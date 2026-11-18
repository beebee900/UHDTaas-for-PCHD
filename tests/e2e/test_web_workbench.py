"""Clinician workbench flow: sign in, open a persona from the worklist, read the
explanation, accept the recommendation, and open a twin drill-down.

Needs `make demo-users` and `npm run build` in apps/web. Starts OPA, the APDT and AHDT
services and the Next.js server, then drives Chromium with Playwright.
"""

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atra.config import ROOT
from tests.e2e.test_web_smoke import (  # noqa: F401
    ENV_FILE,
    WEB,
    _password,
    _port_free,
    _wait,
    browser,
)

pytestmark = pytest.mark.e2e
READY = "all services are healthy"


def _start_services(log: Path) -> subprocess.Popen:
    # The launcher prints the ready line after the services are healthy and the demo
    # episodes are open, which can take several minutes on a loaded laptop.
    services = subprocess.Popen(
        [sys.executable, "-u", "run.py", "--profile", "p0", "--only", "ahdt,apdt"], cwd=ROOT,
        stdout=log.open("w"), stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if services.poll() is not None:
            raise RuntimeError(f"run.py exited with {services.returncode}")
        if READY in log.read_text():
            return services
        time.sleep(2)
    services.terminate()
    raise RuntimeError("the AHDT and APDT services did not become ready")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if not ENV_FILE.exists() or not (WEB / ".next" / "BUILD_ID").exists():
        pytest.skip("run `make demo-users` and `npm run build` in apps/web first")
    busy = [port for port in (3000, 8100, 8181, 8200) if not _port_free(port)]
    if busy:
        pytest.fail(f"ports already in use: {busy}")
    services = _start_services(tmp_path_factory.mktemp("services") / "run.log")
    web = None
    try:
        web = subprocess.Popen(["npm", "run", "start"], cwd=WEB,
                               env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"},
                               stdout=subprocess.DEVNULL, start_new_session=True)
        _wait("http://127.0.0.1:3000/en/login", web)
        yield "http://127.0.0.1:3000"
    finally:
        # npm starts next-server as a child, so the whole process group is stopped.
        if web is not None:
            os.killpg(web.pid, signal.SIGTERM)
        services.terminate()
        for proc in (web, services):
            if proc is None:
                continue
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_medical_officer_reviews_and_accepts_the_recommendation(stack, browser):  # noqa: F811
    page = browser.new_page()
    # The AHDT panel evaluates 17 twin models; on a loaded laptop a page can take over 30 s.
    page.set_default_timeout(90_000)
    page.goto(f"{stack}/en/login")
    page.get_by_label("Username").fill("medical_officer.fac-a")
    page.get_by_label("Password").fill(_password("medical_officer.fac-a"))
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("heading", name="Dashboard").wait_for()

    review = re.compile("Open the workbench for Review diagnosis for A.O.")
    page.get_by_role("link", name=review).first.click()
    page.get_by_role("heading", name="Clinician workbench").wait_for()
    assert page.get_by_text("Plasmodium falciparum malaria", exact=True).first.is_visible()
    assert page.get_by_test_id("source-ahdt").count() >= 1
    page.get_by_test_id("twin-tile").nth(16).wait_for()
    assert page.get_by_test_id("twin-tile").count() == 17

    page.get_by_role("button", name="Why?").first.click()
    dialog = page.get_by_role("dialog")
    assert dialog.get_by_text("Evidence for").is_visible()
    assert dialog.get_by_text("Malaria rapid diagnostic test (PfHRP2): positive").is_visible()
    dialog.get_by_role("button", name="Close").click()

    page.get_by_test_id("agent-step").first.wait_for()
    assert page.get_by_role("heading", name="Agent steps").is_visible()
    steps_before = page.get_by_test_id("agent-step").count()
    assert steps_before >= 1

    page.get_by_role("button", name="Accept").click()
    page.get_by_test_id("decision-recorded").wait_for()
    assert page.get_by_test_id("agent-step").count() >= steps_before

    page.get_by_role("link", name="Open the Heart and blood vessels twin").click()
    page.wait_for_url(re.compile(r"/twins/cardiovascular$"))
    page.get_by_role("heading", name="Current state").wait_for()
    assert page.get_by_role("rowheader", name="heart_rate").is_visible()

    page.get_by_role("button", name="Run agents").click()
    page.get_by_test_id("agent-goal").first.wait_for()
    status = page.get_by_test_id("goal-status").first.inner_text()
    assert status in {"Met", "Unmet", "Not evaluated"}
