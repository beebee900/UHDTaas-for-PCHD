"""Flutter web scaffold smoke test (WP01 acceptance): login page and stubbed dashboard.

Needs `make demo-users` and `make mobile`. Starts OPA, the APDT service and a static server
for the ward app's web build, then drives Chromium through Flutter's semantics tree.
"""

import signal
import subprocess
import sys
import time

import httpx
import pytest

from atra.config import ROOT

pytestmark = pytest.mark.e2e

BUILD = ROOT / "apps" / "mobile" / "build" / "web"
ENV_FILE = ROOT / "deploy" / "keycloak" / "demo-users.local.env"


def _password(username: str) -> str:
    key = "DEMO_USER_" + username.upper().replace(".", "_").replace("-", "_") + "="
    return next(line[len(key):] for line in ENV_FILE.read_text().splitlines()
                if line.startswith(key))


@pytest.fixture(scope="module")
def ward_app():
    if not ENV_FILE.exists() or not (BUILD / "main.dart.js").exists():
        pytest.skip("run `make demo-users` and `make mobile` first")
    apdt = subprocess.Popen([sys.executable, "run.py", "--only", "apdt"], cwd=ROOT)
    static = subprocess.Popen([sys.executable, "-m", "http.server", "8400", "--bind",
                               "127.0.0.1", "-d", str(BUILD)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 90
        while True:
            try:
                if httpx.get("http://127.0.0.1:8200/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline or apdt.poll() is not None:
                raise RuntimeError("the APDT service did not start")
            time.sleep(0.5)
        yield "http://127.0.0.1:8400/"
    finally:
        static.send_signal(signal.SIGTERM)
        apdt.terminate()
        apdt.wait(timeout=15)
        static.wait(timeout=5)


def test_nurse_signs_in_to_the_ward_web_app(ward_app):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(ward_app)
        page.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=60000)
        page.evaluate("document.querySelector('flt-semantics-placeholder').click()")
        # Flutter's text fields take key events, not a value set from outside.
        page.get_by_role("textbox", name="Username").click()
        page.keyboard.type("nurse.fac-a")
        page.get_by_role("textbox", name="Password").click()
        page.keyboard.type(_password("nurse.fac-a"))
        page.get_by_role("button", name="Sign in").click()
        page.get_by_text("Review A.O.").wait_for(timeout=30000)
        assert page.get_by_text("All changes are sent.").is_visible()
        assert errors == []
        browser.close()
