"""Web scaffold smoke test (WP01 acceptance): login page and stubbed dashboard.

Needs `make demo-users` and `npm run build` in apps/web. Starts OPA, the APDT service and
the Next.js server, then drives Chromium with Playwright.
"""

import os
import signal
import subprocess
import sys
import time

import httpx
import pytest

from atra.config import ROOT

pytestmark = pytest.mark.e2e

WEB = ROOT / "apps" / "web"
ENV_FILE = ROOT / "deploy" / "keycloak" / "demo-users.local.env"
AXE = WEB / "node_modules" / "axe-core" / "axe.min.js"


def _port_free(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/", timeout=0.5)
    except httpx.HTTPError:
        return True
    return False


def _wait(url: str, proc: subprocess.Popen, timeout_s: float = 90) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process for {url} exited with {proc.returncode}")
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


def _password(username: str) -> str:
    key = "DEMO_USER_" + username.upper().replace(".", "_").replace("-", "_") + "="
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith(key):
            return line[len(key):]
    raise LookupError(username)


@pytest.fixture(scope="module")
def stack():
    if not ENV_FILE.exists() or not (WEB / ".next" / "BUILD_ID").exists():
        pytest.skip("run `make demo-users` and `npm run build` in apps/web first")
    busy = [port for port in (3000, 8181, 8200) if not _port_free(port)]
    if busy:
        pytest.fail(f"ports already in use: {busy}")
    apdt = subprocess.Popen([sys.executable, "run.py", "--profile", "p0", "--only", "apdt"],
                            cwd=ROOT)
    web = subprocess.Popen(["npm", "run", "start"], cwd=WEB,
                           env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"},
                           stdout=subprocess.DEVNULL, start_new_session=True)
    try:
        _wait("http://127.0.0.1:8200/health", apdt)
        _wait("http://127.0.0.1:3000/en/login", web)
        yield "http://127.0.0.1:3000"
    finally:
        # npm starts next-server as a child, so the whole process group is stopped.
        os.killpg(web.pid, signal.SIGTERM)
        apdt.terminate()
        for proc in (web, apdt):
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chromium = pw.chromium.launch()
        yield chromium
        chromium.close()


def _axe_violations(page) -> list:
    page.add_script_tag(path=str(AXE))
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']})")
    return result["violations"]


def test_login_page_is_accessible(stack, browser):
    page = browser.new_page()
    page.goto(f"{stack}/en/login")
    assert page.get_by_role("heading", name="Sign in").is_visible()
    assert [v["id"] for v in _axe_violations(page)] == []


def test_medical_officer_sees_the_stubbed_dashboard(stack, browser):
    page = browser.new_page()
    page.goto(f"{stack}/en/login")
    page.get_by_label("Username").fill("medical_officer.fac-a")
    page.get_by_label("Password").fill(_password("medical_officer.fac-a"))
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("heading", name="Dashboard").wait_for()
    assert page.get_by_test_id("twin-tile").count() == 17
    assert page.get_by_text("Review A.O.").is_visible()
    assert [v["id"] for v in _axe_violations(page)] == []


def test_wrong_password_is_refused(stack, browser):
    page = browser.new_page()
    page.goto(f"{stack}/en/login")
    page.get_by_label("Username").fill("medical_officer.fac-a")
    page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Sign in").click()
    page.get_by_text("The username or password is not correct.").wait_for()


def test_yoruba_locale_shows_yoruba_text(stack, browser):
    page = browser.new_page()
    page.goto(f"{stack}/yo/login")
    assert page.locator("html").get_attribute("lang") == "yo"
    assert page.get_by_role("heading", name="Wọlé").is_visible()
