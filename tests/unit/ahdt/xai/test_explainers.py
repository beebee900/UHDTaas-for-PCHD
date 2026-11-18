import math

import numpy as np
import pytest

from ahdt.models.catalogue import default_catalogue
from ahdt.xai import attribution as A
from ahdt.xai import deep, graph, mechanistic, semantic, temporal
from ahdt.xai.probes import mechanistic_subject, reference_subject, rule_subject
from ahdt.xai.subjects import TextSubject
from tests.unit.ahdt.xai.examples import subject_for


@pytest.fixture(scope="module")
def tab():
    return subject_for("ahdt.respiratory.exacerbation_risk")


def test_tree_shap_is_additive(tab):
    r = A.shap_tree(tab)
    raw = r.detail["base_log_odds"] + r.detail["sum"]
    assert 1 / (1 + math.exp(-raw)) == pytest.approx(tab.output, abs=1e-6)
    assert {d.feature for d in r.drivers} == set(tab.features)


def test_kernel_shap_lime_ebm_pdp_permutation(tab):
    for fn in (A.shap_kernel, A.lime_tabular, A.partial_dependence, A.permutation_importance):
        r = fn(tab)
        assert len(r.drivers) == len(tab.features) and r.output == pytest.approx(tab.output)
    k = A.shap_kernel(tab)
    assert k.base + sum(d.contribution for d in k.drivers) == pytest.approx(tab.output, abs=0.05)
    e = A.ebm_twin(tab)
    assert 0.0 < e.fidelity <= 1.0 and len(e.drivers) == len(tab.features)


def test_dice_counterfactuals_change_the_decision(tab):
    r = A.dice_counterfactuals(tab)
    assert r.counterfactuals
    now = tab.output >= tab.threshold
    for cf in r.counterfactuals:
        assert (cf.outcome >= tab.threshold) != now
        assert set(cf.changes) <= set(tab.features)


def test_window_shap_and_trajectories():
    s = subject_for("ahdt.endocrine.glucose_forecasting")
    r = temporal.shap_window(s)
    assert r.family == "temporal_attribution" and r.detail["fallback_for"] == "timeshap"
    assert r.base + sum(d.contribution for d in r.drivers) == pytest.approx(s.output, abs=0.3)
    cf = temporal.counterfactual_trajectory(s)
    assert len(cf.counterfactuals) == 2
    assert temporal.prototype_trajectory(s).drivers


def test_sequence_and_online():
    seq = subject_for("ahdt.whole_body.clinical_health_state")
    r = temporal.occlusion_sequence(seq)
    assert len(r.drivers) == seq.obs.size
    online = subject_for("ahdt.behavioural_cognitive.lifestyle")
    assert temporal.baseline_deviation(online).detail["flag"]


def test_signal_explainers():
    s = subject_for("ahdt.cardiovascular.arrhythmia_detection")
    ig = deep.integrated_gradients(s)
    assert len(ig.detail["saliency"]) == len(s.x) and ig.detail["convergence_delta"] < 0.1
    assert len(deep.occlusion(s).drivers) == deep.SEGMENTS
    cam = deep.grad_cam(s)
    assert len(cam.detail["saliency"]) == len(s.x)


def test_tcav_scores_a_concept():
    s = subject_for("ahdt.cardiovascular.arrhythmia_detection")
    t = np.arange(len(s.x)) / s.fs
    fast = np.stack([np.sin(2 * np.pi * (3 + i % 3) * t) for i in range(12)])
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (12, len(s.x)))
    r = deep.tcav(s, {"fast rhythm": fast}, noise, layer="conv.5")
    assert r.drivers and 0.0 <= r.drivers[0].contribution + 0.5 <= 1.0


def test_graph_explainers():
    s = subject_for("ahdt.social.social_network")
    g = graph.gnn_explainer(s)
    assert len(g.drivers) == len(s.features) and g.detail["edges"]
    p = graph.pg_explainer(s)
    assert p.detail["edges"]


@pytest.mark.parametrize("model_id", [
    "ahdt.endocrine.glucose_insulin_and_metabolic_regulation",
    "ahdt.cardiovascular.coronary_cerebral_peripheral_vasculature_and_microcirculation",
    "ahdt.haematological.platelets"])
def test_sensitivity_and_bands(model_id):
    s = mechanistic_subject(default_catalogue()[model_id])
    sob = mechanistic.sobol(s)
    mor = mechanistic.morris(s)
    pce = mechanistic.polynomial_chaos(s)
    loc = mechanistic.local_sensitivity(s)
    assert sob.drivers and mor.drivers and loc.drivers
    assert sob.detail["evaluations"] >= 8 * (len(sob.drivers) + 2)
    u = pce.uncertainty
    assert u["lower"] <= u["mean"] <= u["upper"] and u["std"] >= 0
    top = max(loc.drivers, key=lambda d: abs(d.contribution)).feature
    assert top in {d.feature for d in sob.drivers}


def test_scenario_counterfactual_and_posterior():
    model = default_catalogue()["ahdt.endocrine.glucose_insulin_and_metabolic_regulation"]
    s = mechanistic_subject(model, inputs={"meals": [{"t_s": 0, "carbs_g": 50}]})
    cf = mechanistic.scenario_counterfactual(s, {"k_abs": 0.04})
    assert cf.counterfactuals[0].outcome["change"] != 0
    s.posterior_std.update({"k_abs": 0.001})
    post = mechanistic.posterior_summary(s)
    p = post.uncertainty["parameters"]["k_abs"]
    assert p["lower"] < p["mean"] < p["upper"]


def test_news2_rule_trace_adds_up():
    model = default_catalogue()["ahdt.whole_body.early_warning"]
    r = semantic.rule_trace(rule_subject(model))
    scores = [st["score"] for st in r.detail["steps"] if "score" in st]
    assert sum(scores) == r.output == 7.0
    assert all(st["kb"].startswith("news2") for st in r.detail["steps"])


def test_pharmacogenomics_rule_trace():
    model = default_catalogue()["ahdt.whole_body.pharmacogenomics"]
    r = semantic.rule_trace(rule_subject(model))
    assert any(st.get("phenotype") == "Intermediate Metabolizer" for st in r.detail["steps"])
    assert any(st.get("drug") == "codeine" for st in r.detail["steps"])


def test_reference_trace_has_range_and_status():
    model = default_catalogue()["ahdt.digestive.mouth_oesophagus_rectum_and_gut_epithelium"]
    r = semantic.reference_trace(reference_subject(model))
    assert set(r.detail["variables"]) == set(model.definition.variables)


def test_hermit_justification():
    r = semantic.hermit_justification("UBERON:0001264")
    assert r.family == "ontology_justification"
    assert len(r.detail["axioms"]) == 3


def test_citation_trace_and_self_consistency():
    sources = {"kb-1": "Give artemether and lumefantrine twice daily for three days.",
               "kb-2": "Check blood glucose in a child with fever."}
    good = TextSubject("m", "1", "q", "Give artemether and lumefantrine twice daily for three days."
                       " Check blood glucose.", sources, sample=lambda: "Give artemether and "
                       "lumefantrine twice daily for three days.")
    r = semantic.citation_trace(good)
    assert r.output == 1.0 and {d.feature for d in r.drivers} == {"kb-1", "kb-2"}
    bad = TextSubject("m", "1", "q", "Give 40 tablets of aspirin.", sources)
    assert semantic.citation_trace(bad).output == 0.0
    same = semantic.self_consistency(good)
    odd = TextSubject("m", "1", "q", "Take 3 days.", sources,
                      sample=lambda: "Stop treatment now and wait 9 weeks.")
    assert same.output > semantic.self_consistency(odd).output
