"""Registry entries of the APDT Layer 4 models (design 05, 5.5).

Each entry carries the same tags as an AHDT entry (design 03, 3.4) and pins the AHDT models it
uses in `depends_on`. A `model.change_approved` event for a pinned AHDT model triggers
revalidation of the dependents (`dependents_of`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from atra import contracts as c
from atra.backends.base import ModelRegistryBackend

ML, SIM, SEM = c.ModelFamily.ML, c.ModelFamily.SIMULATION, c.ModelFamily.SEMANTIC
T1, T2 = c.Tier.T1, c.Tier.T2
type Port = tuple[str, str, str]

NOISY_OR = ("Pearl J. Probabilistic Reasoning in Intelligent Systems. Morgan Kaufmann; 1988; "
            "pgmpy (Ankan A, Panda A. SciPy 2015); parameters from the ATRA knowledge base")
RULES = "Rules over the ATRA knowledge base (kb/), sources cited per entry"


@dataclass(frozen=True)
class APDTModel:
    model_id: str
    tier: c.Tier
    family: c.ModelFamily
    intended_use: str
    source: str
    inputs: tuple[Port, ...] = ()
    outputs: tuple[tuple[str, str], ...] = ()
    depends_on: tuple[tuple[str, str], ...] = ()
    explainers: tuple[str, ...] = ()
    version: str = "1.0.0"

    def entry(self, validation: c.Validation | None = None) -> c.ModelRegistryEntry:
        return c.ModelRegistryEntry(
            model_id=self.model_id, version=self.version, twin="apdt", family=self.family,
            tier=self.tier, anatomy=None,
            inputs=[c.ModelInput(name=n, unit=u, **{"from": f}) for n, u, f in self.inputs],
            outputs=[c.ModelIO(name=n, unit=u) for n, u in self.outputs],
            validation=validation, intended_use=self.intended_use,
            explainers=list(self.explainers),
            depends_on=[c.ModelRef(model_id=m, version=v) for m, v in self.depends_on],
            source=self.source)


POP = ("ahdt.population.population_priors_and_norms", "1.0.0")
KIDNEY = ("ahdt.renal_urinary.kidney_and_renal_function", "1.0.0")
PBPK = ("ahdt.whole_body.whole_body_pbpk", "1.0.0")
PGX = ("ahdt.whole_body.pharmacogenomics", "1.0.0")
LIVER = ("ahdt.hepatobiliary.liver_drug_clearance_capacity", "1.0.0")
EWS = ("ahdt.whole_body.early_warning", "1.0.0")
MATERNAL = ("ahdt.whole_body.maternal_foetal", "1.0.0")

XGB = ("Chen T, Guestrin C. XGBoost: a scalable tree boosting system. KDD 2016; split-conformal "
       "sets (Lei J et al. JASA 2018;113(523):1094-1111; MAPIE LAC score)")
SYNTH_NOTE = "; trained on the ATRA synthetic cohort (evaluation/models/apdt)"

MODELS: tuple[APDTModel, ...] = (
    APDTModel("apdt.diagnosis.differential_bn", T1, ML,
              "Differential diagnosis: noisy-OR Bayesian network over the kb conditions with "
              "Bayesian model averaging over three structure variants",
              NOISY_OR,
              (("findings", "{finding}", "episode:findings"),
               ("tests", "{test}", "episode:results"),
               ("prior", "1", "connector:PriorConnector")),
              (("condition_probability", "1"),), (POP,),
              ("posterior.summary", "counterfactual.scenario")),
    APDTModel("apdt.diagnosis.neuro_symbolic", T2, SEM,
              "SHACL exclusions and red-flag rules over the patient clinical graph; decides "
              "list membership and never sets a probability",
              "SHACL (W3C 2017) with pySHACL; red flags from kb/conditions.yaml",
              (("candidates", "{condition}", "model:apdt.diagnosis.differential_bn"),),
              (("excluded", "{condition}"), ("must_rule_out", "{condition}")), (),
              ("rules.trace",)),
    APDTModel("apdt.diagnosis.xgboost_comparator", T1, ML,
              "Multi-class comparator for the primary diagnosis with 90 % conformal sets; "
              "a disagreement with the network is a signal for the clinician",
              XGB + SYNTH_NOTE,
              (("findings", "{finding}", "episode:findings"),
               ("tests", "{test}", "episode:results")),
              (("class_probability", "1"), ("conformal_set", "{condition}")), (),
              ("shap.tree",)),
    APDTModel("apdt.diagnosis.diagnostic_uncertainty", T1, ML,
              "Conformal prediction sets, Bayesian model averaging weights and the result "
              "that would change the top diagnosis",
              "Split-conformal prediction; BIC model averaging (Hoeting JA et al. Stat Sci "
              "1999;14(4):382-417)",
              (("differential", "1", "model:apdt.diagnosis.differential_bn"),),
              (("conformal_set", "{condition}"), ("bma_weight", "1")), (),
              ("counterfactual.scenario",)),
    APDTModel("apdt.diagnosis.llm_narrative", T1, c.ModelFamily.LLM,
              "Narrative of the differential and a check for missed candidates; every "
              "sentence and suggestion cites the kb and nothing is scored",
              "Hosted, local or offline model through the ATRA converser chain; kb citations",
              (("facts", "{fact}", "model:apdt.diagnosis.differential_bn"),),
              (("narrative", "{text}"), ("suggestion", "{condition}")), (), ("citation.trace",)),
    APDTModel("apdt.diagnosis.test_selection", T1, ML,
              "Rank available tests by expected entropy reduction of the differential per "
              "naira and day, and name the result that would change the top diagnosis",
              "Value of information over the differential; costs from kb/prices",
              (("differential", "1", "model:apdt.diagnosis.differential_bn"),),
              (("test_score", "1"),), (), ("counterfactual.scenario",)),
    APDTModel("apdt.diagnosis.test_policy_tree", T1, ML,
              "Decision tree distilled from the test-selection policy for offline use in "
              "the CHW app",
              "CART (Breiman L et al. 1984) distilled from the value-of-information policy"
              + SYNTH_NOTE,
              (("findings", "{finding}", "episode:findings"),), (("next_test", "{test}"),),
              ()),
    APDTModel("apdt.diagnosis.result_interpretation", T2, SEM,
              "Flag results against age, sex and pregnancy reference ranges, critical values "
              "and delta checks",
              "kb/reference_ranges.yaml, kb/critical_values.yaml, kb/plausibility.yaml",
              (("results", "{result}", "episode:results"),),
              (("flag", "{flag}"), ("level", "{level}")), (), ("rules.trace",)),
    APDTModel("apdt.treatment.options", T2, SEM,
              "Guideline-concordant treatment options by diagnosis, severity, age, pregnancy, "
              "weight, intake and prior treatment, with the rules that fired",
              RULES, (("diagnosis", "{condition}", "episode:diagnosis"),),
              (("option", "{option}"),), (MATERNAL,), ("rules.trace",)),
    APDTModel("apdt.treatment.dosing", T2, SEM,
              "Weight-band and mg/kg dosing with interaction-linked and pharmacogenomic "
              "adjustments",
              RULES + "; CPIC guidelines via kb/pgx.yaml",
              (("weight", "kg", "field:29463-7"), ("egfr", "mL/min/{1.73_m2}", "model:egfr")),
              (("dose", "mg"),), (KIDNEY, PGX, PBPK), ("rules.trace",)),
    APDTModel("apdt.treatment.safety", T2, SEM,
              "Interaction, contraindication, allergy, duplication and dose-range checks that "
              "produce FHIR DetectedIssue resources",
              "kb/interactions.yaml, kb/doses",
              (("regimen", "{regimen}", "episode:proposal"),), (("detected_issue", "{issue}"),),
              (LIVER, KIDNEY), ("rules.trace",)),
    APDTModel("apdt.treatment.population_pk", T2, SIM,
              "Individual clearance and volume from measured concentrations, given a "
              "published population model in the kb",
              "One-compartment oral model with log-normal random effects; PyMC "
              "(Abril-Pla O et al. PeerJ CS 2023;9:e1516); typical values from kb/popk",
              (("concentrations", "mg/L", "episode:results"), ("dose", "mg", "episode:orders")),
              (("clearance", "L/h"), ("volume", "L")), (PBPK,)),
    APDTModel("apdt.care.early_warning", T2, SEM,
              "NEWS2 for adults and PEWS for children as the baseline of the deterioration "
              "early warning",
              "Royal College of Physicians. NEWS2. 2017; NHS England. National PEWS. 2023",
              (("vitals", "{vitals}", "gateway:ahdt.data.observations"),),
              (("score", "{score}"), ("band", "{band}")), (EWS,), ("rules.trace",)),
    APDTModel("apdt.care.pathways", T2, SEM,
              "PlanDefinition $apply to a draft CarePlan and Tasks, and token-replay "
              "conformance of executed tasks against the BPMN pathway",
              "HL7 FHIR R4 PlanDefinition/$apply; BPMN 2.0 (OMG 2011); pm4py (Berti A et al. "
              "arXiv:1905.06169)",
              (("diagnosis", "{condition}", "episode:diagnosis"),
               ("task_log", "{task}", "episode:tasks")),
              (("care_plan", "{resource}"), ("deviation", "{task}")), ()),
    APDTModel("apdt.agency.preference_mcda", T2, SEM,
              "Criteria weights from swing weighting or paired choices, and additive "
              "multi-criteria scoring of options",
              "Multi-attribute value theory (Keeney RL, Raiffa H. 1976); logistic choice "
              "model for paired choices",
              (("responses", "{answer}", "agency:questionnaire"),),
              (("weights", "1"), ("value", "1")), ()),
    APDTModel("apdt.agency.decision_aid", T2, SEM,
              "Options grid of benefits, harms, uncertainty, cost and burden with sources, "
              "text for audio, and the patient's choice and questions",
              "International Patient Decision Aid Standards options-grid format; kb sources",
              (("options", "{option}", "model:apdt.treatment.options"),),
              (("grid", "{grid}"),), ()),
    APDTModel("apdt.agency.capacity_proxy", T2, SEM,
              "Who consents and decides for the patient (self, guardian, registered proxy) "
              "from age, AVPU and capacity assessment, with the rule audited",
              "Rules in kb/capacity.yaml; legal basis to be confirmed by the clinical lead",
              (("age", "a", "demographics"), ("avpu", "{AVPU}", "field:avpu")),
              (("actor", "{actor}"),), (), ("rules.trace",)),
    APDTModel("apdt.agency.literacy_hooks", T2, SEM,
              "Literacy level from a three-item screening score and a text-adaptation hook "
              "that the language converser plugs into",
              "Hooks over the ATRA converser; screening mapping is an assumption",
              (("screening", "{score}", "agency:questionnaire"),), (("level", "{level}"),),
              ()),
)

BY_ID: Mapping[str, APDTModel] = {m.model_id: m for m in MODELS}


def dependents_of(ahdt_model_id: str, models: Iterable[APDTModel] = MODELS) -> list[str]:
    """The APDT models that must be revalidated when an AHDT model changes."""
    return [m.model_id for m in models if any(d == ahdt_model_id for d, _ in m.depends_on)]


async def register_all(backend: ModelRegistryBackend,
                       validations: Mapping[str, c.Validation] | None = None,
                       metrics: Mapping[str, Mapping[str, float]] | None = None
                       ) -> list[c.ModelRegistryEntry]:
    entries = []
    for m in MODELS:
        entry = m.entry((validations or {}).get(m.model_id))
        await backend.register(entry, metrics=(metrics or {}).get(m.model_id))
        entries.append(entry)
    return entries
