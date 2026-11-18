import pytest

from atra.contracts import Role
from atra.provenance import AuditLog, ChainBroken, ProvenanceStore, verify_chain
from atra.security import InvalidToken, Keyring, KeyShredded, LocalIssuer, TokenVerifier

HDT = "hdt-0123456789ab"
ACTOR = {"id": "mo-1", "role": "medical_officer"}


def test_audit_chain_survives_restart_and_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog("ahdt", path=path)
    for outcome in ("ok", "denied", "ok"):
        log.append(actor=ACTOR, action="tool", target="ahdt.model.state", purpose="care",
                   outcome=outcome, hdt_id=HDT)
    reopened = AuditLog("ahdt", path=path)
    assert reopened.verify_chain() == 3
    assert reopened.append(actor=ACTOR, action="tool", target="x", purpose="care",
                           outcome="ok").seq == 3
    records = list(reopened)
    records[1] = records[1].model_copy(update={"outcome": "ok"})
    with pytest.raises(ChainBroken):
        verify_chain(records)
    assert len(reopened.query(outcome="denied")) == 1


def test_prov_lineage():
    store = ProvenanceStore("ahdt")
    obs = store.entity("obs-1", "observation")
    out = store.entity("out-1", "model_output")
    store.activity("predict", used=[obs], generated=[out])
    exp = store.entity("exp-1", "explanation")
    store.derived(exp, out)
    assert store.lineage(exp) == ["atra:out-1", "atra:obs-1"]


def test_tokens():
    issuer = LocalIssuer("https://atra.local/issuer", "atra")
    token = issuer.issue("p-1", Role.PERSON, hdt_id=HDT, scopes=["patient/*.rs"])
    verifier = TokenVerifier(issuer.jwks(), issuer=issuer.issuer, audience="atra")
    claims = verifier.verify(token)
    assert claims.role is Role.PERSON and claims.hdt_id == HDT
    assert "patient/*.rs" in claims.scopes
    with pytest.raises(InvalidToken):
        verifier.verify(token[:-4] + "AAAA")
    other = TokenVerifier(issuer.jwks(), issuer=issuer.issuer, audience="other")
    with pytest.raises(InvalidToken):
        other.verify(token)
    expired = issuer.issue("p-1", Role.PERSON, ttl_s=-120)
    with pytest.raises(InvalidToken):
        verifier.verify(expired)


def test_keyring_rotation_and_crypto_shredding(tmp_path):
    ring = Keyring(tmp_path / "keyring.json")
    sealed = ring.seal(HDT, b"free-text note")
    ring.rotate(HDT)
    assert Keyring(tmp_path / "keyring.json").open(HDT, sealed) == b"free-text note"
    assert ring.shred(HDT)
    with pytest.raises(KeyShredded):
        Keyring(tmp_path / "keyring.json").open(HDT, sealed)
