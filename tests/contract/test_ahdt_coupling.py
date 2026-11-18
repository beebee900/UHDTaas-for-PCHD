from starlette.testclient import TestClient

from ahdt.app import build_app
from ahdt.coupling.manager import connector_name, hdt_pairs
from ahdt.coupling.service import CouplingMatrix
from ahdt.registry import load_registry
from atra.contracts import Role
from atra.personas import BY_KEY

HDT = BY_KEY["ao"].hdt_id


def test_coupling_matrix_route_lists_every_connector(settings, backends):
    app = build_app(settings, backends=backends("ahdt"))
    issuer = app.state.backends.issuer
    admin = {"authorization": "Bearer " + issuer.issue("ops-1", Role.ADMINISTRATOR)}
    own = {"authorization": "Bearer " + issuer.issue("p", Role.PERSON, hdt_id=HDT)}
    other = {"authorization": "Bearer " + issuer.issue(
        "p2", Role.PERSON, hdt_id=BY_KEY["gh"].hdt_id)}
    with TestClient(app) as client:
        r = client.get(f"/v1/persons/{HDT}/coupling", headers=admin)
        assert r.status_code == 200
        body = CouplingMatrix.model_validate(r.json())
        assert body.running and body.hdt_id == HDT
        assert {c.name for c in body.connectors} == {
            connector_name(*p) for p in hdt_pairs(load_registry())}
        assert body.count == len(body.connectors) == 53
        assert "in" in r.json()["connectors"][0]
        assert all(c.state == "running" for c in body.connectors)
        assert client.get(f"/v1/persons/{HDT}/coupling", headers=own).status_code == 200
        assert client.get(f"/v1/persons/{HDT}/coupling", headers=other).status_code == 403
        assert client.get("/v1/persons/hdt-000000000000/coupling",
                          headers=admin).status_code == 404
    assert app.state.coupling.hdts == {}
