"""Vendor adapters against the samples of each vendor's public documentation (fixtures record
the page and retrieval date; `kind` says whether the body is a verbatim sample, the schema's
own example values, or only the documented schema)."""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ahdt.devices.vendors import dexcom, fitbit, garmin, polar, withings
from ahdt.devices.vendors.base import Token, VendorError, pkce_challenge
from ahdt.ingest import build_pipeline
from ahdt.models.catalogue import default_catalogue
from atra import units
from atra.backends import Backends
from atra.config import Settings
from atra.consent import demo_registry
from atra.provenance import AuditLog
from edge.devices.sim.cloud import DexcomCloud
from synth.streams import persona_stream

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
KINDS = {"verbatim_sample", "schema_examples", "documented_schema"}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["body"]


class Recorder:
    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def client(self):
        def handle(request):
            self.requests.append(request)
            for prefix, body in self.routes.items():
                if str(request.url).startswith(prefix):
                    return httpx.Response(200, json=body)
            return httpx.Response(404)
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))

    def form(self, i=-1):
        return {k: v[0] for k, v in parse_qs(self.requests[i].content.decode()).items()}


def test_fixtures_name_their_source():
    for path in FIXTURES.glob("*.json"):
        doc = json.loads(path.read_text())
        assert doc["source_url"].startswith("https://") and doc["retrieved"] == "2026-10-10"
        assert doc["kind"] in KINDS, path.name


def test_pkce_matches_rfc7636_appendix_b():
    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


async def test_fitbit_oauth_and_mappers():
    rec = Recorder({fitbit.TOKEN_URL: fixture("fitbit_token_refresh"),
                    f"{fitbit.API}/1/user/-/activities/heart": fixture("fitbit_heart_intraday"),
                    f"{fitbit.API}/1/user/-/spo2": fixture("fitbit_spo2_summary")})
    client = fitbit.Fitbit(fitbit.config("cid", "secret", "https://atra.test/cb"), rec.client(),
                           clock=lambda: NOW)
    url = urlsplit(client.authorization_url("s1", code_challenge="abc"))
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == fitbit.AUTHORIZE_URL
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["heartrate oxygen_saturation"]
    with pytest.raises(VendorError):
        client.authorization_url("s1")
    token = await client.exchange("code-1", code_verifier="v" * 43)
    assert rec.form() == {"grant_type": "authorization_code", "code": "code-1",
                          "redirect_uri": "https://atra.test/cb", "code_verifier": "v" * 43}
    assert rec.requests[-1].headers["authorization"].startswith("Basic ")
    assert token.user_id == "GGNJL9" and token.expires_at == NOW.replace(hour=17)
    await client.refresh(token)
    assert rec.form()["grant_type"] == "refresh_token"
    hr = await client.heart_rate(token, date(2019, 5, 8))
    assert [r.value for r in hr] == [78, 78, 77, 77, 77]
    assert hr[1].time == datetime(2019, 5, 8, 0, 1, tzinfo=UTC) and hr[0].code.code == "8867-4"
    assert rec.requests[-1].url.params["timezone"] == "UTC"
    spo2 = await client.spo2(token, date(2021, 10, 4))
    assert [(r.code.code, r.value, r.unit) for r in spo2] == [("59408-5", 97.5, "%")]


async def test_polar_oauth_and_mappers():
    token_body = {"access_token": "a", "token_type": "bearer", "expires_in": 31535999,
                  "x_user_id": 10001}
    rec = Recorder({polar.TOKEN_URL: token_body,
                    f"{polar.API}/v3/users/continuous-heart-rate":
                        fixture("polar_continuous_heart_rate"),
                    f"{polar.API}/v3/users/biosensing": fixture("polar_body_temperature")})
    client = polar.Polar(polar.config("cid", "secret", "https://atra.test/cb"), rec.client(),
                         clock=lambda: NOW)
    assert client.authorization_url("s").startswith(polar.AUTHORIZE_URL + "?response_type=code")
    token = await client.exchange("c")
    assert token.user_id == "10001" and token.refresh_token is None
    with pytest.raises(VendorError):
        await client.refresh(token)
    hr = await client.heart_rate(token, date(2022, 9, 12))
    assert [(r.value, r.time) for r in hr] == [
        (63, datetime(2022, 9, 12, 0, 2, 8, tzinfo=UTC)),
        (62, datetime(2022, 9, 12, 0, 7, 8, tzinfo=UTC))]
    temp = await client.temperature(token)
    assert [(r.code.code, r.value, r.unit) for r in temp] == [("8310-5", 36.5, "Cel")]
    assert temp[0].time == datetime(2023, 10, 20, 4, 0, 0, 123000, tzinfo=UTC)


async def test_withings_oauth_and_mappers():
    rec = Recorder({withings.TOKEN_URL: fixture("withings_token"),
                    withings.MEASURE_URL: fixture("withings_getmeas")})
    client = withings.Withings(withings.config("cid", "secret", "https://atra.test/cb"),
                               rec.client(), clock=lambda: NOW)
    q = parse_qs(urlsplit(client.authorization_url("s")).query)
    assert q["scope"] == ["user.info,user.metrics,user.activity"]
    token = await client.exchange("c")
    form = rec.form()
    assert form["action"] == "requesttoken" and form["client_secret"] == "secret"
    assert "authorization" not in rec.requests[-1].headers
    assert token.user_id == "363" and token.refresh_token.startswith("f631")
    await client.refresh(token)
    assert rec.form()["grant_type"] == "refresh_token"
    found = await client.measures(token, NOW, NOW)
    assert rec.form()["action"] == "getmeas"
    assert [(r.code.code, r.value, r.unit) for r in found] == [("29463-7", 65.75, "kg")]
    assert found[0].time == datetime.fromtimestamp(1594245600, UTC)
    bp = withings.measures({"status": 0, "body": {"measuregrps": [{"date": 1594245600,
        "category": 1, "measures": [{"value": 1205, "type": 10, "unit": -1},
                                    {"value": 178, "type": 4, "unit": -2}]}]}})
    assert [(r.code.code, r.value) for r in bp] == [("8480-6", 120.5),
                                                    ("8302-2", pytest.approx(1.78))]
    with pytest.raises(VendorError):
        withings.measures({"status": 401})


async def test_dexcom_oauth_and_documented_schema():
    rec = Recorder({f"{dexcom.SANDBOX}/v3/oauth2/token": fixture("dexcom_token"),
                    f"{dexcom.SANDBOX}/v3/users/self/egvs": fixture("dexcom_egvs")})
    client = dexcom.Dexcom(dexcom.config("cid", "secret", "https://atra.test/cb"), rec.client(),
                           clock=lambda: NOW)
    url = client.authorization_url("s")
    assert url.startswith("https://sandbox-api.dexcom.com/v3/oauth2/login?")
    assert parse_qs(urlsplit(url).query)["scope"] == ["offline_access"]
    token = await client.exchange("c")
    assert rec.form()["client_id"] == "cid" and token.expires_at == NOW.replace(hour=11)
    glucose = await client.glucose(token, datetime(2025, 2, 6), datetime(2025, 2, 7))
    assert rec.requests[-1].url.params["startDate"] == "2025-02-06T00:00:00"
    assert [r.value for r in glucose] == [pytest.approx(108 / 18.0156, rel=1e-3)]
    assert glucose[0].unit == "mmol/L" and glucose[0].time.tzinfo is UTC


async def test_garmin_flow_without_a_public_schema():
    rec = Recorder({"https://partner.test/token": {"access_token": "g", "expires_in": 60}})
    client = garmin.Garmin(garmin.config("cid", "s", "https://atra.test/cb",
                                         authorize_url="https://partner.test/authorize",
                                         token_url="https://partner.test/token"),
                           rec.client(), clock=lambda: NOW)
    assert "code_challenge=x" in client.authorization_url("s", code_challenge="x")
    assert (await client.exchange("c", code_verifier="v")).access_token == "g"
    with pytest.raises(VendorError):
        garmin.summaries({})


@pytest.fixture(scope="module")
def de_stream():
    return asyncio.run(persona_stream("de", default_catalogue(), hours=1, step_s=900))


async def test_cgm_stream_reaches_the_endocrine_twin(tmp_path, de_stream):
    body = DexcomCloud("cgm-1", de_stream).egvs()
    rec = Recorder({f"{dexcom.SANDBOX}/v3/users/self/egvs": body})
    client = dexcom.Dexcom(dexcom.config("cid", "s", "https://atra.test/cb"), rec.client())
    readings = await client.glucose(Token("t", None, None), de_stream.start, de_stream.start)
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    raws = [r.raw(hdt_id=de_stream.hdt_id, device_id="cgm-1", key=f"dexcom-{i}")
            for i, r in enumerate(readings)]
    result = await pipeline.process(raws)
    assert len(result.accepted) == 13 and not result.rejected
    truth = de_stream.at("glucose", 0.0)
    one_mg = units.convert(1.0, "mg/dL", "mmol/L", substance="glucose")
    for record in result.accepted:
        assert record.code.code == "15074-8" and record.unit == "mmol/L"
        assert record.dt.value == "endocrine"
        assert abs(record.value - truth) <= one_mg / 2 + 1e-9
    again = await pipeline.process(raws)
    assert len(again.duplicates) == 13
    await backends.close()
