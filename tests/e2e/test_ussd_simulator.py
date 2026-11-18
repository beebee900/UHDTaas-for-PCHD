"""MSC4 end to end on the USSD simulator (WP20 acceptance 2): A.O. dials the short code on
the phone-shaped page, withholds the genome, confirms, and receives the SMS; the APDT and
its gateway consent hold the choice. Starts OPA, the APDT and the channels service in
process and drives Chromium with Playwright."""

import httpx
import pytest

from apdt.app import build_app as build_apdt
from atra.backends import Backends
from atra.config import InfraUrls, Settings
from atra.personas import BY_KEY
from atra.telemetry import span_store
from channels.apdt_client import ApdtClient
from channels.app import build_app as build_channels
from tests.contract.conftest import LiveServer

pytestmark = pytest.mark.e2e

AO = BY_KEY["ao"]
MSC4 = ["ussd.session_start", "communication.data_uses", "communication.consent_decision",
        "apdt.consent.store", "apdt.gateway.consent_update", "communication.confirmation_sms"]


@pytest.fixture
def stack(tmp_path, opa):
    settings = Settings(var_dir=tmp_path, infra=InfraUrls(opa=opa.url))
    apdt = build_apdt(settings, backends=Backends(settings, "apdt", ephemeral=True))
    issuer = apdt.state.backends.issuer
    client = ApdtClient("http://apdt", lambda: issuer.issue_service("channels-svc"),
                        transport=httpx.ASGITransport(app=apdt))
    channels = build_channels(settings, backends=Backends(settings, "channels", ephemeral=True),
                              apdt=client)
    with LiveServer(channels) as server:
        yield apdt, channels, server.url


def test_msc4_on_the_ussd_simulator(stack):
    from playwright.sync_api import sync_playwright

    apdt, channels, url = stack
    menu = channels.state.menu
    span_store().clear()
    choices = ["2" if i["id"] == "genome" else "1" for i in menu.consent_items]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{url}/simulator")
        screen = page.get_by_test_id("screen")
        page.get_by_test_id("dial").click()
        page.wait_for_function("document.getElementById('screen').textContent"
                               ".includes('Consent')")
        for entry in ["5", "1", *choices]:
            before = screen.text_content()
            page.get_by_test_id("entry").fill(entry)
            page.get_by_test_id("send").click()
            page.wait_for_function("t => document.getElementById('screen').textContent !== t",
                                   arg=before)
        assert "Genome" in screen.text_content()
        page.get_by_test_id("entry").fill("1")
        page.get_by_test_id("send").click()
        page.get_by_test_id("sms").locator("li").first.wait_for()
        assert screen.text_content() == menu.t("consent.saved", AO.language)
        assert page.get_by_test_id("sms").locator("li").all_text_contents() == [
            menu.t("consent.sms", AO.language)]
        page.set_viewport_size({"width": 360, "height": 740})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
    consent = apdt.state.consents.get(AO.hdt_id)
    assert "ahdt.data.genome" in consent.refused_tools and "care" in consent.purposes
    names = [s.name for s in sorted(span_store().get_finished_spans(),
                                    key=lambda s: s.start_time) if s.name in MSC4]
    assert names == MSC4
