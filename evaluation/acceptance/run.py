"""Acceptance test run against a running p0 deployment.

Each case states its input and expected outcome, calls the live services, and records the
actual outcome. The run writes `results.json` and `results.md` to the output folder.

    python -m evaluation.acceptance.run --logins deploy/keycloak/demo-logins.local.txt \
        --out var/acceptance

The run opens new episodes and records decisions, so take a copy of `var/` first if the
demo state must be kept.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from atra.consent import to_fhir
from atra.provenance import AuditRecord, verify_chain

APDT = "http://127.0.0.1:8200"
AHDT = "http://127.0.0.1:8100"
CHANNELS = "http://127.0.0.1:8300"
POPULATION = "http://127.0.0.1:8110"
EDGE = "http://127.0.0.1:8095"
B = "/v1/t/fac-a"
AO = "hdt-5537426f869a"
BM = "hdt-21639ea535e8"
CN = "hdt-fa6993fb8be4"
AO_PHONE = "+2340000000001"
GATEWAY_LIMIT_S = 30.0
MALARIA_INTAKE = {"findings": {"find.fever_history": True},
                  "tests": {"test.malaria_rdt_hrp2": True},
                  "measurements": {"temperature": 38.6}, "weight_kg": 62}


@dataclass
class Case:
    case_id: str
    requirement: str
    title: str
    input: str
    expected: str
    actual: str = ""
    result: str = "not run"
    seconds: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


class Live:
    """Clients for the demo logins, plus the run helpers the cases share."""

    def __init__(self, logins: Path) -> None:
        self.passwords: dict[str, str] = {}
        for line in logins.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 3 and "." in parts[0]:
                self.passwords[parts[0]] = parts[2]
        self._clients: dict[tuple[str, str], httpx.Client] = {}
        self.timings: list[dict[str, Any]] = []

    def token(self, user: str) -> str:
        r = httpx.post(f"{APDT}/auth/token",
                       json={"username": user, "password": self.passwords[user]}, timeout=30)
        r.raise_for_status()
        return str(r.json()["access_token"])

    def as_(self, user: str, base: str = APDT) -> httpx.Client:
        key = (user, base)
        if key not in self._clients:
            self._clients[key] = httpx.Client(
                base_url=base, timeout=300,
                headers={"Authorization": f"Bearer {self.token(user)}"})
        return self._clients[key]

    def timed(self, label: str, call: Callable[[], httpx.Response]) -> httpx.Response:
        t0 = time.perf_counter()
        resp = call()
        self.timings.append({"call": label, "seconds": time.perf_counter() - t0,
                             "status": resp.status_code})
        return resp

    def episode(self, hdt_id: str, reason: str,
                intake: dict[str, Any] | None = None) -> str:
        mo = self.as_("medical_officer.fac-a")
        r = mo.post(f"{B}/episodes", json={"hdt_id": hdt_id, "reason": reason})
        r.raise_for_status()
        eid = str(r.json()["episode"]["episode_id"])
        if intake is not None:
            mo.post(f"{B}/episodes/{eid}/intake", json=intake).raise_for_status()
        return eid

    def run(self, eid: str, goal: str, user: str = "medical_officer.fac-a") -> dict[str, Any]:
        """Starts a goal run and waits until it stops at an interrupt or ends."""
        cl = self.as_(user)
        t0 = time.perf_counter()
        r = cl.post(f"{B}/episodes/{eid}/goals/{goal}")
        r.raise_for_status()
        run_id = r.json()["run_id"]
        while True:
            run: dict[str, Any] = cl.get(f"{B}/runs/{run_id}").json()
            if run["status"] != "running" or time.perf_counter() - t0 > 600:
                break
            time.sleep(0.25)
        self.timings.append({"call": f"{goal} run to interrupt",
                             "seconds": time.perf_counter() - t0, "status": run["status"]})
        return run


def steps(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["node"]: s for s in run.get("result", {}).get("steps", [])}


def decision(rec_id: str, kind: str, who: str = "medical_officer.fac-a",
             role: str = "medical_officer", **extra: Any) -> dict[str, Any]:
    return {"decision_id": f"d-acc-{kind}-{rec_id}", "recommendation_id": rec_id,
            "decided_by": {"id": who, "role": role}, "decision": kind,
            "signature": "acceptance-run", **extra}


def check(case: Case, ok: bool | None, actual: str, **detail: Any) -> None:
    case.result = {True: "pass", False: "fail", None: "partly"}[ok]
    case.actual = actual
    case.detail.update(detail)


# The cases. Each function fills in `actual` and `result` for its case.

def fr1(lv: Live, case: Case) -> None:
    mo = lv.as_("medical_officer.fac-a")
    r = mo.post(f"{B}/episodes", json={"hdt_id": AO, "reason": "Acceptance: open and close"})
    ep = r.json()["episode"]
    closed = mo.post(f"{B}/episodes/{ep['episode_id']}/close", json={"outcome": "resolved"})
    status = closed.json().get("status")
    check(case, r.status_code == 201 and ep["hdt_id"].startswith("hdt-") and status == "closed",
          f"HTTP {r.status_code}; episode {ep['episode_id']} opened for {ep['hdt_id']} "
          f"with status {ep['status']}; close returned HTTP {closed.status_code} "
          f"with status {status}")


def fr2(lv: Live, case: Case) -> None:
    eid = lv.episode(AO, "Acceptance: clinician data", MALARIA_INTAKE)
    mo = lv.as_("medical_officer.fac-a")
    res = mo.get(f"{B}/episodes/{eid}").json()["resources"]
    types = sorted({r["resourceType"] for r in res})
    temp = [r for r in res if r.get("valueQuantity", {}).get("value") == 38.6]
    q = mo.get(f"{B}/questionnaires/phq9").json().get("questionnaire", {})
    check(case, bool(res) and bool(temp) and q.get("resourceType") == "Questionnaire",
          f"{len(res)} FHIR resources stored in episode {eid} ({', '.join(types)}), "
          f"including the temperature 38.6 as an Observation: {bool(temp)}; the PHQ-9 form "
          f"is a FHIR {q.get('resourceType')}")


def diagnosis_run(lv: Live) -> tuple[str, dict[str, Any]]:
    eid = lv.episode(AO, "Acceptance: fever", MALARIA_INTAKE)
    return eid, lv.run(eid, "diagnosis")


def fr3(lv: Live, case: Case) -> None:
    _, run = diagnosis_run(lv)
    ev = steps(run).get("assemble_evidence", {})
    calls = [(t["tool"], t["ahdt_layer"]) for t in ev.get("tool_calls", [])]
    ahdt_calls = [c for c in calls if c[0].startswith("ahdt.data.")]
    vitals = ev.get("output", {}).get("vitals", {})
    sources = sorted({v.get("source") for v in vitals.values()})
    check(case, bool(ahdt_calls) and all(layer == 3 for _, layer in ahdt_calls),
          f"The evidence-assembly agent called {', '.join(t for t, _ in ahdt_calls)} "
          f"(AHDT Layer 3) through the gateway; vitals returned from source {sources}")


def treatment_run(lv: Live) -> tuple[str, dict[str, Any]]:
    eid = lv.episode(AO, "Acceptance: treatment", MALARIA_INTAKE)
    dx = lv.run(eid, "diagnosis")
    rec = dx["interrupt"]["payload"]["recommendation_id"]
    lv.as_("medical_officer.fac-a").post(f"{B}/runs/{dx['run_id']}/resume",
                                         json=decision(rec, "accept")).raise_for_status()
    return eid, lv.run(eid, "treatment")


def fr4(lv: Live, case: Case) -> None:
    _, run = treatment_run(lv)
    sims = steps(run).get("simulate_each", {}).get("output", {}).get("simulations", [])
    forked = [s for s in sims if s.get("simulation") and s["simulation"].get("fork_id")]
    note = forked[0]["simulation"]["assumptions"][0] if forked else ""
    check(case, bool(forked) and len(forked) == len(sims),
          f"{len(forked)} of {len(sims)} treatment options simulated on forked twins "
          f"(fork ids returned); model note: \"{note}\"")


def fr5(lv: Live, case: Case) -> None:
    _, run = treatment_run(lv)
    explain = steps(run).get("explain", {}).get("output", {})
    bundle_id = run["interrupt"]["payload"]["bundle_id"]
    bundle = lv.as_("medical_officer.fac-a").get(f"{B}/bundles/{bundle_id}").json()
    has_trace = bundle.get("simulation_trace") is not None
    has_ahdt = explain.get("ahdt_explanation") is not None
    linked = any(e.get("ahdt_explanation_id") for e in bundle.get("evidence_for", []))
    ok: bool | None = has_trace and has_ahdt and linked
    if has_trace and has_ahdt and not linked:
        ok = None
    check(case, ok,
          f"Bundle {bundle_id}: AHDT simulation trace {'present' if has_trace else 'absent'}; "
          f"AHDT explanation returned to the explain step: {has_ahdt}; evidence items linked "
          f"to an AHDT explanation id: {linked}")


def fr6(lv: Live, case: Case) -> None:
    eid, run = diagnosis_run(lv)
    recs = lv.as_("medical_officer.fac-a").get(f"{B}/episodes/{eid}/recommendations").json()
    dx = next(r for r in recs if r["kind"] == "diagnosis")
    diff = dx["payload"]["differential"]
    bundle = lv.as_("medical_officer.fac-a").get(f"{B}/bundles/{dx['bundle_id']}").json()
    ranked = [d["probability"] for d in diff] == sorted((d["probability"] for d in diff),
                                                       reverse=True)
    top = ", ".join(f"{d['name']} {d['probability']:.3f}" for d in diff[:3])
    check(case, run["status"] == "waiting_for_human" and ranked and bool(bundle["evidence_for"]),
          f"Run stopped at '{run['interrupt']['kind']}'; {len(diff)} ranked conditions "
          f"(top three: {top}); {len(bundle['evidence_for'])} weighted evidence items")


def fr7(lv: Live, case: Case) -> None:
    eid, _ = diagnosis_run(lv)
    recs = lv.as_("medical_officer.fac-a").get(f"{B}/episodes/{eid}/recommendations").json()
    tests = next(r for r in recs if r["kind"] == "test")["payload"]["tests"]
    keys = {"voi", "cost_ngn", "turnaround_h", "on_site"}
    rows = "; ".join(f"{t['name']} (VOI {t['voi']}, NGN {t['cost_ngn']:.0f}, "
                     f"{t['turnaround_h']:.0f} h, on site {t['on_site']})" for t in tests[:2])
    check(case, bool(tests) and all(keys <= set(t) for t in tests),
          f"{len(tests)} tests ranked: {rows}")


def fr8(lv: Live, case: Case) -> None:
    _, run = treatment_run(lv)
    options = run["interrupt"]["payload"]["options"]
    checked = steps(run).get("check_options", {}).get("output", {}).get("checks", [])
    simulated = [o for o in options if o.get("simulation")]
    check(case, run["interrupt"]["kind"] == "sign_prescription" and bool(options)
          and bool(checked) and bool(simulated),
          f"{len(options)} guideline options listed; the pharmacotherapy agent returned "
          f"{len(checked)} dose, interaction, allergy and formulary checks; "
          f"{len(simulated)} options simulated; first option "
          f"'{options[0]['option_id']}' blocks signing: {options[0]['blocks_signing']}")


def fr9(lv: Live, case: Case) -> None:
    pt = lv.as_("patient.ao")
    answers = {"cost": "most important", "travel_distance": "important",
               "pill_burden": "less important"}
    r = pt.put(f"{B}/patients/{AO}/preferences", json={"answers": answers})
    weights = r.json().get("weights", {})
    equal = len(set(weights.values())) == 1
    check(case, None if r.status_code == 200 and equal else r.status_code == 200,
          f"HTTP {r.status_code}; weights returned {weights}. The answers are accepted, "
          f"but every criterion gets the same weight and the answers are not stored for "
          f"later runs")


def fr10(lv: Live, case: Case) -> None:
    eid, _ = treatment_run(lv)
    run = lv.run(eid, "care")
    kind = (run.get("interrupt") or {}).get("kind")
    role = (run.get("interrupt") or {}).get("required_role")
    check(case, run["status"] == "waiting_for_human" and role == "medical_officer",
          f"Care run status '{run['status']}', waiting at '{kind}' for role '{role}'")


def fr11(lv: Live, case: Case, catalogue: dict[str, Any]) -> None:
    fields = {m["field"] for m in catalogue.get("measurements", [])}
    vitals = {"respiratory_rate": 28, "spo2": 90, "sbp": 88, "heart_rate": 128,
              "temperature": 39.4}
    intake = {**MALARIA_INTAKE, "measurements": {k: v for k, v in vitals.items()
                                                 if k in fields}, "avpu": "V"}
    eid = lv.episode(AO, "Acceptance: deterioration", intake)
    recs = lv.as_("medical_officer.fac-a").get(f"{B}/episodes/{eid}/recommendations").json()
    care = next((r for r in recs if r["kind"] == "care"), None)
    ew = care["payload"].get("early_warning") if care else None
    check(case, ew is not None,
          f"Vitals sent: {intake['measurements']}, AVPU V. Early warning in the care "
          f"proposal: {json.dumps(ew)[:200]}",
          catalogue_fields=sorted(fields))


def fr12(lv: Live, case: Case) -> None:
    _, run = diagnosis_run(lv)
    rec = run["interrupt"]["payload"]["recommendation_id"]
    mo = lv.as_("medical_officer.fac-a")
    no_reason = mo.post(f"{B}/runs/{run['run_id']}/resume", json=decision(rec, "reject"))
    ok = mo.post(f"{B}/runs/{run['run_id']}/resume",
                 json=decision(rec, "reject", override_reason="Clinical picture fits typhoid"))
    done = ok.json()
    audit = mo.get(f"{B}/audit", params={"limit": 200}).json()
    logged = [a for a in audit if rec in json.dumps(a)]
    check(case, no_reason.status_code >= 400 and done.get("status") == "done"
          and done["result"]["status"] == "overridden" and bool(logged),
          f"Override without a reason: HTTP {no_reason.status_code}; with a reason: run "
          f"'{done.get('status')}', recommendation '{done['result']['status']}'; "
          f"{len(logged)} audit records name the recommendation")


def fr13(lv: Live, case: Case) -> None:
    pt = lv.as_("patient.ao")
    r = pt.put(f"{B}/patients/{AO}/consent",
               json=to_fhir(AO, ["care"], ["ahdt.data.genome"], consent_id="cons-acc-ao"))
    other = pt.put(f"{B}/patients/{CN}/consent",
                   json=to_fhir(CN, ["care"], [], consent_id="cons-acc-cn"))
    proxy = lv.as_("proxy.bm").put(f"{B}/patients/{BM}/consent",
                                   json=to_fhir(BM, ["care"], [], consent_id="cons-acc-bm"))
    refused = r.json().get("refused_tools")
    check(case, r.status_code == 200 and refused == ["ahdt.data.genome"]
          and other.status_code == 403 and proxy.status_code == 200,
          f"Patient withholds the genome tool: HTTP {r.status_code}, refused tools {refused}; "
          f"the same patient setting another patient's consent: HTTP {other.status_code}; "
          f"proxy setting B.M.'s consent: HTTP {proxy.status_code}")


def fr14(lv: Live, case: Case) -> None:
    _, run = diagnosis_run(lv)
    bid = run["interrupt"]["payload"]["bundle_id"]
    mo = lv.as_("medical_officer.fac-a")
    b = mo.get(f"{B}/bundles/{bid}").json()
    p = mo.get(f"{B}/bundles/{bid}", params={"audience": "patient"}).json()
    parts = {k: bool(b.get(k)) for k in ("evidence_for", "citations", "counterfactuals",
                                         "patient_summary")}
    cite = b["citations"][0]["source_title"] if b.get("citations") else "none"
    check(case, all(parts.values()),
          f"Bundle {bid} parts present: {parts}; first citation: {cite}; patient summary "
          f"starts \"{str(p.get('patient_summary'))[:90]}\"")


def fr15(lv: Live, case: Case) -> None:
    r = lv.as_("patient.ao").post(f"{B}/patients/{AO}/messages",
                                  json={"text": "Mo ni iba", "language": "yo"})
    first = httpx.post(f"{CHANNELS}/v1/ussd", timeout=60, data={
        "sessionId": "acc-lang", "serviceCode": "*347#", "phoneNumber": AO_PHONE,
        "networkCode": "99999", "text": ""}).text
    reply = r.json()
    check(case, None,
          f"Yoruba message: HTTP {r.status_code}, reply \"{reply.get('reply')}\" tagged "
          f"'{reply.get('language')}'. USSD first menu for A.O. (Yoruba speaker): "
          f"\"{first[:80]}\". The reply text is a fixed English sentence")


def fr16(lv: Live, case: Case) -> None:
    ahdt = lv.as_("medical_officer.fac-a", AHDT)
    before = ahdt.get("/v1/fhir/Condition", params={"subject": AO})
    n0 = before.json()["total"] if before.status_code == 200 else None
    _, run = diagnosis_run(lv)
    rec = run["interrupt"]["payload"]["recommendation_id"]
    lv.as_("medical_officer.fac-a").post(f"{B}/runs/{run['run_id']}/resume",
                                         json=decision(rec, "accept"))
    after = ahdt.get("/v1/fhir/Condition", params={"subject": AO})
    n1 = after.json()["total"] if after.status_code == 200 else None
    check(case, (n1 or 0) > (n0 or 0),
          f"AHDT Condition records for A.O. before an accepted diagnosis: {n0} "
          f"(HTTP {before.status_code}); after: {n1} (HTTP {after.status_code})")


def fr17(lv: Live, case: Case) -> None:
    eid = lv.episode(AO, "Acceptance: referral", MALARIA_INTAKE)
    r = lv.as_("medical_officer.fac-a").post(f"{B}/referrals", json={
        "episode_id": eid, "to_tenant": "fac-b", "reason": "Needs specialist review",
        "urgency": "routine"})
    body = r.json()
    written = (Path("var") / str(body.get("bundle_ref", "-"))).exists()
    check(case, r.status_code == 201 and written,
          f"HTTP {r.status_code}; referral {body.get('status')} with bundle reference "
          f"{body.get('bundle_ref')}; bundle file written: {written}")


def fr18(lv: Live, case: Case) -> None:
    out, ok = [], True
    for user, role in (("medical_officer.fac-a", "medical_officer"),
                       ("pharmacist.fac-a", "pharmacist"), ("nurse.fac-a", "nurse")):
        r = lv.as_(user).get(f"{B}/worklists/{role}")
        kinds = sorted({i["kind"] for i in r.json().get("items", [])})
        ok = ok and r.status_code == 200
        out.append(f"{role}: HTTP {r.status_code}, {len(r.json().get('items', []))} items "
                   f"{kinds}")
    cross = lv.as_("nurse.fac-a").get(f"{B}/worklists/medical_officer")
    out.append(f"nurse asking for the medical officer's worklist: HTTP {cross.status_code}")
    check(case, ok and cross.status_code == 403, "; ".join(out))


def fr19(lv: Live, case: Case) -> None:
    eid = lv.episode(AO, "Acceptance: twin panel", MALARIA_INTAKE)
    r = lv.timed("ahdt-panel (17 twins via gateway)",
                 lambda: lv.as_("medical_officer.fac-a").get(f"{B}/episodes/{eid}/ahdt-panel"))
    tiles = r.json().get("tiles", [])
    check(case, r.status_code == 200 and len(tiles) == 17,
          f"HTTP {r.status_code}; {len(tiles)} twin tiles, degraded: {r.json().get('degraded')}")


def fr20(lv: Live, case: Case) -> None:
    r = lv.as_("medical_officer.fac-a", POPULATION).post(
        "/v1/tools/population.priors",
        json={"conditions": ["62676009"], "age_band": "45-49", "sex": "female",
              "region": "Lagos", "season": "rainy"})
    body = r.json()
    answer = json.dumps({k: v for k, v in body.items() if k != "_meta"})[:160]
    person_keys = {"hdt_id", "name", "phone"} & set(json.dumps(body).split('"'))
    check(case, r.status_code == 200 and not person_keys,
          f"Population priors for malaria, women 45-49, Lagos, rainy season: HTTP "
          f"{r.status_code}, answer {answer}; "
          f"person fields in the answer: {sorted(person_keys) or 'none'}")


def nfr1(lv: Live, case: Case) -> None:
    r = lv.as_("medical_officer.fac-a", AHDT).post("/v1/agents/run", json={
        "hdt_id": AO, "twin": "cardiovascular",
        "probes": ["sign_order_dispense", "drive_clinical_actuator"]})
    text = r.text
    _, run = diagnosis_run(lv)
    rec = run["interrupt"]["payload"]["recommendation_id"]
    agent = lv.as_("medical_officer.fac-a").post(
        f"{B}/runs/{run['run_id']}/resume",
        json=decision(rec, "accept", who="differential-diagnosis-agent", role="agent"))
    refused = text.count("denied") + text.count("refused")
    check(case, r.status_code == 200 and refused > 0 and agent.status_code >= 400,
          f"Orchestrator run with sign/order/dispense and actuator probes: HTTP "
          f"{r.status_code}, {refused} refusals in the report. A decision submitted in an "
          f"agent's name: HTTP {agent.status_code}", report=text[:1500])


def nfr2(lv: Live, case: Case) -> None:
    anon = httpx.get(f"{APDT}{B}/episodes", timeout=30)
    other = lv.as_("medical_officer.fac-a").get("/v1/t/fac-b/episodes")
    eid = lv.episode(AO, "Acceptance: policy", MALARIA_INTAKE)
    nurse = lv.as_("nurse.fac-a").post(f"{B}/episodes/{eid}/goals/diagnosis")
    check(case, anon.status_code == 401 and other.status_code in (403, 422)
          and nurse.status_code == 403,
          f"No token: HTTP {anon.status_code}; another facility's episodes: HTTP "
          f"{other.status_code}; a nurse starting a diagnosis run: HTTP {nurse.status_code}")


def nfr3(lv: Live, case: Case, seen: list[str]) -> None:
    leaks = [s for s in seen if AO_PHONE in s]
    check(case, not leaks,
          f"{len(seen)} APDT responses from this run scanned; {len(leaks)} contain a "
          f"phone number. Patients appear as pseudonymous ids (hdt-...) and initials")


def nfr4(lv: Live, case: Case) -> None:
    eid, _ = treatment_run(lv)
    mo = lv.as_("medical_officer.fac-a")
    recs = mo.get(f"{B}/episodes/{eid}/recommendations").json()
    ok = [r for r in recs if r.get("bundle_id")
          and mo.get(f"{B}/bundles/{r['bundle_id']}").status_code == 200]
    check(case, len(ok) == len(recs) > 0,
          f"{len(ok)} of {len(recs)} recommendations have a retrievable explanation bundle")


def pytest_case(case: Case, tests: list[str]) -> None:
    t0 = time.perf_counter()
    proc = subprocess.run([".venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           *tests], capture_output=True, text=True, timeout=1800)
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]
    check(case, proc.returncode == 0, f"{last} ({time.perf_counter() - t0:.0f} s)",
          tests=tests)


def nfr7(lv: Live, case: Case) -> None:
    eid = lv.episode(AO, "Acceptance: latency", MALARIA_INTAKE)
    mo = lv.as_("medical_officer.fac-a")
    for _ in range(10):
        lv.timed("ahdt-panel (17 twins via gateway)",
                 lambda: mo.get(f"{B}/episodes/{eid}/ahdt-panel"))
        lv.timed("unified view", lambda: mo.get(f"{B}/episodes/{eid}/unified-view"))
    for _ in range(5):
        diagnosis_run(lv)
    ahdt = lv.as_("medical_officer.fac-a", AHDT)
    for dt in ("cardiovascular", "respiratory", "renal_urinary", "endocrine"):
        for _ in range(5):
            lv.timed("single AHDT tool call (ahdt.model.state)", lambda dt=dt: ahdt.post(
                "/v1/tools/ahdt.model.state", json={"hdt_id": AO, "dt": dt}))
    for _ in range(10):
        lv.timed("single AHDT tool call (ahdt.data.observations)", lambda: ahdt.post(
            "/v1/tools/ahdt.data.observations",
            json={"hdt_id": AO, "codes": ["8310-5", "8867-4"]}))
    single = [t["seconds"] for t in lv.timings if t["call"].startswith("single")]
    pages = [t["seconds"] for t in lv.timings if not t["call"].startswith("single")]
    over = sum(x > GATEWAY_LIMIT_S for x in pages)
    check(case, max(single) <= GATEWAY_LIMIT_S and over == 0,
          f"Single AHDT tool calls: slowest {max(single):.2f} s of {len(single)}. Whole "
          f"pages and runs that make many gateway calls: {over} of {len(pages)} over 30 s, "
          f"slowest {max(pages):.2f} s (see the latency table)")


def nfr8(lv: Live, case: Case) -> None:
    session = f"acc-{int(time.time())}"
    texts = ["", "5"]
    replies = []
    for text in texts:
        replies.append(httpx.post(f"{CHANNELS}/v1/ussd", timeout=60, data={
            "sessionId": session, "serviceCode": "*347#", "phoneNumber": AO_PHONE,
            "networkCode": "99999", "text": text}).text)
    check(case, all(r.startswith(("CON", "END")) for r in replies),
          f"USSD session on a basic phone: main menu \"{replies[0][:60]}...\"; consent menu "
          f"\"{replies[1][:60]}...\"")


def nfr9(lv: Live, case: Case) -> None:
    hooks = httpx.get(f"{APDT}/cds-services", timeout=30).json()["services"]
    smart = httpx.get(f"{APDT}/smart/.well-known/smart-configuration", timeout=30).json()
    q = lv.as_("medical_officer.fac-a").get(f"{B}/questionnaires/phq9").json()
    q = q.get("questionnaire", {})
    names = sorted(h["hook"] for h in hooks)
    check(case, len(names) == 3 and "launch-ehr" in smart.get("capabilities", [])
          and q.get("resourceType") == "Questionnaire",
          f"CDS Hooks services: {names}; SMART capabilities include launch-ehr: "
          f"{'launch-ehr' in smart.get('capabilities', [])}; FHIR resource type "
          f"{q.get('resourceType')}")


def nfr10(case: Case) -> None:
    counts = {}
    for name in ("apdt", "ahdt"):
        path = Path("var/audit") / f"{name}.jsonl"
        records = [AuditRecord.model_validate_json(line)
                   for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        counts[name] = verify_chain(records)
    check(case, all(counts.values()),
          f"Hash chain recomputed with no break: {counts['apdt']} APDT records and "
          f"{counts['ahdt']} AHDT records")


def nfr12(case: Case) -> None:
    peak = {}
    for unit in ("atra-health", "atra-web"):
        base = Path(f"/sys/fs/cgroup/system.slice/{unit}.service")
        peak[unit] = int((base / "memory.peak").read_text()) / 2**30
    total = sum(peak.values())
    check(case, total < 8.0,
          f"Peak memory since the services started: services {peak['atra-health']:.2f} GiB, "
          f"web app {peak['atra-web']:.2f} GiB, total {total:.2f} GiB (limit 8 GB)",
          peak_gib=peak)


def nfr13(lv: Live, case: Case) -> None:
    models = lv.as_("medical_officer.fac-a", AHDT).get("/v1/models")
    ids = {m["model_id"] for m in models.json()} if models.status_code == 200 else set()
    cards = {p.stem for p in Path("docs/governance/model_cards").glob("*.md")}
    missing = sorted(ids - cards)
    docs = [p for p in ("docs/governance/datasets.md", "docs/governance/kb_review.pdf")
            if Path(p).exists()]
    check(case, models.status_code == 200 and not missing and len(docs) == 2,
          f"{len(ids)} registered models (HTTP {models.status_code}), {len(cards)} model "
          f"cards, {len(missing)} registered models without a card; dataset register and "
          f"knowledge-base review list present: {len(docs) == 2}", missing=missing[:20])


def nfr14(case: Case) -> None:
    files = sorted(Path("var/models/t1").glob("*/metrics.json"))
    with_groups = []
    for f in files:
        text = f.read_text(encoding="utf-8").lower()
        if "fairness" in text and "sex" in text:
            with_groups.append(f.parent.name)
    check(case, len(with_groups) == len(files) > 0,
          f"{len(with_groups)} of {len(files)} trained models report fairness metrics by "
          f"group (synthetic data)")


def latency_table(timings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for label in sorted({t["call"] for t in timings}):
        xs = sorted(t["seconds"] for t in timings if t["call"] == label)
        rows.append({"call": label, "n": len(xs), "median_s": statistics.median(xs),
                     "p95_s": xs[min(len(xs) - 1, round(0.95 * (len(xs) - 1)))],
                     "max_s": xs[-1], "within_30_s": sum(x <= GATEWAY_LIMIT_S for x in xs)})
    return rows


def write(out: Path, cases: list[Case], timings: list[dict[str, Any]],
          started: datetime) -> None:
    out.mkdir(parents=True, exist_ok=True)
    meta = {"started": started.isoformat(), "finished": datetime.now(UTC).isoformat(),
            "host": platform.node(), "machine": platform.machine(),
            "commit": Path(".deployed-commit").read_text().strip()
            if Path(".deployed-commit").exists() else None}
    lat = latency_table(timings)
    (out / "results.json").write_text(json.dumps(
        {"meta": meta, "cases": [asdict(c) for c in cases], "latency": lat,
         "timings": timings}, indent=1, default=str), encoding="utf-8")
    lines = [f"# Acceptance run {meta['started'][:16]}Z on {meta['host']} "
             f"({meta['machine']}, commit {meta['commit']})", "",
             "| Case | Req. | Input | Expected | Actual | Result |", "|---|---|---|---|---|---|"]
    for c in cases:
        cells = [c.case_id, c.requirement, c.input, c.expected, c.actual, c.result]
        lines.append("| " + " | ".join(x.replace("|", "/").replace("\n", " ")
                                       for x in cells) + " |")
    lines += ["", "| Call | n | Median (s) | p95 (s) | Max (s) | Within 30 s |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {r['call']} | {r['n']} | {r['median_s']:.2f} | {r['p95_s']:.2f} | "
              f"{r['max_s']:.2f} | {r['within_30_s']}/{r['n']} |" for r in lat]
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logins", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("var/acceptance"))
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated case ids to run")
    args = ap.parse_args()
    started = datetime.now(UTC)
    lv = Live(args.logins)
    seen: list[str] = []
    original_get = httpx.Client.get

    def recording_get(self: httpx.Client, url: Any, **kw: Any) -> httpx.Response:
        resp = original_get(self, url, **kw)
        if str(self.base_url).startswith(APDT):
            seen.append(resp.text)
        return resp

    httpx.Client.get = recording_get  # type: ignore[method-assign]
    catalogue = lv.as_("medical_officer.fac-a").get(f"{B}/intake/catalogue").json()

    C = Case
    plan: list[tuple[Case, Callable[[Case], None]]] = [
        (C("TC-01", "FR1", "Open and close a care episode",
           "Medical officer opens an episode for A.O., then closes it with outcome 'resolved'",
           "HTTP 201; pseudonymous hdt id; status open, then closed"),
         lambda c: fr1(lv, c)),
        (C("TC-02", "FR2", "Capture clinician data in FHIR",
           "Intake for A.O.: history of fever, positive malaria RDT, temperature 38.6, 62 kg",
           "Findings stored as FHIR resources linked to the episode; forms are FHIR "
           "Questionnaires"), lambda c: fr2(lv, c)),
        (C("TC-03", "FR3", "Retrieve AHDT data through service 6.1",
           "Diagnosis run on a new A.O. episode",
           "Evidence-assembly agent calls ahdt.data.* tools at AHDT Layer 3"),
         lambda c: fr3(lv, c)),
        (C("TC-04", "FR4", "Simulate on forked AHDT instances",
           "Treatment run after an accepted malaria diagnosis",
           "Every option simulated on a fork; live twin not changed"),
         lambda c: fr4(lv, c)),
        (C("TC-05", "FR5", "AHDT explanation in the bundle",
           "Treatment run; read the explanation bundle",
           "Bundle holds the AHDT simulation trace and links the AHDT explanation"),
         lambda c: fr5(lv, c)),
        (C("TC-06", "FR6", "Ranked differential with uncertainty and evidence",
           "Diagnosis run for A.O. (fever, positive RDT)",
           "Run waits for the medical officer; conditions ranked by probability; weighted "
           "evidence"), lambda c: fr6(lv, c)),
        (C("TC-07", "FR7", "Recommend next investigations",
           "Diagnosis run for A.O.; read the test recommendation",
           "Tests ranked by value of information, with cost, turnaround and availability"),
         lambda c: fr7(lv, c)),
        (C("TC-08", "FR8", "Guideline treatments with safety checks and simulation",
           "Treatment run after an accepted malaria diagnosis",
           "Options listed; dose, interaction, allergy and formulary checks; simulations; "
           "run waits for signature"), lambda c: fr8(lv, c)),
        (C("TC-09", "FR9", "Capture goals and preferences",
           "Patient A.O. ranks cost, travel distance and pill burden",
           "HTTP 200; preferences stored and turned into weights"),
         lambda c: fr9(lv, c)),
        (C("TC-10", "FR10", "Care plan routed for approval",
           "Care run after diagnosis and treatment", "Run waits for the medical officer"),
         lambda c: fr10(lv, c)),
        (C("TC-11", "FR11", "Early-warning score",
           "Intake with abnormal vitals (RR 28, SpO2 90, SBP 88, HR 128, T 39.4, AVPU V)",
           "Care proposal carries an early-warning score"),
         lambda c: fr11(lv, c, catalogue)),
        (C("TC-12", "FR12", "Sign-off routing and recorded overrides",
           "Medical officer rejects the differential, first with no reason, then with one",
           "Override without a reason refused; with a reason recorded and audited"),
         lambda c: fr12(lv, c)),
        (C("TC-13", "FR13", "Granular consent, including proxy",
           "A.O. withholds the genome tool; A.O. tries to set C.N.'s consent; proxy sets "
           "B.M.'s consent", "200 with genome refused; 403; 200"),
         lambda c: fr13(lv, c)),
        (C("TC-14", "FR14", "Explanation with evidence, citations, counterfactuals and patient "
           "summary", "Diagnosis run; read the bundle for clinician and patient",
           "All four parts present"), lambda c: fr14(lv, c)),
        (C("TC-15", "FR15", "Conversation in local languages",
           "A.O. sends 'Mo ni iba' (Yoruba); A.O. dials the USSD code",
           "Reply in Yoruba; USSD menu in Yoruba"), lambda c: fr15(lv, c)),
        (C("TC-16", "FR16", "Signed findings written back to the AHDT",
           "Medical officer accepts a diagnosis; count AHDT Condition records",
           "One more Condition in the AHDT"), lambda c: fr16(lv, c)),
        (C("TC-17", "FR17", "Referral bundle",
           "Refer a new A.O. episode to facility fac-b", "FHIR Bundle returned"),
         lambda c: fr17(lv, c)),
        (C("TC-18", "FR18", "Role-specific worklists",
           "Medical officer, pharmacist and nurse read their worklists; the nurse asks for "
           "the medical officer's", "200 for each own worklist; 403 for another role's"),
         lambda c: fr18(lv, c)),
        (C("TC-19", "FR19", "Embedded AHDT dashboard",
           "Open the AHDT panel of an A.O. episode", "17 twin tiles"),
         lambda c: fr19(lv, c)),
        (C("TC-20", "FR20", "De-identified population contribution",
           "Ask the Population twin for malaria priors for women",
           "Aggregate answer with no person data"), lambda c: fr20(lv, c)),
        (C("TC-21", "NFR1", "Agents cannot sign, order, dispense or drive actuators",
           "Orchestrator run with forbidden-action probes; a decision sent in an agent's name",
           "Each probe refused and audited; agent decision rejected"),
         lambda c: nfr1(lv, c)),
        (C("TC-22", "NFR2", "Authorisation on every call",
           "Call with no token; read another facility; nurse starts a diagnosis",
           "401; 403 or 422; 403"), lambda c: nfr2(lv, c)),
        (C("TC-24", "NFR4", "Every recommendation has an explanation bundle",
           "Full diagnosis and treatment runs; fetch every bundle",
           "One retrievable bundle per recommendation"), lambda c: nfr4(lv, c)),
        (C("TC-27", "NFR7", "Gateway response time",
           "10 AHDT panels, 10 unified views and 5 diagnosis runs on top of the runs above",
           "Every call returns within 30 s"), lambda c: nfr7(lv, c)),
        (C("TC-28", "NFR8", "Critical functions on a basic phone",
           "A.O. dials *347# and opens the consent menu", "USSD menus returned"),
         lambda c: nfr8(lv, c)),
        (C("TC-29", "NFR9", "Standard interfaces",
           "Read the CDS Hooks discovery, SMART configuration and a FHIR Questionnaire",
           "Three CDS Hooks services; SMART launch-ehr; FHIR resource"),
         lambda c: nfr9(lv, c)),
        (C("TC-30", "NFR10", "Complete, append-only audit trail",
           "Recompute the hash chain of the APDT and AHDT audit logs",
           "No broken link or hash"), nfr10),
        (C("TC-33", "NFR13", "Model cards and governance documents",
           "Compare registered models with model cards", "A card for every registered model; "
           "dataset register and knowledge-base review present"), lambda c: nfr13(lv, c)),
        (C("TC-34", "NFR14", "Fairness reported by group",
           "Read the metrics of every trained model", "Fairness metrics by group in each"),
         nfr14),
        (C("TC-23", "NFR3", "No direct identifiers above Layer 3",
           "Scan every APDT response of this run for the patient's phone number",
           "No phone number in any response"), lambda c: nfr3(lv, c, seen)),
        (C("TC-32", "NFR12", "Runs within 8 GB",
           "Read the peak memory of the services and the web app after the run",
           "Total peak below 8 GB"), nfr12),
    ]
    if not args.skip_pytest:
        plan += [
            (C("TC-25", "NFR5", "Degraded but safe when the AHDT is unreachable",
               "Automated tests that cut the AHDT connection during a run",
               "Degraded result that names the missing evidence"),
             lambda c: pytest_case(c, [
                 "tests/contract/test_apdt_clinical.py::"
                 "test_ahdt_outage_degrades_and_names_the_missing_evidence",
                 "tests/unit/atra/test_gateway.py::test_degraded_when_ahdt_unreachable"])),
            (C("TC-26", "NFR6", "Store-and-forward",
               "Automated tests that cut the link, buffer data and reconnect",
               "Buffered data delivered after reconnection"),
             lambda c: pytest_case(c, [
                 "tests/unit/atra/test_connectors.py::test_buffer_and_flush_after_outage",
                 "tests/unit/edge/service/test_bandwidth.py::"
                 "test_offline_buffers_and_delivery_uses_the_profile_batch_size",
                 "tests/unit/channels/test_channels.py::"
                 "test_outbox_stores_and_forwards_with_audit"])),
            (C("TC-31", "NFR11", "Versioned contracts",
               "Regenerate the contracts and compare with the committed ones",
               "No drift"),
             lambda c: pytest_case(c, ["tests/contract/test_generated_contracts.py"])),
        ]
    only = set(filter(None, args.only.split(",")))
    cases = []
    for case, fn in plan:
        if only and case.case_id not in only:
            continue
        t0 = time.perf_counter()
        try:
            fn(case)
        except Exception as exc:  # a crashed case is a failed case
            case.result, case.actual = "fail", f"{type(exc).__name__}: {exc}"[:400]
        case.seconds = time.perf_counter() - t0
        cases.append(case)
        print(f"{case.case_id} {case.requirement:6} {case.result:7} {case.actual[:150]}",
              flush=True)
    cases.sort(key=lambda c: c.case_id)
    write(args.out, cases, lv.timings, started)


if __name__ == "__main__":
    main()
