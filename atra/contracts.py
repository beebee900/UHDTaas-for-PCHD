"""Frozen contracts (design 03) as Python types.

The JSON Schemas in `contracts/schemas/` are generated from these models by
`python -m atra.schemagen`; a contract test fails when the two drift apart.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from atra.connectors import DTKind
from atra.gateway import AHDT_TOOLS, DEFAULT_ROLE_TOOLS, CallContext, Role

__all__ = [
    "APDT_TOOL_ARGS",
    "APDT_TOOL_RESPONSES",
    "ATRA_ROLE_TOOLS",
    "CONSENT_CATEGORIES",
    "POPULATION_TOOL_ARGS",
    "POPULATION_TOOL_RESPONSES",
    "PURPOSE_HL7",
    "TOOL_ARGS",
    "TOOL_RESPONSES",
    "AHDTExplanation",
    "Agent",
    "AgentResult",
    "AuditRecord",
    "AutonomyLevel",
    "ClinicalDecision",
    "Code",
    "DTKind",
    "Episode",
    "EventEnvelope",
    "ExplanationBundle",
    "FacetView",
    "FieldDefinition",
    "Goal",
    "GoalCheck",
    "InstanceRecord",
    "Interrupt",
    "Layer4Model",
    "ModelFamily",
    "ModelOutput",
    "ModelRegistryEntry",
    "ObservationRecord",
    "Orchestrator",
    "PurposeOfUse",
    "Quality",
    "Recommendation",
    "Role",
    "Scenario",
    "StandingGoal",
    "Tier",
    "ToolMeta",
    "Trajectory",
    "TwinDefinition",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# 3.1 Enumerations
# ---------------------------------------------------------------------------

class PurposeOfUse(str, enum.Enum):
    CARE = "care"
    EMERGENCY = "emergency"
    RESEARCH = "research"
    PUBLIC_HEALTH = "public_health"
    OPERATIONS = "operations"
    SELF_MANAGEMENT = "self_management"


PURPOSE_HL7: Mapping[PurposeOfUse, str] = {
    PurposeOfUse.CARE: "TREAT",
    PurposeOfUse.EMERGENCY: "ETREAT",
    PurposeOfUse.RESEARCH: "HRESCH",
    PurposeOfUse.PUBLIC_HEALTH: "PUBHLTH",
    PurposeOfUse.OPERATIONS: "HOPERAT",
    PurposeOfUse.SELF_MANAGEMENT: "PATRQT",
}


class AutonomyLevel(str, enum.Enum):
    INFORM = "inform"
    RECOMMEND = "recommend"
    PREPARE_FOR_SIGNATURE = "prepare_for_signature"
    ACT_WITH_APPROVAL = "act_with_approval"
    ACT = "act"
    NEVER = "never"


class Tier(str, enum.Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class ModelFamily(str, enum.Enum):
    ML = "ml"
    SLM = "slm"
    LLM = "llm"
    SIMULATION = "simulation"
    SEMANTIC = "semantic"
    PHYSICS_HYBRID = "physics_hybrid"


class Quality(str, enum.Enum):
    OK = "ok"
    SUSPECT = "suspect"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# 3.6.3 Role-to-tool policy
# ---------------------------------------------------------------------------

_TOOLS = frozenset(t.name for t in AHDT_TOOLS)
_DATA_TOOLS = frozenset(t.name for t in AHDT_TOOLS if t.sublayer == "6.1")
_COGNITIVE_TOOLS = frozenset(t.name for t in AHDT_TOOLS if t.sublayer == "6.4")


def _with(role: Role, *extra: str) -> frozenset[str]:
    return DEFAULT_ROLE_TOOLS[role] | frozenset(extra)


ATRA_ROLE_TOOLS: Mapping[Role, frozenset[str]] = {
    Role.MEDICAL_OFFICER: _TOOLS - {"ahdt.model.calibrate", "ahdt.data.cohort_extract"},
    Role.RADIOLOGIST: _with(Role.RADIOLOGIST, "ahdt.data.timeseries", "ahdt.data.documents",
                            "ahdt.cognitive.perceive"),
    Role.PHARMACIST: _with(Role.PHARMACIST, "ahdt.data.documents", "ahdt.model.facet",
                           "ahdt.model.cosimulate", "ahdt.xai.causal_graph"),
    Role.NURSE: _with(Role.NURSE, "ahdt.data.timeseries", "ahdt.cognitive.request_data"),
    Role.LAB_SCIENTIST: _with(Role.LAB_SCIENTIST, "ahdt.data.timeseries"),
    Role.PATIENT: _with(Role.PATIENT, "ahdt.cognitive.perceive", "ahdt.cognitive.request_data"),
    Role.PROXY: _with(Role.PROXY, "ahdt.cognitive.perceive", "ahdt.cognitive.request_data"),
    Role.COMMUNITY_HEALTH_WORKER: frozenset({
        "ahdt.data.observations", "ahdt.data.medications", "ahdt.model.state",
        "ahdt.xai.explain", "ahdt.cognitive.converse", "ahdt.cognitive.request_data"}),
    Role.THERAPIST: frozenset({
        "ahdt.data.observations", "ahdt.data.timeseries", "ahdt.model.state",
        "ahdt.model.forecast", "ahdt.xai.explain", "ahdt.cognitive.converse"}),
    Role.CARER: frozenset({
        "ahdt.data.observations", "ahdt.model.forecast", "ahdt.xai.explain",
        "ahdt.cognitive.converse"}),
    Role.PERSON: (_DATA_TOOLS - {"ahdt.data.cohort_extract"}) | _COGNITIVE_TOOLS | frozenset({
        "ahdt.model.state", "ahdt.model.forecast", "ahdt.model.simulate", "ahdt.xai.explain"}),
    Role.RESEARCHER: frozenset({"ahdt.data.cohort_extract"}),
    Role.PUBLIC_HEALTH_OFFICIAL: frozenset({"ahdt.data.cohort_extract"}),
    Role.CLINICAL_SAFETY_OFFICER: frozenset({"ahdt.model.calibrate", "ahdt.model.state"}),
    Role.ADMINISTRATOR: frozenset({"ahdt.model.calibrate", "ahdt.model.state"}),
}

# 3.13: consent categories shown to patients, mapped to the tools they withhold.
CONSENT_CATEGORIES: Mapping[str, frozenset[str]] = {
    "vital_signs_and_device_data": frozenset({"ahdt.data.observations", "ahdt.data.timeseries"}),
    "laboratory_and_imaging": frozenset({"ahdt.data.imaging"}),
    "medicines": frozenset({"ahdt.data.medications"}),
    "genome": frozenset({"ahdt.data.genome"}),
    "knowledge_graph_and_notes": frozenset({"ahdt.data.graph_query", "ahdt.data.documents",
                                            "ahdt.data.knowledge"}),
    "body_models_and_simulation": frozenset(t for t in _TOOLS if t.startswith("ahdt.model.")),
    "explanations": frozenset(t for t in _TOOLS if t.startswith("ahdt.xai.")),
    "conversation_and_speech": _COGNITIVE_TOOLS,
}


# ---------------------------------------------------------------------------
# 3.2 Twin definition
# ---------------------------------------------------------------------------

class FieldDefinition(_Model):
    name: str
    loinc: str | None = None
    snomed: str | None = None
    mdc: str | None = None
    ucum: str
    ref: str | None = Field(None, description="kb/reference_ranges.yaml entry id")
    sample_period_s: float | None = None
    source: list[Literal["wearable", "monitor", "device", "manual", "self_report", "lab",
                         "imaging", "derived", "import"]]


class GoalCheck(_Model):
    kind: Literal["freshness", "threshold", "model_flag", "composite", "human_decision"]
    params: dict[str, Any] = Field(default_factory=dict)


class StandingGoal(_Model):
    id: str
    text: str
    check: GoalCheck
    priority: int = Field(3, ge=1, le=5)


class FacetRead(_Model):
    instance: str
    facet: str


class TwinDefinition(_Model):
    kind: DTKind
    name: str
    referent: str
    fields: list[FieldDefinition]
    models: list[str]
    owns_instances: list[str]
    reads_facets: list[FacetRead] = Field(default_factory=list)
    standing_goals: list[StandingGoal]
    connectors_out: list[str] = Field(default_factory=list)
    connectors_in: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.3 Observation record
# ---------------------------------------------------------------------------

class Code(_Model):
    system: str
    code: str
    display: str | None = None


class Waveform(_Model):
    array: list[float]
    period_ms: float


class ObservationRecord(_Model):
    record_id: str
    hdt_id: str
    dt: DTKind
    code: Code
    alt_codes: list[Code] = Field(default_factory=list)
    value: float | int | bool | str | Waveform
    unit: str
    effective_time: datetime
    sim_time: float | None = None
    device_id: str | None = None
    source: Literal["device", "manual", "self_report", "derived", "import"]
    quality: Quality = Quality.OK
    consent_tag: str
    provenance_id: str
    version: int = Field(1, ge=1)


# ---------------------------------------------------------------------------
# 3.4 Model registry entry and Layer 4 protocol
# ---------------------------------------------------------------------------

class ModelInput(_Model):
    name: str
    unit: str
    from_: str = Field(alias="from")


class ModelIO(_Model):
    name: str
    unit: str


class Validation(_Model):
    dataset: str
    metric: str
    value: float
    date: str


class ModelRef(_Model):
    model_id: str
    version: str


class ModelRegistryEntry(_Model):
    model_id: str
    version: str
    twin: DTKind | Literal["apdt"]
    family: ModelFamily
    tier: Tier
    anatomy: str | None
    inputs: list[ModelInput]
    outputs: list[ModelIO]
    validity: dict[str, Any] = Field(default_factory=dict)
    validation: Validation | None = None
    intended_use: str
    regulatory_status: Literal["research", "investigational", "samd_candidate"] = "research"
    explainers: list[str] = Field(default_factory=list)
    depends_on: list[ModelRef] = Field(default_factory=list)
    source: str


class Interval(_Model):
    lower: float
    upper: float
    level: float


class StdDev(_Model):
    std: float


class ConformalSet(_Model):
    set_: list[str] = Field(alias="set")


type Uncertainty = Interval | StdDev | ConformalSet


class ModelOutput(_Model):
    output_id: str
    model_id: str
    version: str
    hdt_id: str
    values: dict[str, float | str | list[float] | list[str]]
    uncertainty: dict[str, Uncertainty] = Field(default_factory=dict)
    inputs_ref: str
    created_at: datetime


class TrajectoryEvent(_Model):
    t: float
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class Trajectory(_Model):
    output_id: str
    model_id: str
    version: str
    t: list[float]
    series: dict[str, list[float]]
    units: dict[str, str]
    events: list[TrajectoryEvent] = Field(default_factory=list)
    fork_id: str | None = None


class ScenarioDrug(_Model):
    atc: str
    dose_mg: float
    route: str
    schedule_h: list[float]


class Scenario(_Model):
    kind: Literal["drug", "activity", "diet", "environment", "intervention"]
    drug: ScenarioDrug | None = None
    activity: dict[str, Any] | None = None
    diet: dict[str, Any] | None = None
    environment: dict[str, Any] | None = None
    intervention: dict[str, Any] | None = None
    dts: list[DTKind] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.5 Organ instance store
# ---------------------------------------------------------------------------

class InstanceRecord(_Model):
    instance_id: str
    anatomy: str
    model_id: str
    version: str
    owner_dt: DTKind
    params: dict[str, Any]
    state: dict[str, Any]
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    last_assimilated: datetime | None = None
    revision: int = Field(0, ge=0)


class FacetView(_Model):
    instance_id: str
    anatomy: str
    facet: str
    fields: dict[str, Any]
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    revision: int
    fork_id: str | None = None


@runtime_checkable
class Layer4Model(Protocol):
    model_id: str
    version: str
    family: ModelFamily
    tier: Tier

    async def predict(self, inputs: Mapping[str, Any],
                      state: InstanceRecord | None) -> ModelOutput: ...

    async def simulate(self, state: InstanceRecord, scenario: Scenario, horizon_s: float,
                       step_s: float) -> Trajectory: ...

    async def calibrate(self, state: InstanceRecord,
                        obs: Sequence[ObservationRecord]) -> InstanceRecord: ...


# ---------------------------------------------------------------------------
# 3.6 Tool response metadata
# ---------------------------------------------------------------------------

class ToolMeta(_Model):
    model_config = ConfigDict(extra="allow")

    ahdt_version: str
    models: list[ModelRef] = Field(default_factory=list)
    explainers: list[str] | None = None
    forked: bool | None = None
    fork_id: str | None = None
    output_id: str | None = None
    as_of: datetime | None = None


# ---------------------------------------------------------------------------
# 3.7 APDT API objects
# ---------------------------------------------------------------------------

class CareTeamMember(_Model):
    id: str
    role: Role


class Episode(_Model):
    episode_id: str
    tenant_id: str
    hdt_id: str
    status: Literal["open", "closed"]
    opened_at: datetime
    closed_at: datetime | None = None
    reason: str
    goal_text: str | None = None
    responsible_clinician: str
    care_team: list[CareTeamMember] = Field(default_factory=list)


class Interrupt(_Model):
    kind: Literal["accept_diagnosis", "verify_prescription", "sign_prescription",
                  "approve_care_plan", "patient_consent_to_treatment"]
    payload: dict[str, Any]
    allowed_decisions: list[str]
    required_role: Role


# ---------------------------------------------------------------------------
# 3.8 Events
# ---------------------------------------------------------------------------

EVENT_TYPES = frozenset({
    "observation.ingested", "state.updated", "anomaly.detected", "forecast.created",
    "deterioration.detected", "alert.raised", "alert.acknowledged", "alert.escalated",
    "recommendation.proposed", "decision.recorded", "consent.changed", "episode.opened",
    "episode.closed", "task.created", "task.completed", "message.sent", "message.received",
    "connector.delivered", "connector.dead_lettered", "model.drift_detected",
    "model.change_requested", "model.change_approved", "agent.paused", "agent.resumed",
})


class EventEnvelope(_Model):
    event_id: str
    event_type: Annotated[str, Field(pattern=r"^[a-z_]+\.[a-z_]+$")]
    source: str
    hdt_id: str | None = None
    tenant_id: str | None = None
    episode_id: str | None = None
    wall_time: datetime
    sim_time: float | None = None
    trace_id: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# 3.9 Explanations
# ---------------------------------------------------------------------------

class Driver(_Model):
    feature: str
    value: Any = None
    contribution: float
    direction: Literal["up", "down"]


class Counterfactual(_Model):
    changes: dict[str, Any]
    outcome: Any


class Artefact(_Model):
    kind: Literal["heatmap", "plot", "subgraph"]
    ref: str


class ExplanationQuality(_Model):
    faithfulness: float | None = None
    robustness: float | None = None
    complexity: float | None = None


class AHDTExplanation(_Model):
    explanation_id: str
    output_id: str
    model_id: str
    version: str
    explainer: str
    method_family: Literal["attribution", "saliency", "counterfactual", "sensitivity",
                           "rule_trace", "ontology_justification", "citation",
                           "temporal_attribution", "graph"]
    drivers: list[Driver] = Field(default_factory=list)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    counterfactuals: list[Counterfactual] | None = None
    artefacts: list[Artefact] | None = None
    text: str
    quality: ExplanationQuality | None = None
    causal_graph_ref: str | None = None


class BundleRecommendation(_Model):
    text: str
    code: Code | None = None
    confidence: float = Field(ge=0, le=1)
    interval: Interval | None = None
    conformal_set: list[str] | None = None


class EvidenceItem(_Model):
    source: Literal["apdt", "ahdt"]
    item: str
    value: Any = None
    weight: float
    ahdt_explanation_id: str | None = None


class Citation(_Model):
    kb_entry_id: str
    source_title: str
    section: str
    url: str | None = None


class BundleCounterfactual(_Model):
    change: str
    new_top: str
    delta: float


class Sensitivity(_Model):
    param: str
    S1: float
    ST: float


class SimulationTrace(_Model):
    output_id: str
    fork_id: str
    summary: str
    assumptions: list[str]
    sensitivity: list[Sensitivity] = Field(default_factory=list)


class Alternative(_Model):
    text: str
    score: float
    why_lower: str


class PatientSummary(_Model):
    language: Literal["en", "yo", "ha", "ig", "pcm"]
    text: str
    audio_ref: str | None = None


class ExplanationBundle(_Model):
    bundle_id: str
    recommendation_id: str
    recommendation: BundleRecommendation
    evidence_for: list[EvidenceItem]
    evidence_against: list[EvidenceItem]
    citations: list[Citation]
    counterfactuals: list[BundleCounterfactual]
    simulation_trace: SimulationTrace | None = None
    alternatives: list[Alternative]
    patient_summary: PatientSummary
    audience_views: dict[Literal["medical_officer", "pharmacist", "nurse", "radiologist",
                                 "patient"], dict[str, Any]]
    created_at: datetime
    model_versions: list[ModelRef]

    def missing_parts(self) -> list[str]:
        """Names of the seven [APDT] L5 parts that are empty (NFR4 completeness)."""
        parts = {"recommendation": True,
                 "evidence": bool(self.evidence_for or self.evidence_against),
                 "citations": bool(self.citations),
                 "counterfactuals": bool(self.counterfactuals),
                 "simulation_trace": self.simulation_trace is not None,
                 "alternatives": bool(self.alternatives),
                 "patient_summary": bool(self.patient_summary.text)}
        return [name for name, present in parts.items() if not present]


# ---------------------------------------------------------------------------
# 3.10 Agents, orchestrators, recommendations, decisions
# ---------------------------------------------------------------------------

class Goal(_Model):
    goal_id: str
    text: str
    owner: str
    priority: int = Field(ge=1, le=5)
    check: GoalCheck
    deadline: datetime | None = None


class ToolCallRecord(_Model):
    tool: str
    args_hash: str
    result_ref: str
    ahdt_layer: int | None = None


class Recommendation(_Model):
    recommendation_id: str
    episode_id: str | None = None
    hdt_id: str
    kind: Literal["diagnosis", "test", "treatment", "care", "lifestyle", "data_request"]
    payload: dict[str, Any]
    confidence: float | None = Field(None, ge=0, le=1)
    status: Literal["proposed", "accepted", "edited", "overridden", "declined", "signed"]
    bundle_id: str | None = None
    autonomy_level: AutonomyLevel
    created_by_agent: str


class AgentResult(_Model):
    agent: str
    goal_id: str
    proposals: list[Recommendation] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    autonomy_level: AutonomyLevel
    status: Literal["ok", "degraded", "failed"]
    missing_evidence: list[str] = Field(default_factory=list)


class Decider(_Model):
    id: str
    role: Role


class ClinicalDecision(_Model):
    decision_id: str
    recommendation_id: str
    decided_by: Decider
    decision: Literal["accept", "edit", "reject", "sign", "verify", "query", "consent",
                      "decline"]
    edited_payload: dict[str, Any] | None = None
    override_reason: str | None = None
    signed_at: datetime | None = None
    signature: str


@runtime_checkable
class Agent(Protocol):
    name: str
    tier: Literal["7.1", "7.2", "7.3"]
    twin: DTKind | Literal["apdt"]
    tools: frozenset[str]

    async def act(self, goal: Goal, ctx: CallContext) -> AgentResult: ...


class Orchestrator(Agent, Protocol):
    goal: Goal

    def plan(self, state: Mapping[str, Any]) -> list[Mapping[str, Any]]: ...

    async def delegate(self, step: Mapping[str, Any], ctx: CallContext) -> AgentResult: ...

    def report(self, state: Mapping[str, Any]) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# 3.11 Audit
# ---------------------------------------------------------------------------

class Actor(_Model):
    id: str
    role: str


class AuditRecord(_Model):
    seq: int = Field(ge=0)
    prev_hash: str
    hash: str
    t: datetime
    service: str
    actor: Actor
    agent: str | None = None
    hdt_id: str | None = None
    tenant_id: str | None = None
    episode_id: str | None = None
    action: str
    target: str
    purpose: str
    outcome: Literal["ok", "denied", "degraded", "error"]
    reason: str | None = None
    trace_id: str
    detail_ref: str | None = None


# ---------------------------------------------------------------------------
# 3.6 Tool arguments and responses
# ---------------------------------------------------------------------------

Language = Literal["en", "yo", "ha", "ig", "pcm"]
Audience = Literal["clinician", "patient", "pharmacist", "nurse", "radiologist"]


class Period(_Model):
    start: datetime
    end: datetime


class _ToolArgs(_Model):
    hdt_id: Annotated[str, Field(pattern=r"^hdt-[0-9a-f]{12}$")]


class _DataArgs(_ToolArgs):
    as_of: datetime | None = None


class ObservationsArgs(_DataArgs):
    codes: list[str] = Field(min_length=1)
    period: Period | None = None
    aggregate: Literal["raw", "1m", "5m", "1h"] = "raw"


class ImagingArgs(_DataArgs):
    modality: Literal["CR", "DX", "CT", "MR", "US", "SM"]
    period: Period | None = None


class MedicationsArgs(_DataArgs):
    active_only: bool = False


class GenomeArgs(_DataArgs):
    genes: list[str] = Field(min_length=1)


class GraphQueryArgs(_DataArgs):
    question: str = Field(min_length=1)
    mode: Literal["graphrag", "vector", "chunkless", "hybrid"] = "hybrid"


class TimeseriesArgs(_DataArgs):
    code: str
    period: Period
    max_points: int | None = Field(None, ge=2)


class DocumentsArgs(_DataArgs):
    query: str = Field(min_length=1)
    types: list[Literal["discharge_summary", "note", "report"]] | None = None
    top_k: int = Field(5, ge=1, le=50)


class KnowledgeArgs(_DataArgs):
    query_id: str
    params: dict[str, Any]


class KAnonymity(_Model):
    k: int = Field(ge=2)


class DifferentialPrivacy(_Model):
    epsilon: float = Field(gt=0)


class CohortExtractArgs(_DataArgs):
    cohort_def: dict[str, Any]
    fields: list[str] = Field(min_length=1)
    privacy: KAnonymity | DifferentialPrivacy


class StateArgs(_ToolArgs):
    dt: DTKind


class ForecastArgs(_ToolArgs):
    dt: DTKind
    variable: str
    horizon_h: float = Field(gt=0, le=720)


class SimulateArgs(_ToolArgs):
    dt: DTKind
    scenario: Scenario
    fork: Literal[True] = True
    horizon_h: float = Field(72, gt=0, le=720)


class FacetArgs(_ToolArgs):
    anatomy: str
    facet: str


class CosimulateArgs(_ToolArgs):
    scenario: Scenario
    dts: list[DTKind] = Field(min_length=2)
    horizon_h: float = Field(gt=0, le=720)
    step_s: float = Field(gt=0)
    fork: Literal[True] = True


class CalibrateArgs(_ToolArgs):
    dt: DTKind
    model_id: str


class ExplainArgs(_ToolArgs):
    output_id: str
    audience: Audience = "clinician"


class CausalGraphArgs(_ToolArgs):
    output_id: str


class ConverseArgs(_ToolArgs):
    utterance: str = Field(min_length=1)
    language: Language
    session_id: str | None = None


class PerceiveArgs(_ToolArgs):
    modality: Literal["speech", "image", "signal", "text"]
    content_ref: str | None = None
    text: str | None = None
    language: Language | None = None


class ReasonArgs(_ToolArgs):
    kind: Literal["ontology", "causal", "probabilistic", "temporal"]
    query: str = Field(min_length=1)


class RequestDataArgs(_ToolArgs):
    what: list[str] = Field(min_length=1)
    from_: Literal["person", "device", "clinician"] = Field(alias="from")
    channel: Literal["app", "sms", "ussd", "voice"] | None = None
    deadline_h: float | None = Field(None, gt=0)


class SeriesPoint(_Model):
    t: datetime
    v: float | str | bool
    unit: str
    quality: Quality = Quality.OK


class ObservationsData(_Model):
    series: dict[str, list[SeriesPoint]]


class ImagingStudy(_Model):
    study_uid: str
    modality: str
    started: datetime
    description: str
    dicomweb_url: str
    series_count: int = Field(ge=0)


class ImagingData(_Model):
    studies: list[ImagingStudy]


class MedicationEntry(_Model):
    atc: str
    rxnorm: str | None = None
    display: str
    dose: str
    route: str
    frequency: str
    start: datetime
    end: datetime | None = None
    adherence: float | None = Field(None, ge=0, le=1)


class MedicationsData(_Model):
    medications: list[MedicationEntry]


class Variant(_Model):
    gene: str
    star_allele: str | None = None
    rsid: str | None = None
    genotype: str
    phenotype: str
    source: str


class GenomeData(_Model):
    variants: list[Variant]


class GraphCitation(_Model):
    node_id: str | None = None
    doc_id: str | None = None
    label: str
    path: list[str] | None = None


class Subgraph(_Model):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphQueryData(_Model):
    answer: str
    citations: list[GraphCitation]
    subgraph: Subgraph | None = None


class StateData(_Model):
    dt: DTKind
    state: dict[str, Any]
    status: Literal["normal", "watch", "alert"]
    updated_at: datetime
    output_id: str


class ForecastData(_Model):
    t: list[float]
    mean: list[float]
    lower: list[float]
    upper: list[float]
    level: float = Field(gt=0, lt=1)
    output_id: str


class SimulateData(Trajectory):
    fork_id: str


class ConverseData(_Model):
    reply: str
    language: Language
    session_id: str
    grounded_on: list[GraphCitation]


class TimeseriesData(_Model):
    t: list[datetime]
    v: list[float]
    unit: str


class DocumentHit(_Model):
    doc_id: str
    section_path: list[str]
    snippet: str
    score: float


class DocumentsData(_Model):
    hits: list[DocumentHit]


class KnowledgeData(_Model):
    rows: list[dict[str, Any]]


class CohortExtractData(_Model):
    rows: list[dict[str, Any]] | None = None
    aggregates: dict[str, Any] | None = None
    privacy_report: dict[str, Any]


class CalibrateData(_Model):
    instance_id: str
    revision: int = Field(ge=0)
    fit_before: float
    fit_after: float


class GraphNode(_Model):
    id: str
    kind: Literal["model", "message", "observation"]
    label: str


class GraphEdge(_Model):
    from_: str = Field(alias="from")
    to: str
    weight: float


class CausalGraphData(_Model):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Finding(_Model):
    code: str
    display: str
    value: Any = None
    confidence: float = Field(ge=0, le=1)


class PerceiveData(_Model):
    findings: list[Finding]
    transcript: str | None = None


class ReasonData(_Model):
    answer: str
    justification: list[str]


class RequestDataData(_Model):
    request_id: str
    status: Literal["queued", "sent", "answered", "expired"]


TOOL_ARGS: Mapping[str, type[_ToolArgs]] = {
    "ahdt.data.observations": ObservationsArgs,
    "ahdt.data.imaging": ImagingArgs,
    "ahdt.data.medications": MedicationsArgs,
    "ahdt.data.genome": GenomeArgs,
    "ahdt.data.graph_query": GraphQueryArgs,
    "ahdt.data.timeseries": TimeseriesArgs,
    "ahdt.data.documents": DocumentsArgs,
    "ahdt.data.knowledge": KnowledgeArgs,
    "ahdt.data.cohort_extract": CohortExtractArgs,
    "ahdt.model.state": StateArgs,
    "ahdt.model.forecast": ForecastArgs,
    "ahdt.model.simulate": SimulateArgs,
    "ahdt.model.facet": FacetArgs,
    "ahdt.model.cosimulate": CosimulateArgs,
    "ahdt.model.calibrate": CalibrateArgs,
    "ahdt.xai.explain": ExplainArgs,
    "ahdt.xai.causal_graph": CausalGraphArgs,
    "ahdt.cognitive.converse": ConverseArgs,
    "ahdt.cognitive.perceive": PerceiveArgs,
    "ahdt.cognitive.reason": ReasonArgs,
    "ahdt.cognitive.request_data": RequestDataArgs,
}

TOOL_RESPONSES: Mapping[str, type[BaseModel]] = {
    "ahdt.data.observations": ObservationsData,
    "ahdt.data.imaging": ImagingData,
    "ahdt.data.medications": MedicationsData,
    "ahdt.data.genome": GenomeData,
    "ahdt.data.graph_query": GraphQueryData,
    "ahdt.data.timeseries": TimeseriesData,
    "ahdt.data.documents": DocumentsData,
    "ahdt.data.knowledge": KnowledgeData,
    "ahdt.data.cohort_extract": CohortExtractData,
    "ahdt.model.state": StateData,
    "ahdt.model.forecast": ForecastData,
    "ahdt.model.simulate": SimulateData,
    "ahdt.model.facet": FacetView,
    "ahdt.model.cosimulate": SimulateData,
    "ahdt.model.calibrate": CalibrateData,
    "ahdt.xai.explain": AHDTExplanation,
    "ahdt.xai.causal_graph": CausalGraphData,
    "ahdt.cognitive.converse": ConverseData,
    "ahdt.cognitive.perceive": PerceiveData,
    "ahdt.cognitive.reason": ReasonData,
    "ahdt.cognitive.request_data": RequestDataData,
}


# ---------------------------------------------------------------------------
# 3.15 Population and APDT MCP tools
# ---------------------------------------------------------------------------

class PriorsArgs(_Model):
    conditions: list[str] = Field(min_length=1)
    age_band: str
    sex: Literal["female", "male"]
    region: str
    season: Literal["dry", "rainy"]


class PriorRow(_Model):
    condition: str
    prevalence: float = Field(ge=0, le=1)
    age_band: str
    season: str
    region: str
    source: str


class PriorsData(_Model):
    priors: list[PriorRow]


class NormsArgs(_Model):
    fields: list[str] = Field(min_length=1)
    age_band: str
    sex: Literal["female", "male"]


class NormRow(_Model):
    field: str
    unit: str
    p05: float
    p50: float
    p95: float
    n: int = Field(ge=0)


class NormsData(_Model):
    norms: list[NormRow]


class ContributeArgs(_Model):
    contract: Literal["cohort_contribution", "registry_case"]
    records: list[dict[str, Any]] = Field(min_length=1)


class ContributeData(_Model):
    accepted: int = Field(ge=0)
    suppressed: int = Field(ge=0)
    k: int = Field(ge=1)


class _EpisodeArgs(_Model):
    tenant_id: Literal["fac-a", "fac-b"]
    episode_id: Annotated[str, Field(pattern=r"^ep-\d{4}-\d{6}$")]


class EpisodeSummaryArgs(_EpisodeArgs):
    pass


class EpisodeSummaryData(_Model):
    episode: Episode
    problems: list[Code]
    active_medications: list[str]
    open_recommendations: list[str]
    latest_news2: int | None = None


class DifferentialArgs(_EpisodeArgs):
    top_k: int = Field(5, ge=1, le=20)


class DifferentialEntry(_Model):
    code: Code
    probability: float = Field(ge=0, le=1)
    recommendation_id: str
    bundle_id: str


class DifferentialData(_Model):
    differential: list[DifferentialEntry]
    conformal_set: list[str]


class TreatmentOptionsArgs(_EpisodeArgs):
    diagnosis_code: str


class TreatmentOption(_Model):
    text: str
    atc: list[str]
    score: float
    guideline_concordant: bool
    recommendation_id: str
    bundle_id: str


class TreatmentOptionsData(_Model):
    options: list[TreatmentOption]


class APDTExplainArgs(_Model):
    tenant_id: Literal["fac-a", "fac-b"]
    bundle_id: str
    audience: Literal["medical_officer", "pharmacist", "nurse", "radiologist",
                      "patient"] = "medical_officer"


class ConsentGetArgs(_Model):
    tenant_id: Literal["fac-a", "fac-b"]
    hdt_id: Annotated[str, Field(pattern=r"^hdt-[0-9a-f]{12}$")]


class ConsentData(_Model):
    hdt_id: str
    purposes: list[PurposeOfUse]
    refused_tools: list[str]
    consent_id: str | None = None


POPULATION_TOOL_ARGS: Mapping[str, type[_Model]] = {
    "population.priors": PriorsArgs,
    "population.norms": NormsArgs,
    "population.contribute": ContributeArgs,
}
POPULATION_TOOL_RESPONSES: Mapping[str, type[_Model]] = {
    "population.priors": PriorsData,
    "population.norms": NormsData,
    "population.contribute": ContributeData,
}
APDT_TOOL_ARGS: Mapping[str, type[_Model]] = {
    "apdt.episode.summary": EpisodeSummaryArgs,
    "apdt.diagnosis.differential": DifferentialArgs,
    "apdt.treatment.options": TreatmentOptionsArgs,
    "apdt.explain": APDTExplainArgs,
    "apdt.consent.get": ConsentGetArgs,
}
APDT_TOOL_RESPONSES: Mapping[str, type[_Model]] = {
    "apdt.episode.summary": EpisodeSummaryData,
    "apdt.diagnosis.differential": DifferentialData,
    "apdt.treatment.options": TreatmentOptionsData,
    "apdt.explain": ExplanationBundle,
    "apdt.consent.get": ConsentData,
}


# ---------------------------------------------------------------------------
# 3.7 APDT API bodies
# ---------------------------------------------------------------------------

TenantId = Literal["fac-a", "fac-b"]


class EpisodeCreate(_Model):
    hdt_id: Annotated[str, Field(pattern=r"^hdt-[0-9a-f]{12}$")]
    reason: str = Field(min_length=1)
    encounter_class: Literal["AMB", "EMER", "IMP", "HH", "VR"] = "AMB"
    responsible_clinician: str | None = None


class EpisodeView(_Model):
    episode: Episode
    episode_of_care: dict[str, Any]
    resources: list[dict[str, Any]] = Field(default_factory=list)


class PatientEntry(_Model):
    """A patient of a facility, as the demo patient directory lists them."""

    hdt_id: str
    initials: str
    sex: Literal["female", "male"]
    age_years: int = Field(ge=0)
    language: Language
    tenant_id: TenantId


class EpisodeListItem(_Model):
    episode: Episode
    patient: PatientEntry | None = None


class IntakeFinding(_Model):
    id: str
    name: str
    capture: Literal["question", "exam", "lab"]


class IntakeMeasurement(_Model):
    field: str
    unit: str


class IntakeTest(_Model):
    id: str
    name: str


class IntakeCatalogue(_Model):
    """What a clinician can record at intake: findings, tests and measurements from the KB."""

    findings: list[IntakeFinding]
    tests: list[IntakeTest]
    measurements: list[IntakeMeasurement]


class IntakeRecord(_Model):
    """Findings (present or absent), test results (positive or negative) and measurements of
    one episode, keyed by KB id or field name, with the patient details the reasoner needs."""

    findings: dict[str, bool] = Field(default_factory=dict)
    tests: dict[str, bool] = Field(default_factory=dict)
    measurements: dict[str, float] = Field(default_factory=dict)
    weight_kg: float | None = Field(None, gt=0, le=400)
    pregnancy: Literal["none", "t1", "t2", "t3"] = "none"
    avpu: Literal["A", "V", "P", "U"] = "A"


class EpisodeClose(_Model):
    outcome: str
    discharge_summary_ref: str | None = None


class DiagnosisEntry(_Model):
    """The diagnosis the medical officer makes, in the medical officer's own words.
    `recommendation_id` names the APDT proposal it was taken from, if any."""

    condition: str = Field(min_length=1, max_length=200)
    status: Literal["confirmed", "provisional"] = "confirmed"
    basis: str | None = Field(None, max_length=2000)
    recommendation_id: str | None = None


class DispenseEntry(_Model):
    """A medication the pharmacist hands over for the patient."""

    medication: str = Field(min_length=1, max_length=200)
    dose: str = Field(min_length=1, max_length=200)
    quantity: str = Field(min_length=1, max_length=100)
    days_supply: int | None = Field(None, ge=1, le=365)
    notes: str | None = Field(None, max_length=2000)


class AdministrationEntry(_Model):
    """A medication the nurse gives, or a care activity the nurse carries out."""

    kind: Literal["medication", "care"]
    item: str = Field(min_length=1, max_length=200)
    dose: str | None = Field(None, max_length=200)
    route: Literal["oral", "intravenous", "intramuscular", "subcutaneous", "topical",
                   "inhaled", "rectal", "other"] | None = None
    given_at: datetime | None = None
    notes: str | None = Field(None, max_length=2000)


class ClinicalEntry(_Model):
    """One entry of an episode's clinical record: a diagnosis, a dispense or care given.
    `resource` is the FHIR resource the entry is stored as."""

    entry_id: str
    kind: Literal["diagnosis", "dispense", "administration"]
    title: str
    details: list[str] = Field(default_factory=list)
    recorded_by: Actor
    recorded_at: datetime
    resource: dict[str, Any]


class RunStarted(_Model):
    run_id: str
    goal: Literal["diagnosis", "treatment", "care"]


class RunStatus(_Model):
    run_id: str
    status: Literal["running", "waiting_for_human", "done", "failed"]
    interrupt: Interrupt | None = None
    result: dict[str, Any] | None = None


class SourcedItem(_Model):
    source: Literal["apdt", "ahdt"]
    kind: str
    label: str
    value: Any = None
    unit: str | None = None
    time: datetime | None = None
    ref: str | None = None


class UnifiedView(_Model):
    episode_id: str
    items: list[SourcedItem]
    degraded: bool = False
    missing_evidence: list[str] = Field(default_factory=list)


class TwinTile(_Model):
    dt: DTKind
    status: Literal["normal", "watch", "alert", "unavailable"]
    headline: str
    updated_at: datetime | None = None


class AHDTPanel(_Model):
    hdt_id: str
    tiles: list[TwinTile]
    vitals: dict[str, SourcedItem]
    forecast: dict[str, Any] | None = None
    degraded: bool = False


class Preferences(_Model):
    answers: dict[str, Any]


class PreferenceWeights(_Model):
    hdt_id: str
    weights: dict[str, float]


class PatientMessage(_Model):
    text: str | None = None
    audio_ref: str | None = None
    language: Language
    channel: Literal["app", "sms", "ussd", "voice", "web"] = "app"


class PatientReply(_Model):
    reply: str
    language: Language
    audio_ref: str | None = None
    grounded_on: list[str] = Field(default_factory=list)


class WorklistItem(_Model):
    item_id: str
    kind: str
    episode_id: str | None = None
    hdt_id: str | None = None
    title: str
    due_by: datetime | None = None
    priority: int = Field(3, ge=1, le=5)


class Worklist(_Model):
    role: Role
    tenant_id: str
    items: list[WorklistItem]


class AlertAck(_Model):
    by: str
    observations: list[dict[str, Any]] | None = None


class AlertAckResult(_Model):
    alert_id: str
    acknowledged_by: str
    acknowledged_at: datetime


class ReferralRequest(_Model):
    episode_id: Annotated[str, Field(pattern=r"^ep-\d{4}-\d{6}$")]
    to_tenant: TenantId
    reason: str
    urgency: Literal["routine", "urgent", "emergency"] = "routine"


class ReferralResult(_Model):
    referral_id: str
    bundle_ref: str
    status: Literal["sent", "queued"]


APDT_API_MODELS: tuple[type[_Model], ...] = (
    EpisodeCreate, EpisodeView, PatientEntry, EpisodeListItem, IntakeCatalogue, IntakeRecord,
    EpisodeClose, DiagnosisEntry, DispenseEntry, AdministrationEntry, ClinicalEntry,
    RunStarted, RunStatus, UnifiedView, AHDTPanel, Preferences,
    PreferenceWeights, PatientMessage, PatientReply, Worklist, AlertAck, AlertAckResult,
    ReferralRequest, ReferralResult,
)
