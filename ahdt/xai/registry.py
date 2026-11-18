"""Explainer registry and binding to model families (design 04, 4.6.1).

Every explainer has an id `<method>@<library version or own>` and runs on one or more
kinds of subject. A model is bound to the explainers of its kind: `kind_of` reads the
registry entry (family, tier, id) and `bind` returns the explainer ids, default first.
The ids are stored on the model's registry entry (`explainers`), so an explanation names
the explainer and the model version it explained.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from importlib.metadata import PackageNotFoundError, version

from ahdt.xai import attribution as attr
from ahdt.xai import deep, graph, mechanistic, semantic, temporal
from ahdt.xai.types import ExplainerSpec, MethodFamily, Result, Runner
from atra import contracts as c


def _v(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unavailable"


def _spec(method: str, library: str | None, family: MethodFamily, kinds: Iterable[str],
          run: Runner, note: str = "") -> ExplainerSpec:
    suffix = _v(library) if library else "own"
    return ExplainerSpec(f"{method}@{suffix}", method, family, frozenset(kinds), run,
                         library=library, note=note)


def _build() -> list[ExplainerSpec]:
    return [
        _spec("shap.tree", "shap", "attribution", ["tabular"], attr.shap_tree,
              "TreeExplainer for the LightGBM models"),
        _spec("shap.kernel", "shap", "attribution", ["tabular"], attr.shap_kernel,
              "any scored model, including the Cox model"),
        _spec("lime.tabular", "lime", "attribution", ["tabular"], attr.lime_tabular),
        _spec("ebm.glassbox", "interpret-core", "attribution", ["tabular"], attr.ebm_twin),
        _spec("pdp.average", None, "attribution", ["tabular"], attr.partial_dependence),
        _spec("permutation.importance", None, "attribution", ["tabular"],
              attr.permutation_importance),
        _spec("dice.random", "dice-ml", "counterfactual", ["tabular"],
              attr.dice_counterfactuals),
        _spec("shap.window", "shap", "temporal_attribution", ["forecast"], temporal.shap_window,
              "SHAP on windowed features; the fallback of design 01 for TimeSHAP"),
        _spec("counterfactual.trajectory", None, "counterfactual", ["forecast"],
              temporal.counterfactual_trajectory),
        _spec("prototype.trajectory", None, "temporal_attribution", ["forecast"],
              temporal.prototype_trajectory),
        _spec("occlusion.sequence", None, "temporal_attribution", ["sequence"],
              temporal.occlusion_sequence),
        _spec("baseline.deviation", None, "attribution", ["online"], temporal.baseline_deviation),
        _spec("captum.ig", "captum", "saliency", ["signal"], deep.integrated_gradients),
        _spec("captum.occlusion", "captum", "saliency", ["signal"], deep.occlusion),
        _spec("gradcam.1d", "grad-cam", "saliency", ["signal"], deep.grad_cam),
        _spec("captum.tcav", "captum", "saliency", ["signal"], deep.tcav,
              "needs concept examples from the caller"),
        _spec("gnnexplainer", "torch-geometric", "graph", ["graph"], graph.gnn_explainer),
        _spec("pgexplainer", "torch-geometric", "graph", ["graph"], graph.pg_explainer),
        _spec("salib.sobol", "SALib", "sensitivity", ["mechanistic"], mechanistic.sobol),
        _spec("salib.morris", "SALib", "sensitivity", ["mechanistic"], mechanistic.morris),
        _spec("chaospy.pce", "chaospy", "sensitivity", ["mechanistic"],
              mechanistic.polynomial_chaos),
        _spec("sensitivity.local", None, "sensitivity", ["mechanistic"],
              mechanistic.local_sensitivity),
        _spec("counterfactual.scenario", None, "counterfactual", ["mechanistic"],
              mechanistic.scenario_counterfactual),
        _spec("posterior.summary", None, "sensitivity", ["mechanistic"],
              mechanistic.posterior_summary),
        _spec("rules.trace", None, "rule_trace", ["rules"], semantic.rule_trace),
        _spec("reference.trace", None, "rule_trace", ["reference"], semantic.reference_trace),
        _spec("citation.trace", None, "citation", ["text"], semantic.citation_trace),
        _spec("self_consistency", None, "citation", ["text"], semantic.self_consistency),
    ]


# Default explainers per kind, first entry is used when the caller names none.
DEFAULTS: Mapping[str, tuple[str, ...]] = {
    "tabular": ("shap.tree", "shap.kernel", "lime.tabular", "ebm.glassbox", "pdp.average",
                "permutation.importance", "dice.random"),
    "forecast": ("shap.window", "counterfactual.trajectory",
                 "prototype.trajectory"),
    "sequence": ("occlusion.sequence",),
    "online": ("baseline.deviation",),
    "signal": ("captum.ig", "captum.occlusion", "gradcam.1d", "captum.tcav"),
    "graph": ("gnnexplainer", "pgexplainer"),
    "mechanistic": ("sensitivity.local", "salib.sobol", "salib.morris", "chaospy.pce",
                    "counterfactual.scenario", "posterior.summary"),
    "rules": ("rules.trace",),
    "reference": ("reference.trace",),
    "text": ("citation.trace", "self_consistency"),
}

# Explainers of model tags on a registry entry (`ModelSpec.explainers`).
TAGS: Mapping[str, str] = {
    "sensitivity.local": "sensitivity.local", "counterfactual.scenario":
    "counterfactual.scenario", "rules.trace": "rules.trace", "timeshap": "shap.window",
}

# T1 models by the kind of subject they serve as. Population models describe cohorts, not a
# person, and have no explainer.
T1_KINDS: Mapping[str, str] = {
    "ahdt.cardiovascular.blood_pressure_forecasting": "forecast",
    "ahdt.endocrine.glucose_forecasting": "forecast",
    "ahdt.whole_body.news2_component_forecasting": "forecast",
    "ahdt.cardiovascular.arrhythmia_detection": "signal",
    "ahdt.cardiovascular.arrhythmia_beat_classification": "signal",
    "ahdt.nervous.eeg_analysis_and_sleep_staging": "signal",
    "ahdt.whole_body.clinical_health_state": "sequence",
    "ahdt.behavioural_cognitive.mental_health_trajectory": "sequence",
    "ahdt.behavioural_cognitive.lifestyle": "online",
    "ahdt.social.social_network": "graph",
    "ahdt.behavioural_cognitive.adherence": "tabular",
    "ahdt.respiratory.spo2_desaturation_detection": "tabular",
    "ahdt.respiratory.exacerbation_risk": "tabular",
    "ahdt.haematological.anaemia_and_sickle_cell_crisis_risk": "tabular",
    "ahdt.musculoskeletal.gait_and_fall_risk": "tabular",
    "ahdt.whole_body.deterioration_risk": "tabular",
    "ahdt.behavioural_cognitive.affect_and_stress": "tabular",
}

# Models that describe a cohort or the platform, not one person.
NOT_PERSON_FACING_TWINS = frozenset({"population"})


def person_facing(entry: c.ModelRegistryEntry) -> bool:
    """A model reaches a person unless its twin is the Population twin, whose outputs are
    cohort statistics and priors for the other twins."""
    return str(getattr(entry.twin, "value", entry.twin)) not in NOT_PERSON_FACING_TWINS


def kind_of(entry: c.ModelRegistryEntry) -> str:
    """The subject kind an entry's model is explained as."""
    if entry.model_id in T1_KINDS:
        return T1_KINDS[entry.model_id]
    if entry.family in (c.ModelFamily.SLM, c.ModelFamily.LLM):
        return "text"
    if entry.tier is c.Tier.T3:
        return "reference"
    if entry.family is c.ModelFamily.SEMANTIC:
        return "rules"
    if entry.family in (c.ModelFamily.SIMULATION, c.ModelFamily.PHYSICS_HYBRID):
        return "mechanistic"
    raise LookupError(f"{entry.model_id}: no explainer kind for {entry.family.value} "
                      f"{entry.tier.value}")


class ExplainerRegistry:
    def __init__(self, specs: Iterable[ExplainerSpec] | None = None) -> None:
        self._specs: dict[str, ExplainerSpec] = {}
        self._by_method: dict[str, ExplainerSpec] = {}
        for spec in specs if specs is not None else _build():
            self.register(spec)

    def register(self, spec: ExplainerSpec) -> None:
        self._specs[spec.id] = spec
        self._by_method[spec.method] = spec

    def get(self, ref: str) -> ExplainerSpec:
        """By id (`shap.tree@0.52.0`) or by method name (`shap.tree`)."""
        if ref in self._specs:
            return self._specs[ref]
        if ref in self._by_method:
            return self._by_method[ref]
        raise KeyError(f"unknown explainer {ref}")

    def for_kind(self, kind: str) -> list[ExplainerSpec]:
        return [self._by_method[m] for m in DEFAULTS[kind] if m in self._by_method]

    def bind(self, entry: c.ModelRegistryEntry) -> list[str]:
        """Explainer ids for `entry`: those of its kind, then the ones its tags name."""
        if not person_facing(entry):
            return []
        ids = [s.id for s in self.for_kind(kind_of(entry))]
        for tag in entry.explainers:
            method = TAGS.get(tag.split("@", 1)[0])
            if method is not None and method in self._by_method:
                sid = self._by_method[method].id
                if sid not in ids:
                    ids.append(sid)
        return ids

    def stamp(self, entry: c.ModelRegistryEntry) -> c.ModelRegistryEntry:
        """`entry` with its explainer ids set; register the stamped entry."""
        return entry.model_copy(update={"explainers": self.bind(entry)})

    def applies(self, spec: ExplainerSpec, subject: object) -> bool:
        """Whether `spec` can run on `subject`: tree SHAP needs the tree model."""
        if spec.method == "shap.tree":
            return getattr(subject, "booster", None) is not None
        return spec.method != "captum.tcav"

    def runner(self, ref: str) -> Callable[..., Result]:
        return self.get(ref).run

    def specs(self) -> list[ExplainerSpec]:
        return list(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)


_DEFAULT: ExplainerRegistry | None = None


def default_registry() -> ExplainerRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ExplainerRegistry()
    return _DEFAULT
