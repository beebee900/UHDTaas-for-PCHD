"""Every model that reaches a person has a bound, runnable explainer."""

from __future__ import annotations

import pytest

from ahdt.models.catalogue import default_catalogue
from ahdt.models.ml.inventory import ITEMS
from ahdt.xai.explain import Explainer
from ahdt.xai.registry import T1_KINDS, default_registry, kind_of, person_facing
from atra import contracts as c
from tests.unit.ahdt.xai.examples import subject_for

REGISTRY = default_registry()
T1_ENTRIES = [item.spec.entry(None, c.Validation(dataset="test", metric="m", value=1.0,
                                                 date="2026-10-12")) for item in ITEMS]
T2_ENTRIES = [m.spec.entry(m.paramset) for m in default_catalogue().values()]
ENTRIES = {e.model_id: e for e in [*T1_ENTRIES, *T2_ENTRIES]}


def test_person_facing_rule():
    """Every registered model reaches a person except those of the Population twin."""
    excluded = {m for m, e in ENTRIES.items() if not person_facing(e)}
    assert excluded == {"ahdt.population.cohort", "ahdt.population.population_priors_and_norms"}


def test_every_person_facing_model_is_bound_and_known():
    for model_id, entry in ENTRIES.items():
        if not person_facing(entry):
            assert REGISTRY.bind(entry) == []
            continue
        ids = REGISTRY.bind(entry)
        assert ids, model_id
        for ref in ids:
            spec = REGISTRY.get(ref)
            assert kind_of(entry) in spec.kinds
    assert set(T1_KINDS) | {e.model_id for e in T2_ENTRIES} == {
        m for m, e in ENTRIES.items() if person_facing(e)}


def test_tags_are_kept_and_stamped_entries_carry_ids():
    entry = ENTRIES["ahdt.cardiovascular.blood_pressure_forecasting"]
    stamped = REGISTRY.stamp(entry)
    assert any(x.startswith("shap.window@") for x in stamped.explainers)
    heart = REGISTRY.stamp(ENTRIES["ahdt.cardiovascular.heart_chambers_and_valves"])
    assert any(x.startswith("counterfactual.scenario@") for x in heart.explainers)


def test_library_ids_carry_the_installed_version():
    assert REGISTRY.get("shap.tree").id.startswith("shap.tree@0.")
    assert REGISTRY.get("rules.trace").id == "rules.trace@own"


@pytest.mark.parametrize("model_id", [m for m, e in ENTRIES.items() if person_facing(e)])
def test_default_explainer_runs(model_id):
    explainer = Explainer()
    subject = subject_for(model_id)
    done = explainer.explain(subject, output_id="out-test", audience="clinician")
    assert done.explanation.explainer in REGISTRY.bind(ENTRIES[model_id])
    assert done.explanation.text and done.explanation.uncertainty
    assert done.explanation.model_id == model_id


def test_family_binding_for_language_models_and_external_simulators():
    slm = ENTRIES["ahdt.whole_body.early_warning"].model_copy(
        update={"model_id": "ahdt.cognitive.converse_slm", "family": c.ModelFamily.SLM,
                "tier": c.Tier.T1, "explainers": []})
    assert [REGISTRY.get(i).method for i in REGISTRY.bind(slm)] == [
        "citation.trace", "self_consistency"]
    pbpk = ENTRIES["ahdt.endocrine.hpa_axis"].model_copy(
        update={"model_id": "ahdt.whole_body.whole_body_pbpk",
                "family": c.ModelFamily.PHYSICS_HYBRID})
    assert "salib.sobol" in [REGISTRY.get(i).method for i in REGISTRY.bind(pbpk)]
