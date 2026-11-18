"""The unified patient view, the AHDT panel and the role worklists (design 05, 5.8.1)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from apdt.models.context import Observations, Patient, kb
from apdt.services import clinical_record
from apdt.services.ahdt_access import AHDTAccess, Missing
from apdt.services.inputs import KB_SYSTEM, MEASURE_SYSTEM, to_resources
from apdt.services.memory_store import InMemoryEpisodeStore
from atra import contracts as c
from atra.connectors import DTKind
from atra.gateway import CallContext
from atra.personas import BY_HDT, PERSONAS

WORKLIST_KINDS: Mapping[c.Role, Mapping[str, str]] = {
    c.Role.MEDICAL_OFFICER: {"diagnosis": "Review diagnosis", "test": "Order tests",
                             "care": "Approve care plan"},
    c.Role.PHARMACIST: {"treatment": "Verify prescription"},
    c.Role.NURSE: {"care": "Care plan"}}
RECORD_LABELS = {"diagnosis": "Clinician's diagnosis", "dispense": "Dispensed",
                 "administration": "Given by the nurse"}
# Work that follows a decision: the pharmacist dispenses a verified prescription, and the nurse
# gives an approved care plan or treatment. The item stays until its record entry exists.
FOLLOW_UP: Mapping[c.Role, tuple[str, frozenset[str], str]] = {
    c.Role.PHARMACIST: ("dispense", frozenset({"treatment"}), "Dispense"),
    c.Role.NURSE: ("administration", frozenset({"care", "treatment"}), "Give care")}
APPROVED_CARE = frozenset({"accepted", "edited"})
TRIAGE_ROLES = frozenset({c.Role.MEDICAL_OFFICER})
BLOCKING_PRIORITY = 1
DEFAULT_PRIORITY = 3
# AHDT state calls of one panel that run at the same time.
PANEL_CONCURRENCY = 4


def _name(entry_id: str) -> str:
    return str(kb().entry(entry_id).content().get("name", entry_id))


def apdt_items(ep: c.Episode, store: InMemoryEpisodeStore) -> list[c.SourcedItem]:
    items: list[c.SourcedItem] = []
    for r in store.resources[ep.episode_id]:
        coding = (r.get("code", {}).get("coding") or [{}])[0]
        system, code = coding.get("system"), coding.get("code", "")
        if r["resourceType"] == "Condition" and system == KB_SYSTEM:
            items.append(c.SourcedItem(source="apdt", kind="condition", label=_name(code),
                                       value="recorded", time=ep.opened_at, ref=code))
        elif r["resourceType"] == "MedicationRequest":
            drug = r.get("medicationCodeableConcept", {}).get("text", "")
            items.append(c.SourcedItem(source="apdt", kind="medication", label=drug,
                                       value="active", time=ep.opened_at))
        elif r["resourceType"] == "Observation" and system == KB_SYSTEM:
            is_test = code.startswith("test.")
            positive = r.get("valueBoolean")
            state = (("positive" if positive else "negative") if is_test
                     else ("present" if positive else "absent"))
            items.append(c.SourcedItem(source="apdt", kind="test" if is_test else "finding",
                                       label=_name(code), value=state, time=ep.opened_at,
                                       ref=code))
        elif r["resourceType"] == "Observation" and system == MEASURE_SYSTEM:
            value = r.get("valueQuantity", {}).get("value", r.get("valueString"))
            items.append(c.SourcedItem(source="apdt", kind="measurement",
                                       label=code.replace("_", " ").capitalize(), value=value,
                                       time=ep.opened_at, ref=code))
    for entry in clinical_record.entries(store.resources[ep.episode_id]):
        items.append(c.SourcedItem(source="apdt", kind=entry.kind,
                                   label=f"{RECORD_LABELS[entry.kind]}: {entry.title}",
                                   value=", ".join(entry.details[:2]), time=entry.recorded_at,
                                   ref=entry.entry_id))
    for rec in store.recommendations[ep.episode_id]:
        bundle = store.bundles.get(rec.bundle_id or "")
        text = bundle.recommendation.text if bundle else rec.kind
        items.append(c.SourcedItem(source="apdt", kind="recommendation",
                                   label=f"{rec.kind.capitalize()}: {text}", value=rec.status,
                                   time=ep.opened_at, ref=rec.recommendation_id))
    return items


async def unified_view(ep: c.Episode, store: InMemoryEpisodeStore, ahdt: AHDTAccess,
                       ctx: CallContext) -> c.UnifiedView:
    items = apdt_items(ep, store)
    missing: list[str] = []
    for fetch in (ahdt.vitals, ahdt.medications):
        try:
            result = await fetch(ep.tenant_id, ctx)
        except Missing as exc:
            missing.append(str(exc))
            continue
        items += list(result.values()) if isinstance(result, dict) else result
    return c.UnifiedView(episode_id=ep.episode_id, items=items, degraded=bool(missing),
                         missing_evidence=missing)


async def ahdt_panel(ep: c.Episode, ahdt: AHDTAccess, ctx: CallContext) -> c.AHDTPanel:
    members = [k for k in DTKind if k.is_ahdt_member]
    try:
        vitals = await ahdt.vitals(ep.tenant_id, ctx)
    except Missing as exc:
        tiles = [c.TwinTile(dt=k, status="unavailable", headline=exc.reason) for k in members]
        return c.AHDTPanel(hdt_id=ep.hdt_id, tiles=tiles, vitals={}, degraded=True)
    limit = asyncio.Semaphore(PANEL_CONCURRENCY)

    async def limited[T](call: Awaitable[T]) -> T:
        async with limit:
            return await call

    tiles, forecast = await asyncio.gather(
        asyncio.gather(*(limited(ahdt.tile(ep.tenant_id, k, ctx)) for k in members)),
        limited(ahdt.forecast(ep.tenant_id, ctx)))
    return c.AHDTPanel(hdt_id=ep.hdt_id, tiles=tiles, vitals=vitals, forecast=forecast,
                       degraded=any(t.status == "unavailable" for t in tiles))


def worklist(role: c.Role, tenant_id: str, store: InMemoryEpisodeStore) -> c.Worklist:
    kinds = WORKLIST_KINDS.get(role, {})
    items: list[c.WorklistItem] = []
    for ep in store.open_episodes(tenant_id):
        persona = BY_HDT.get(ep.hdt_id)
        who = persona.initials if persona else ep.hdt_id
        recs = store.recommendations[ep.episode_id]
        if role in TRIAGE_ROLES and not recs:
            items.append(c.WorklistItem(item_id=f"wl-{ep.episode_id}-triage", kind="triage",
                                        episode_id=ep.episode_id, hdt_id=ep.hdt_id,
                                        title=f"New episode for {who}: {ep.reason}"))
        for rec in recs:
            if rec.status != "proposed" or rec.kind not in kinds:
                continue
            bundle = store.bundles.get(rec.bundle_id or "")
            text = f": {bundle.recommendation.text}" if bundle else ""
            blocked = bool(rec.payload.get("blocks_signing"))
            items.append(c.WorklistItem(
                item_id=f"wl-{rec.recommendation_id}", kind=f"review_{rec.kind}",
                episode_id=ep.episode_id, hdt_id=ep.hdt_id,
                title=f"{kinds[rec.kind]} for {who}{text}",
                priority=BLOCKING_PRIORITY if blocked else DEFAULT_PRIORITY))
        if role in FOLLOW_UP:
            entry_kind, rec_kinds, label = FOLLOW_UP[role]
            entered = any(e.kind == entry_kind
                          for e in clinical_record.entries(store.resources[ep.episode_id]))
            verified = {d.recommendation_id for d in store.decisions.get(ep.episode_id, [])
                        if d.decision == "verify"}
            decided = [r for r in recs if r.kind in rec_kinds and (
                r.recommendation_id in verified if r.kind == "treatment"
                else r.status in APPROVED_CARE)]
            if decided and not entered:
                items.append(c.WorklistItem(
                    item_id=f"wl-{ep.episode_id}-{entry_kind}", kind=entry_kind,
                    episode_id=ep.episode_id, hdt_id=ep.hdt_id,
                    title=f"{label} for {who}", priority=DEFAULT_PRIORITY))
    items.sort(key=lambda i: (i.priority, i.item_id))
    return c.Worklist(role=role, tenant_id=tenant_id, items=items)



def patient_entry(hdt_id: str) -> c.PatientEntry | None:
    p = BY_HDT.get(hdt_id)
    if p is None:
        return None
    return c.PatientEntry(hdt_id=p.hdt_id, initials=p.initials, sex=p.sex,
                          age_years=p.age_years, language=p.language, tenant_id=p.tenant_id)


def facility_patients(tenant_id: str) -> list[c.PatientEntry]:
    return [e for p in PERSONAS if p.tenant_id == tenant_id
            if (e := patient_entry(p.hdt_id)) is not None]


@cache
def intake_catalogue(kb_dir: Path) -> c.IntakeCatalogue:
    entries = yaml.load((kb_dir / "findings.yaml").read_text(), Loader=yaml.CSafeLoader)
    findings = [c.IntakeFinding(id=e["id"], name=e["name"], capture=e["capture"])
                for e in entries if e["capture"] != "measurement"]
    tests = yaml.load((kb_dir / "tests.yaml").read_text(), Loader=yaml.CSafeLoader)
    fields = sorted({e["derive"]["field"] for e in entries if e.get("derive")})
    measurements = [c.IntakeMeasurement(field=f, unit=str(kb().entry(f"range.{f}").content()
                                                          .get("unit", "")))
                    for f in fields]
    return c.IntakeCatalogue(findings=findings,
                             tests=[c.IntakeTest(id=t["id"], name=t["name"]) for t in tests],
                             measurements=measurements)


def intake_resources(hdt_id: str, tenant_id: str, body: c.IntakeRecord,
                     catalogue: c.IntakeCatalogue) -> list[dict[str, Any]]:
    """The FHIR resources of an intake record, built as the demo seed builds them."""
    persona = BY_HDT.get(hdt_id)
    if persona is None:
        raise ValueError(f"no directory entry for {hdt_id}")
    unknown = ((set(body.findings) - {f.id for f in catalogue.findings})
               | (set(body.tests) - {t.id for t in catalogue.tests})
               | (set(body.measurements) - {m.field for m in catalogue.measurements}))
    if unknown:
        raise ValueError("unknown intake items: " + ", ".join(sorted(unknown)))
    patient = Patient(age_years=persona.age_years, sex=persona.sex, tenant_id=tenant_id,
                      weight_kg=body.weight_kg, pregnancy=body.pregnancy)
    obs = Observations(findings=dict(body.findings), tests=dict(body.tests),
                       measurements=dict(body.measurements), avpu=body.avpu)
    return to_resources(patient, obs)
