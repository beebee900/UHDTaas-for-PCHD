import httpx
import pytest

from atra import contracts as c
from atra.backends import Backends
from atra.config import AHDTSettings, InfraUrls, Settings
from atra.connectors import DTKind
from atra.personas import PERSONAS
from population.app import build_app
from population.priors import PopulationPriors, UnknownCondition, slice_age_band, slice_region
from tests.unit.ahdt.coupling.conftest import Rig

CONDITIONS = ["cond.malaria_falciparum", "cond.hypertension", "cond.diabetes_type2",
              "cond.hiv"]


@pytest.fixture
def app(tmp_path, opa, priors_root):
    settings = Settings(var_dir=tmp_path, infra=InfraUrls(opa=opa.url),
                        ahdt=AHDTSettings(grpc_port=None))
    return build_app(settings, backends=Backends(settings, "population", ephemeral=True),
                     models_root=priors_root)


def service_headers(app):
    token = app.state.backends.issuer.issue_service("ahdt-svc")
    return {"Authorization": f"Bearer {token}", "X-Actor-Role": "medical_officer",
            "X-Actor-Id": "wb-orchestrator"}


def test_bands_and_regions():
    assert slice_age_band("45-49") == "40-59" and slice_age_band("0-4") == "0-4"
    assert slice_age_band("8") == "5-17"
    assert slice_region("Surulere") == "mainland_core"
    assert slice_region("north_west") == "north_west"


async def test_priors_for_the_personas_by_season_and_region(app):
    """Acceptance: priors for every persona, both seasons, two regions."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as cl:
        seen = {}
        for persona in PERSONAS:
            for region in ("Surulere", "Ikeja"):
                for season in ("dry", "rainy"):
                    body = {"conditions": CONDITIONS, "age_band": str(persona.age_years),
                            "sex": persona.sex, "region": region, "season": season}
                    r = await cl.post("/v1/tools/population.priors",
                                      headers=service_headers(app), json=body)
                    assert r.status_code == 200, r.text
                    data = c.PriorsData.model_validate({k: v for k, v in r.json().items()
                                                        if k != "_meta"})
                    assert [p.condition for p in data.priors] == CONDITIONS
                    for p in data.priors:
                        assert 0.0 <= p.prevalence <= 1.0 and p.source
                        assert (p.season, p.region) == (season, region)
                        seen[(persona.key, region, season, p.condition)] = (p.prevalence, p.source)
    assert len(seen) == len(PERSONAS) * 2 * 2 * len(CONDITIONS)
    sources = {s for _, s in seen.values()}
    assert any(s.startswith("ahdt.population.population_priors_and_norms") for s in sources)
    assert "kb:prior.malaria_falciparum" in sources


async def test_condition_without_a_prevalence_is_not_found(app):
    """The kb TB entry gives an incidence, not a prevalence."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as cl:
        r = await cl.post("/v1/tools/population.priors", headers=service_headers(app),
                          json={"conditions": ["cond.tb_pulmonary"], "age_band": "30-34",
                                "sex": "male", "region": "Ikeja", "season": "dry"})
    assert r.status_code == 404


def test_seasonal_cells_and_kb_fallback(priors):
    rainy = priors.prior("cond.malaria_falciparum", "0-4", "female", "rainy", "Surulere")
    dry = priors.prior("cond.malaria_falciparum", "0-4", "female", "dry", "Surulere")
    assert rainy.source == dry.source and rainy.source.startswith("ahdt.population")
    assert rainy.prevalence > dry.prevalence
    adult = priors.prior("cond.malaria_falciparum", "47", "female", "rainy", "Surulere")
    assert adult.source == "kb:prior.malaria_falciparum"
    assert priors.prior("62676009", "0-4", "male", "dry", "Ikeja").condition == \
        "cond.malaria_falciparum"
    with pytest.raises(UnknownCondition):
        priors.prior("cond.asthma", "47", "female", "rainy", "Surulere")


def test_untrained_service_uses_the_kb_seeds(tmp_path, kb):
    priors = PopulationPriors.load(kb, tmp_path)
    p = priors.prior("cond.hypertension", "47", "female", "dry", "Ikeja")
    assert p.source == "kb:prior.hypertension"
    assert p.prevalence == pytest.approx(0.434)


async def test_norms_tool(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as cl:
        r = await cl.post("/v1/tools/population.norms", headers=service_headers(app),
                          json={"fields": ["sbp", "glucose"], "age_band": "40-44", "sex": "male"})
    assert r.status_code == 200, r.text
    norms = c.NormsData.model_validate({k: v for k, v in r.json().items() if k != "_meta"}).norms
    assert [(n.field, n.unit) for n in norms] == [("sbp", "mm[Hg]"), ("glucose", "mmol/L")]
    assert all(n.p05 < n.p50 < n.p95 and n.n >= 5 for n in norms)


async def test_prior_and_norms_connectors_reply_from_the_population_twin(opa, app):
    service = app.state.population
    rig = Rig(opa.url, query_providers=service.query_providers())
    await rig.start()
    try:
        prior_c, _ = await rig.connector("PriorConnector", DTKind.POPULATION,
                                             DTKind.WHOLE_BODY)
        msg = await prior_c.request({"condition": "cond.hypertension", "age_band": "40-59",
                                     "sex": "male", "season": "dry", "region": "north_west"})
        expected = service.priors.prior("cond.hypertension", "40-59", "male", "dry", "north_west")
        assert msg.payload["prevalence"] == pytest.approx(expected.prevalence)
        assert msg.payload["region"] == "north_west"
        norm_c, _ = await rig.connector("NormsConnector", DTKind.POPULATION,
                                        DTKind.CARDIOVASCULAR)
        msg = await norm_c.request({"field": "sbp", "age_band": "40-59", "sex": "male"})
        assert msg.payload["field"] == "sbp" and msg.payload["p05"] < msg.payload["p95"]
    finally:
        await rig.stop()
