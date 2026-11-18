import httpx
import pytest

from atra import contracts as c
from atra.contracts import Role
from population.app import build_app


@pytest.fixture
def population(settings, backends):
    return build_app(settings, backends=backends("population"))


async def test_population_tools(population):
    issuer = population.state.backends.issuer
    svc = {"Authorization": f"Bearer {issuer.issue_service('ahdt-svc')}",
           "X-Actor-Role": "medical_officer", "X-Actor-Id": "wb-orchestrator"}
    person = {"Authorization": f"Bearer {issuer.issue('p', Role.PERSON)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=population),
                                 base_url="http://pop") as cl:
        r = await cl.post("/v1/tools/population.priors", headers=svc, json={
            "conditions": ["62676009"], "age_band": "45-49", "sex": "female",
            "region": "Lagos", "season": "rainy"})
        assert r.status_code == 200
        c.PriorsData.model_validate({k: v for k, v in r.json().items() if k != "_meta"})
        r = await cl.post("/v1/tools/population.contribute", headers=person,
                          json={"contract": "registry_case", "records": [{"x": 1}]})
        assert r.status_code == 403
        card = (await cl.get("/a2a/ahdt-orchestrator-population/.well-known/agent-card.json"))
        assert card.json()["name"] == "ahdt-orchestrator-population"
