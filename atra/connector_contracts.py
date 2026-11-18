"""Catalogue of every Layer 6.5 connector and its data contracts (design 03, section 3.16).

The supplied connectors keep their own contract objects; this catalogue refers to them.
Ranges are plausibility bounds, not clinical thresholds. `RANGE_GUARD` holds the
stricter safety limits that `RangeGuardPolicy` and the OPA connector policy apply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from atra.connectors import (
    CardiovascularRespiratoryConnector,
    Connector,
    DataContract,
    Direction,
    DTKind,
    EndocrineBehaviouralConnector,
    FieldSpec,
    IndividualToPopulationConnector,
    SyncMode,
)
from atra.gateway import ClinicalFindingWriteBackConnector, DeteriorationEventConnector

F = FieldSpec

RENAL_FUNCTION = DataContract("renal_function", "2.0", {
    "egfr": F("float", "mL/min/{1.73_m2}", min=1, max=200)})
INFECTION_STATE = DataContract("infection_state", "1.0", {
    "core_temp": F("float", "Cel", min=30, max=44),
    "inflammation_index": F("float", "1", min=0, max=1),
    "sepsis_flag": F("bool")})
PARASITE_BURDEN = DataContract("parasite_burden", "1.0", {
    "parasitaemia": F("float", "%", min=0, max=60),
    "species": F("str")})
OXYGEN_CARRIAGE = DataContract("oxygen_carriage", "1.0", {
    "hb": F("float", "g/dL", min=2, max=25),
    "platelets": F("float", "10*9/L", min=1, max=1500)})
GLYCAEMIA = DataContract("glycaemia", "1.0", {
    "glucose": F("float", "mmol/L", min=1, max=40),
    "hba1c": F("float", "%", required=False, min=3, max=20)})
HEPATIC_FUNCTION = DataContract("hepatic_function", "1.0", {
    "alt": F("float", "U/L", min=1, max=5000),
    "bilirubin": F("float", "umol/L", min=1, max=800),
    "clearance_factor": F("float", "1", min=0, max=2)})
HPA_AXIS = DataContract("hpa_axis", "1.0", {
    "stress_drive": F("float", "1", min=0, max=1),
    "circadian_phase": F("float", "h", min=0, max=24)})
GONADAL_HORMONES = DataContract("gonadal_hormones", "1.0", {
    "oestradiol": F("float", "pmol/L", required=False, min=0),
    "progesterone": F("float", "nmol/L", required=False, min=0),
    "testosterone": F("float", "nmol/L", required=False, min=0)})
REPRODUCTIVE_STATE = DataContract("reproductive_state", "1.0", {
    "pregnant": F("bool"),
    "gestation_weeks": F("float", "wk", required=False, min=0, max=44),
    "cycle_day": F("float", "d", required=False, min=1, max=40)})
MOBILITY = DataContract("mobility", "1.0", {
    "gait_speed": F("float", "m/s", min=0, max=3),
    "fall_risk": F("float", "1", min=0, max=1)})
ACTIVITY_PLAN = DataContract("activity_plan", "1.0", {
    "steps_target": F("float", "/d", min=0, max=40000)})
THERMAL_STATE = DataContract("thermal_state", "1.0", {
    "skin_temp": F("float", "Cel", min=20, max=42),
    "sweat_rate": F("float", "1", min=0, max=1),
    "heat_index": F("float", "Cel", min=10, max=60)})
SENSORY_STATUS = DataContract("sensory_status", "1.0", {
    "visual_acuity_logmar": F("float", "1", required=False, min=-0.3, max=3),
    "hearing_threshold": F("float", "dB", required=False, min=0, max=120)})
NUTRIENT_ABSORPTION = DataContract("nutrient_absorption", "1.0", {
    "carb_appearance": F("float", "mmol/min", min=0, max=50),
    "oral_intake_ok": F("bool")})
ACID_BASE_RESP = DataContract("acid_base_resp", "1.0", {
    "paco2": F("float", "kPa", min=1, max=15),
    "ph": F("float", "1", min=6.8, max=7.8)})
SYSTEM_SUMMARY = DataContract("system_summary", "1.0", {
    "status": F("str"),
    "key_values": F("dict"),
    "news2_components": F("dict", required=False)})
SOCIAL_CONTEXT = DataContract("social_context", "1.0", {
    "household_support": F("float", "1", min=0, max=1),
    "distance_km": F("float", "km", min=0, max=500),
    "bednet_use": F("bool"),
    "food_security": F("float", "1", min=0, max=1)})
EXPOSOME = DataContract("exposome", "1.0", {
    "pm25": F("float", "ug/m3", min=0, max=1000),
    "no2": F("float", "ug/m3", required=False, min=0),
    "temp_c": F("float", "Cel", required=False),
    "humidity": F("float", "%", required=False, min=0, max=100)})
POPULATION_PRIOR = DataContract("population_prior", "1.0", {
    "condition": F("str"),
    "prevalence": F("float", "1", min=0, max=1),
    "age_band": F("str"),
    "season": F("str"),
    "region": F("str")})
POPULATION_NORM = DataContract("population_norm", "1.0", {
    "field": F("str"),
    "p05": F("float"),
    "p50": F("float"),
    "p95": F("float")})
SUPPORT_NEED = DataContract("support_need", "1.0", {
    "needs_carer": F("bool"),
    "adherence": F("float", "1", min=0, max=1)})
CLINICAL_EVENT = DataContract("clinical_event", "1.0", {
    "kind": F("str"),
    "code": F("str"),
    "value": F("float", required=False),
    "output_id": F("str", required=False)})
REFERRAL = DataContract("referral", "1.0", {
    "bundle_ref": F("str"),
    "reason": F("str"),
    "urgency": F("str")})
REGISTRY_CASE = DataContract("registry_case", "1.0", {
    "condition": F("str"),
    "age_band": F("str"),
    "sex": F("str"),
    "state": F("str"),
    "outcome": F("str")})

CLINICAL_EVENT_KINDS = frozenset({"critical_reading", "new_imaging", "new_lab"})
SYSTEM_STATUSES = frozenset({"normal", "watch", "alert"})
REFERRAL_URGENCIES = frozenset({"routine", "urgent", "emergency"})

RANGE_GUARD: Mapping[str, tuple[float, float]] = {
    "core_temp": (30.0, 43.0),
    "glucose": (1.5, 40.0),
    "hb": (3.0, 25.0),
}

CARE = frozenset({"care"})
PUBLIC_HEALTH = frozenset({"public_health"})
CARE_OR_PUBLIC_HEALTH = frozenset({"care", "public_health"})

PHYSIOLOGICAL = tuple(k for k in DTKind if k.is_physiological)


@dataclass(frozen=True)
class ConnectorSpec:
    name: str
    source: DTKind
    target: DTKind
    mode: SyncMode
    direction: Direction
    out_contract: DataContract
    in_contract: DataContract | None = None
    purposes: frozenset[str] = CARE
    supplied: bool = False
    per_source: bool = False

    @property
    def contracts(self) -> tuple[DataContract, ...]:
        return (self.out_contract,) if self.in_contract is None else (
            self.out_contract, self.in_contract)


def _supplied(cls: type[Connector], purposes: frozenset[str] = CARE) -> ConnectorSpec:
    assert cls.SOURCE_KIND and cls.TARGET_KIND and cls.OUT_CONTRACT
    return ConnectorSpec(cls.__name__, cls.SOURCE_KIND, cls.TARGET_KIND, cls.MODE,
                         cls.DIRECTION, cls.OUT_CONTRACT, cls.IN_CONTRACT, purposes, True)


K = DTKind
U, B = Direction.UNIDIRECTIONAL, Direction.BIDIRECTIONAL
PUSH, RR = SyncMode.PUSH, SyncMode.REQUEST_REPLY

# `per_source` rows stand for one connector per physiological twin: SystemToWholeBodyConnector
# has each of them as source, NormsConnector has each of them as target.
CONNECTORS: tuple[ConnectorSpec, ...] = (
    _supplied(CardiovascularRespiratoryConnector),
    _supplied(EndocrineBehaviouralConnector),
    _supplied(IndividualToPopulationConnector, PUBLIC_HEALTH),
    _supplied(ClinicalFindingWriteBackConnector),
    _supplied(DeteriorationEventConnector),
    ConnectorSpec("RenalHepatobiliaryConnector", K.RENAL_URINARY, K.HEPATOBILIARY, RR, U,
                  RENAL_FUNCTION),
    ConnectorSpec("InfectionHaemodynamicsConnector", K.IMMUNE_LYMPHATIC, K.CARDIOVASCULAR,
                  SyncMode.STREAM, U, INFECTION_STATE),
    ConnectorSpec("InfectionNeuroConnector", K.IMMUNE_LYMPHATIC, K.NERVOUS, PUSH, U,
                  INFECTION_STATE),
    ConnectorSpec("HaemolysisConnector", K.IMMUNE_LYMPHATIC, K.HAEMATOLOGICAL, PUSH, U,
                  PARASITE_BURDEN),
    ConnectorSpec("OxygenCarriageConnector", K.HAEMATOLOGICAL, K.CARDIOVASCULAR, PUSH, U,
                  OXYGEN_CARRIAGE),
    ConnectorSpec("GlucoseRenalConnector", K.ENDOCRINE, K.RENAL_URINARY, PUSH, U, GLYCAEMIA),
    ConnectorSpec("HepaticClearanceConnector", K.HEPATOBILIARY, K.WHOLE_BODY, PUSH, U,
                  HEPATIC_FUNCTION),
    ConnectorSpec("RenalClearanceConnector", K.RENAL_URINARY, K.WHOLE_BODY, PUSH, U,
                  RENAL_FUNCTION),
    ConnectorSpec("NeuroEndocrineConnector", K.NERVOUS, K.ENDOCRINE, PUSH, U, HPA_AXIS),
    ConnectorSpec("EndocrineReproductiveConnector", K.ENDOCRINE, K.REPRODUCTIVE, PUSH, B,
                  GONADAL_HORMONES, REPRODUCTIVE_STATE),
    ConnectorSpec("MusculoskeletalBehaviouralConnector", K.MUSCULOSKELETAL,
                  K.BEHAVIOURAL_COGNITIVE, PUSH, B, MOBILITY, ACTIVITY_PLAN),
    ConnectorSpec("IntegumentaryThermoConnector", K.INTEGUMENTARY, K.NERVOUS, PUSH, U,
                  THERMAL_STATE),
    ConnectorSpec("SensoryBehaviouralConnector", K.SENSORY, K.BEHAVIOURAL_COGNITIVE, PUSH, U,
                  SENSORY_STATUS),
    ConnectorSpec("DigestiveEndocrineConnector", K.DIGESTIVE, K.ENDOCRINE, PUSH, U,
                  NUTRIENT_ABSORPTION),
    ConnectorSpec("RespiratoryRenalConnector", K.RESPIRATORY, K.RENAL_URINARY, PUSH, U,
                  ACID_BASE_RESP),
    ConnectorSpec("SystemToWholeBodyConnector", K.CARDIOVASCULAR, K.WHOLE_BODY, PUSH, U,
                  SYSTEM_SUMMARY, per_source=True),
    ConnectorSpec("ContextToBehaviourConnector", K.SOCIAL, K.BEHAVIOURAL_COGNITIVE, PUSH, U,
                  SOCIAL_CONTEXT),
    ConnectorSpec("ExposomeConnector", K.SOCIAL, K.RESPIRATORY, PUSH, U, EXPOSOME),
    ConnectorSpec("ExposomeConnector", K.SOCIAL, K.INTEGUMENTARY, PUSH, U, EXPOSOME),
    ConnectorSpec("PriorConnector", K.POPULATION, K.WHOLE_BODY, RR, U, POPULATION_PRIOR,
                  purposes=CARE_OR_PUBLIC_HEALTH),
    ConnectorSpec("NormsConnector", K.POPULATION, K.CARDIOVASCULAR, RR, U, POPULATION_NORM,
                  purposes=CARE_OR_PUBLIC_HEALTH, per_source=True),
    ConnectorSpec("BehaviourToSocialConnector", K.BEHAVIOURAL_COGNITIVE, K.SOCIAL, PUSH, U,
                  SUPPORT_NEED),
    ConnectorSpec("AHDTEventToAPDTConnector", K.WHOLE_BODY, K.PATIENT, PUSH, U,
                  CLINICAL_EVENT),
    ConnectorSpec("ReferralConnector", K.PATIENT, K.PATIENT, PUSH, U, REFERRAL),
    ConnectorSpec("RegistryContributionConnector", K.PATIENT, K.POPULATION, PUSH, U,
                  REGISTRY_CASE, purposes=PUBLIC_HEALTH),
)


def all_contracts() -> dict[str, DataContract]:
    """Every distinct contract, keyed by `<name>/v<version>`."""
    out: dict[str, DataContract] = {}
    for spec in CONNECTORS:
        for c in spec.contracts:
            out[f"{c.name}/v{c.version}"] = c
    return out


def connector_purposes() -> dict[str, list[str]]:
    """Contract name -> purposes allowed on it (input to the OPA connector policy)."""
    out: dict[str, set[str]] = {}
    for spec in CONNECTORS:
        for c in spec.contracts:
            out.setdefault(c.name, set()).update(spec.purposes)
    return {k: sorted(v) for k, v in sorted(out.items())}


def expanded_pairs() -> list[tuple[str, DTKind, DTKind]]:
    """(connector name, source, target) for every concrete connector of one HDT."""
    pairs: list[tuple[str, DTKind, DTKind]] = []
    for spec in CONNECTORS:
        if spec.per_source and spec.name == "SystemToWholeBodyConnector":
            pairs.extend((spec.name, k, K.WHOLE_BODY) for k in PHYSIOLOGICAL)
        elif spec.per_source and spec.name == "NormsConnector":
            pairs.extend((spec.name, K.POPULATION, k) for k in PHYSIOLOGICAL)
        else:
            pairs.append((spec.name, spec.source, spec.target))
    return pairs


def contract_json_schema(contract: DataContract) -> dict[str, object]:
    """JSON Schema of one connector contract (published to the schema registry)."""
    types = {"float": "number", "int": "integer", "str": "string", "bool": "boolean",
             "list": "array", "dict": "object"}
    props: dict[str, object] = {}
    for name, spec in contract.fields.items():
        prop: dict[str, object] = {"type": types[spec.dtype]}
        if spec.unit:
            prop["x-ucum"] = spec.unit
        if spec.min is not None:
            prop["minimum"] = spec.min
        if spec.max is not None:
            prop["maximum"] = spec.max
        if spec.description:
            prop["description"] = spec.description
        props[name] = prop
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://atra.local/schemas/connectors/{contract.name}/v{contract.version}",
        "title": f"{contract.name} v{contract.version}",
        "type": "object",
        "properties": props,
        "required": [n for n, s in contract.fields.items() if s.required],
        "additionalProperties": contract.allow_extra,
    }
