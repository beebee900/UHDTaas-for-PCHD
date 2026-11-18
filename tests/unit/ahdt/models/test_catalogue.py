from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from ahdt.models import drivers
from ahdt.models.base import Layer4Base
from ahdt.models.cards import card
from ahdt.models.catalogue import (
    OTHER_WORK_PACKAGES,
    contributors,
    create_person_instances,
    default_catalogue,
    inventory_items,
    register_all,
)
from ahdt.models.coupling import parse, resolve_inputs
from ahdt.models.modes import assimilate, run_truth
from ahdt.models.organs import InstanceStore
from ahdt.models.params import all_param_files, load_params
from ahdt.models.validation import VALIDATORS, run_checks
from ahdt.registry import load_registry
from atra import contracts as c
from atra.backends.memory import FileModelRegistry
from atra.connector_contracts import CONNECTORS
from atra.connectors import DTKind
from tests.unit.ahdt.models.helpers import HDT, observation

# Facet fields that no model writes: the kb holds no testosterone reference range and no
# pinned model describes glucagon secretion.
FIELDS_FROM_OTHER_WPS = {
    ("UBERON:0000991", "hormonal"): {"testosterone"},
    ("UBERON:0001264", "endocrine"): {"glucagon_secretion"},
}


@pytest.fixture(scope="module")
def catalogue() -> Mapping[str, Layer4Base]:
    return default_catalogue()


def test_every_inventory_item_is_built_or_assigned(catalogue):
    for item in inventory_items():
        assert item in catalogue or item in OTHER_WORK_PACKAGES, item
    assert not set(OTHER_WORK_PACKAGES) & set(catalogue)


def test_tiers_and_sources(catalogue):
    for model in catalogue.values():
        assert model.tier in (c.Tier.T2, c.Tier.T3)
        entry = model.spec.entry(model.paramset)
        assert entry.source and entry.twin == model.spec.twin


def test_every_t2_model_has_a_reference_check(catalogue):
    t2 = {m for m, model in catalogue.items() if model.tier is c.Tier.T2}
    assert t2 == set(VALIDATORS)


def test_reference_checks_pass(catalogue):
    failed = {m: (ch.metric, ch.value) for m, ch in run_checks(catalogue).items()
              if not ch.passed}
    assert failed == {}


def test_parameter_files_are_complete():
    for path in all_param_files():
        params = load_params(path)
        for name, p in params.params.items():
            if p.assumption or not p.verified:
                assert p.justification, f"{path.name}: {name}"


def test_facet_fields_are_produced(catalogue):
    found = contributors(catalogue)
    for decl in load_registry().facets:
        produced = set()
        for model in found.get(decl.instance, []):
            produced |= {p.name for p in model.spec.outputs}
            produced |= set(getattr(model, "state_names", ()))
        missing = set(decl.fields) - produced - FIELDS_FROM_OTHER_WPS.get(
            (decl.instance, decl.facet), set())
        assert not missing, (decl.instance, decl.facet, missing)


def test_input_sources_respect_facets_and_connectors(catalogue):
    registry = load_registry()
    connector_fields = {}
    for spec in CONNECTORS:
        for contract in spec.contracts:
            connector_fields.setdefault((spec.name, spec.target), set()).update(
                contract.fields)
    for model in catalogue.values():
        twin = model.spec.twin
        for port in model.spec.inputs:
            source = parse(port)
            if source is None or source.kind in ("input", "field"):
                continue
            if source.kind == "facet":
                decl = registry.facet(source.instance, source.facet)
                assert decl is not None, port
                assert twin in decl.consumers, (model.model_id, port.name)
                assert source.item in decl.fields, (model.model_id, port.name)
            elif source.kind == "connector":
                fields = connector_fields.get((source.target, twin))
                assert fields is not None, (model.model_id, source.target)
                assert source.item in fields, (model.model_id, port.name)
            elif source.kind == "model":
                assert source.target.split(".")[1] == twin.value, (model.model_id, port.name)
                if source.target in catalogue:
                    outputs = {p.name for p in catalogue[source.target].spec.outputs}
                    assert source.item in outputs, (model.model_id, port.name)
                else:
                    assert source.target in OTHER_WORK_PACKAGES


async def test_person_instances_and_facet_reads(catalogue):
    store = InstanceStore()
    created = await create_person_instances(store, HDT, catalogue)
    owned = [a for t in load_registry().twins.values() for a in t.owns_instances]
    assert sorted(r.anatomy for r in created) == sorted(owned)
    aorta = await store.get(HDT, "UBERON:0000947")
    assert aorta.model_id == "ahdt.cardiovascular.aorta"
    heart = await store.get_facet(HDT, "UBERON:0000948", "haemodynamics",
                                  consumer=DTKind.RESPIRATORY)
    assert 4.0 < heart.fields["cardiac_output"] < 6.5
    gut = await store.get_facet(HDT, "UBERON:0000160", "absorption", consumer=DTKind.ENDOCRINE)
    assert gut.fields["absorption_rate"] == 0.0


async def test_resolve_inputs_reads_every_kind_of_source(catalogue):
    store = InstanceStore()
    await create_person_instances(store, HDT, catalogue, anatomies=["UBERON:0000178",
                                                                     "UBERON:0000948"])
    gas = catalogue["ahdt.respiratory.lungs_and_gas_exchange"]
    values = await resolve_inputs(gas, HDT, store=store,
                                  fields={"9279-1": 18.0}.get, supplied={"fio2": 0.3})
    assert values["respiratory_rate"] == 18.0 and values["fio2"] == 0.3
    assert "hb" in values and "cardiac_output" in values
    hpa = catalogue["ahdt.endocrine.hpa_axis"]
    values = await resolve_inputs(hpa, HDT, connectors={
        "NeuroEndocrineConnector": {"stress_drive": 0.4, "circadian_phase": 7.0}})
    assert values == {"stress_drive": 0.4, "clock_h": 7.0}


async def test_registration_records_validation(catalogue):
    registry = FileModelRegistry()
    checks = run_checks({m: catalogue[m] for m in ("ahdt.whole_body.anatomical_avatar",)})
    await register_all(registry, catalogue,
                       validations={m: ch.validation() for m, ch in checks.items()})
    entries = await registry.list(tier="T3")
    assert entries and all(e.validation is None for e in entries)
    avatar = await registry.get("ahdt.whole_body.anatomical_avatar")
    assert avatar.validation is not None and avatar.validation.value == pytest.approx(0.0)
    assert len(await registry.list()) == len(catalogue)


def test_model_card_lists_open_items(catalogue):
    text = card(catalogue["ahdt.cardiovascular.baroreflex_regulation"])
    assert "## Open items for sign-off" in text and "`P_n`" in text
    assert "| Twin | cardiovascular |" in text


async def test_truth_mode_is_reproducible_and_personal(catalogue):
    model = catalogue["ahdt.endocrine.glucose_insulin_and_metabolic_regulation"]
    meal = {"meals": [{"t_s": 0, "carbs_g": 60}]}
    a = await run_truth(model, hdt_id=HDT, horizon_s=4 * 3600, step_s=600, inputs=meal)
    b = await run_truth(model, hdt_id=HDT, horizon_s=4 * 3600, step_s=600, inputs=meal)
    other = await run_truth(model, hdt_id="hdt-ffffffffffff", horizon_s=4 * 3600, step_s=600,
                            inputs=meal)
    assert a.params == b.params and a.trajectory.series == b.trajectory.series
    assert a.params != other.params


async def test_aki_driver_raises_creatinine(catalogue):
    kidney = catalogue["ahdt.renal_urinary.kidney_and_renal_function"]
    aki = drivers.acute_kidney_injury(onset_s=24 * 3600, depth=0.7, recovery_d=10)
    run = await run_truth(kidney, hdt_id=HDT, horizon_s=5 * 86400, step_s=6 * 3600,
                          drivers=[aki], vary=False)
    cr = run.trajectory.series["creatinine"]
    stage = run.trajectory.series["aki_stage"]
    assert cr[3] == pytest.approx(cr[0]) and max(cr) > 2 * cr[0] and max(stage) >= 2


async def test_glycaemic_deterioration_raises_glucose(catalogue):
    model = catalogue["ahdt.endocrine.glucose_insulin_and_metabolic_regulation"]
    meal = {"meals": [{"t_s": 0, "carbs_g": 78}]}
    worse = drivers.glycaemic_deterioration(onset_s=0, sensitivity_decline_per_year=1e4)
    base = await run_truth(model, hdt_id=HDT, horizon_s=3 * 3600, step_s=600, inputs=meal,
                           vary=False)
    run = await run_truth(model, hdt_id=HDT, horizon_s=3 * 3600, step_s=600, inputs=meal,
                          drivers=[worse], vary=False)
    assert max(run.trajectory.series["glucose"]) > max(base.trajectory.series["glucose"])


async def test_malaria_driver_with_treatment(catalogue):
    model = catalogue["ahdt.immune_lymphatic.infection_response"]
    untreated = drivers.malaria(onset_s=0, merozoite_release=0.01)
    treated = drivers.malaria(onset_s=0, merozoite_release=0.01, treatment_after_d=12,
                              antimalarial_kill=4.0)
    a = await run_truth(model, hdt_id=HDT, horizon_s=20 * 86400, step_s=86400,
                        drivers=[untreated], vary=False)
    b = await run_truth(model, hdt_id=HDT, horizon_s=20 * 86400, step_s=86400,
                        drivers=[treated], vary=False)
    assert a.trajectory.series["parasitaemia"][-1] > 1.0
    assert b.trajectory.series["parasitaemia"][-1] < 1e-3


async def test_assimilation_writes_through_the_store(catalogue):
    store = InstanceStore()
    await create_person_instances(store, HDT, catalogue, anatomies=["UBERON:0002048"])
    model = catalogue["ahdt.respiratory.lungs_and_gas_exchange"]
    t0 = datetime(2026, 10, 1, 8, tzinfo=UTC)
    obs = [observation("59408-5", 91.0, "%", t0 + timedelta(minutes=5), DTKind.RESPIRATORY)]
    record = await assimilate(store, model, HDT, "UBERON:0002048", obs)
    assert record.revision == 1 and record.last_assimilated is not None
    assert record.params["shunt_fraction"] > 0.03
    assert record.state["spo2"] == pytest.approx(91.0, abs=0.05)
