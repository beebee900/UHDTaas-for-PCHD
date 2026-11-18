"""Every connector of design 03, section 3.16, as a `CoupledConnector`.

Sources follow the WP14a state names and units (model output ports) and the registry
field names. Supplied connectors keep their own mapping; an adapter gives them the keys
they expect. `SystemToWholeBodyConnector` is generated once per physiological twin.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache, lru_cache
from typing import Any, ClassVar

from ahdt.coupling.base import CoupledConnector, SuppliedAdapter
from ahdt.coupling.mapping import SourceView, derived, flag_or_condition, take
from ahdt.registry import load_registry
from atra import connector_contracts as cc
from atra import connectors as supplied
from atra import gateway
from atra.config import get_settings
from atra.connectors import DTKind, TwinEndpoint
from atra.contracts import FieldDefinition
from atra.kb import KBError, KnowledgeBase

K = DTKind


# ---------------------------------------------------------------------------
# Supplied connectors
# ---------------------------------------------------------------------------

class CardiovascularRespiratoryConnector(SuppliedAdapter,
                                         supplied.CardiovascularRespiratoryConnector):
    IN_RULES = (
        take("spo2", "state:spo2", "field:spo2"),
        take("pao2", "state:pao2"),
        take("paco2", "state:paco2"),
        take("respiratory_rate", "field:respiratory_rate", "state:respiratory_rate"),
    )

    def adapt(self, view: SourceView) -> dict[str, Any]:
        return {"heart_rate_bpm": view.first(("state:heart_rate", "field:heart_rate"), "/min"),
                "stroke_volume_ml": view.value("state:stroke_volume", "mL"),
                "map_mmhg": view.first(("state:map", "field:map"), "mm[Hg]"),
                "sbp_mmhg": view.first(("state:sbp", "field:sbp"), "mm[Hg]"),
                "dbp_mmhg": view.first(("state:dbp", "field:dbp"), "mm[Hg]"),
                "_models": view.raw.get("_models", {})}


class EndocrineBehaviouralConnector(SuppliedAdapter, supplied.EndocrineBehaviouralConnector):
    IN_RULES = (
        take("active_minutes_24h", "field:active_minutes", "context:active_minutes_24h"),
        take("sleep_hours", "field:sleep_duration", "context:sleep_hours"),
        take("carbohydrate_g", "field:carb_intake", "context:carbohydrate_g"),
        take("medication_adherence", "field:adherence"),
    )

    def adapt(self, view: SourceView) -> dict[str, Any]:
        return {"glucose_mmol_l": view.first(("state:glucose", "field:glucose"), "mmol/L"),
                "tir_pct": view.first(("field:time_in_range_24h",
                                       "context:time_in_range_24h"), "%"),
                "cortisol_z": view.value("context:cortisol_z")}


class IndividualToPopulationConnector(SuppliedAdapter,
                                      supplied.IndividualToPopulationConnector):
    def adapt(self, view: SourceView) -> dict[str, Any]:
        return {"age_years": view.value("context:age_years"),
                "sex": view.value("context:sex"),
                "address": view.value("context:address"),
                "condition_codes": view.value("context:condition_codes") or [],
                "weight_kg": view.first(("field:weight", "state:weight"), "kg"),
                "height_m": view.first(("field:height", "state:height"), "m")}


class ClinicalFindingWriteBackConnector(SuppliedAdapter,
                                        gateway.ClinicalFindingWriteBackConnector):
    """The source state is the signed FHIR resource from the APDT, as it is."""


class DeteriorationEventConnector(SuppliedAdapter, gateway.DeteriorationEventConnector):
    def adapt(self, view: SourceView) -> dict[str, Any]:
        return {"news2": view.first(("state:news2", "field:news2", "context:news2")),
                "risk": view.first(("context:risk", "field:deterioration_risk")),
                "horizon_h": view.value("context:horizon_h"),
                "drivers": view.value("context:drivers"),
                "output_id": view.value("context:output_id")}


# ---------------------------------------------------------------------------
# Connectors of the design
# ---------------------------------------------------------------------------

_EGFR = (take("egfr", "state:egfr", "field:egfr"),)
_INFECTION = (
    take("core_temp", "field:temperature", "state:core_temp"),
    take("inflammation_index", "state:inflammation_index"),
    derived("sepsis_flag", flag_or_condition("sepsis_flag", "cond.sepsis")),
)


def _species(view: SourceView) -> str | None:
    named = view.value("context:parasite_species")
    if named is not None:
        return str(named)
    found = view.conditions()
    return "Plasmodium falciparum" if found and "cond.malaria_falciparum" in found else None


def _carb_appearance(view: SourceView) -> float | None:
    """Glucose rate of appearance (mg/kg/min) times body weight, as mmol/min."""
    rate = view.value("state:absorption_rate", "mg/kg/min")
    weight = view.first(("state:weight", "field:weight", "context:weight_kg"), "kg")
    if rate is None or weight is None:
        return None
    from atra.units import convert

    return round(convert(float(rate) * float(weight), "mg/min", "mmol/min",
                         substance="glucose"), 4)


def _age_band(view: SourceView) -> str | None:
    band = view.value("context:age_band")
    if band is not None:
        return str(band)
    age = view.value("context:age_years")
    if age is None:
        return None
    lo = (int(age) // 5) * 5
    return f"{lo}-{lo + 4}"


def _state_of_residence(view: SourceView) -> str | None:
    address = view.value("context:address")
    if isinstance(address, Mapping) and address.get("state"):
        return str(address["state"])
    named = view.value("context:state")
    return None if named is None else str(named)


class RenalHepatobiliaryConnector(CoupledConnector, spec="RenalHepatobiliaryConnector"):
    OUT_RULES = _EGFR


class InfectionHaemodynamicsConnector(CoupledConnector, spec="InfectionHaemodynamicsConnector"):
    OUT_RULES = _INFECTION


class InfectionNeuroConnector(CoupledConnector, spec="InfectionNeuroConnector"):
    OUT_RULES = _INFECTION


class HaemolysisConnector(CoupledConnector, spec="HaemolysisConnector"):
    OUT_RULES = (take("parasitaemia", "state:parasitaemia", "field:parasitaemia"),
                 derived("species", _species))


class OxygenCarriageConnector(CoupledConnector, spec="OxygenCarriageConnector"):
    OUT_RULES = (take("hb", "state:hb", "field:hb"),
                 take("platelets", "state:platelets", "field:platelets"))


class GlucoseRenalConnector(CoupledConnector, spec="GlucoseRenalConnector"):
    OUT_RULES = (take("glucose", "state:glucose", "field:glucose"),
                 take("hba1c", "field:hba1c"))


class HepaticClearanceConnector(CoupledConnector, spec="HepaticClearanceConnector"):
    OUT_RULES = (take("alt", "field:alt"),
                 take("bilirubin", "field:bilirubin"),
                 take("clearance_factor", "state:clearance_factor", "field:clearance_factor"))


class RenalClearanceConnector(CoupledConnector, spec="RenalClearanceConnector"):
    OUT_RULES = _EGFR


class NeuroEndocrineConnector(CoupledConnector, spec="NeuroEndocrineConnector"):
    OUT_RULES = (take("stress_drive", "state:stress_drive", "context:stress_drive"),
                 take("circadian_phase", "state:circadian_phase"))


class EndocrineReproductiveConnector(CoupledConnector, spec="EndocrineReproductiveConnector"):
    OUT_RULES = (take("oestradiol", "state:oestradiol", "field:oestradiol"),
                 take("progesterone", "state:progesterone", "field:progesterone"),
                 take("testosterone", "state:testosterone", "field:testosterone"))
    IN_RULES = (derived("pregnant", flag_or_condition("pregnant", "cond.pregnancy")),
                take("gestation_weeks", "field:gestation_weeks", "state:gestation_weeks"),
                take("cycle_day", "field:cycle_day", "state:cycle_day"))


class MusculoskeletalBehaviouralConnector(CoupledConnector,
                                          spec="MusculoskeletalBehaviouralConnector"):
    OUT_RULES = (take("gait_speed", "field:gait_speed", "state:gait_speed"),
                 take("fall_risk", "field:fall_risk", "state:fall_risk"))
    IN_RULES = (take("steps_target", "context:steps_target", "state:steps_target"),)


class IntegumentaryThermoConnector(CoupledConnector, spec="IntegumentaryThermoConnector"):
    OUT_RULES = (take("skin_temp", "state:skin_temp", "field:skin_temp"),
                 take("sweat_rate", "field:sweat_rate", "state:sweat_rate"),
                 take("heat_index", "state:heat_index", "field:heat_index"))


class SensoryBehaviouralConnector(CoupledConnector, spec="SensoryBehaviouralConnector"):
    OUT_RULES = (take("visual_acuity_logmar", "field:visual_acuity_logmar",
                      "state:visual_acuity_logmar"),
                 take("hearing_threshold", "field:hearing_threshold", "state:hearing_threshold"))


class DigestiveEndocrineConnector(CoupledConnector, spec="DigestiveEndocrineConnector"):
    OUT_RULES = (derived("carb_appearance", _carb_appearance),
                 take("oral_intake_ok", "field:oral_intake_ok", "state:oral_intake_ok"))


class RespiratoryRenalConnector(CoupledConnector, spec="RespiratoryRenalConnector"):
    OUT_RULES = (take("paco2", "state:paco2", "field:paco2"),
                 take("ph", "state:ph", "field:ph", "context:ph"))


class ContextToBehaviourConnector(CoupledConnector, spec="ContextToBehaviourConnector"):
    OUT_RULES = (take("household_support", "field:household_support"),
                 take("distance_km", "field:distance_to_facility"),
                 take("bednet_use", "context:bednet_use"),
                 take("food_security", "field:food_security"))


class ExposomeConnector(CoupledConnector, spec="ExposomeConnector", any_target=True):
    """Social to Respiratory and to Integumentary: one class, two targets."""

    TARGETS: ClassVar[frozenset[DTKind]] = frozenset({K.RESPIRATORY, K.INTEGUMENTARY})
    OUT_RULES = (take("pm25", "field:pm25"),
                 take("no2", "field:no2"),
                 take("temp_c", "field:ambient_temp"),
                 take("humidity", "field:humidity"))

    def __init__(self, source: TwinEndpoint, target: TwinEndpoint, *args: Any,
                 **kwargs: Any) -> None:
        if target.kind not in self.TARGETS:
            raise ValueError(f"ExposomeConnector cannot target {target.kind.value}")
        super().__init__(source, target, *args, **kwargs)


_PRIOR_FIELDS = ("condition", "prevalence", "age_band", "season", "region")


class PriorConnector(CoupledConnector, spec="PriorConnector"):
    OUT_RULES = tuple(take(f, f"context:{f}") for f in _PRIOR_FIELDS)


class NormsConnector(CoupledConnector, spec="NormsConnector", any_target=True):
    """Population to each physiological twin (one connector per target)."""

    OUT_RULES = tuple(take(f, f"context:{f}") for f in ("field", "p05", "p50", "p95"))

    def __init__(self, source: TwinEndpoint, target: TwinEndpoint, *args: Any,
                 **kwargs: Any) -> None:
        if not target.kind.is_physiological:
            raise ValueError(f"NormsConnector cannot target {target.kind.value}")
        super().__init__(source, target, *args, **kwargs)


class BehaviourToSocialConnector(CoupledConnector, spec="BehaviourToSocialConnector"):
    OUT_RULES = (take("needs_carer", "context:needs_carer"),
                 take("adherence", "field:adherence", "state:adherence"))


class AHDTEventToAPDTConnector(CoupledConnector, spec="AHDTEventToAPDTConnector"):
    OUT_RULES = tuple(take(f, f"context:{f}") for f in ("kind", "code", "value", "output_id"))
    ENUMS = {"kind": cc.CLINICAL_EVENT_KINDS}


class ReferralConnector(CoupledConnector, spec="ReferralConnector"):
    """Between two facilities' APDTs; endpoints use the facility as the instance."""

    OUT_RULES = tuple(take(f, f"context:{f}") for f in ("bundle_ref", "reason", "urgency"))
    ENUMS = {"urgency": cc.REFERRAL_URGENCIES}


class RegistryContributionConnector(CoupledConnector, spec="RegistryContributionConnector"):
    """De-identified case: only the five contract fields leave the APDT."""

    OUT_RULES = (take("condition", "context:condition"),
                 derived("age_band", _age_band),
                 take("sex", "context:sex"),
                 derived("state", _state_of_residence),
                 take("outcome", "context:outcome"))


# ---------------------------------------------------------------------------
# Generated: one SystemToWholeBodyConnector per physiological twin
# ---------------------------------------------------------------------------

# Bands of the kb reference ranges, as WP14a reports them, to the summary status.
_BAND_STATUS = {"critical": "alert", "warning": "watch", "abnormal": "watch",
                "normal": "normal"}
_STATUS_RANK = {"normal": 0, "watch": 1, "alert": 2}


@lru_cache(maxsize=1)
def _kb() -> KnowledgeBase:
    return KnowledgeBase(get_settings().kb_dir)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def range_band(range_id: str, value: float, kb: KnowledgeBase | None = None) -> str:
    """critical, warning, abnormal, normal or unknown for a value against a kb range."""
    try:
        r = (kb or _kb()).entry(range_id).content()
    except KBError:
        return "unknown"
    for prefix, label in (("crit", "critical"), ("warn", "warning"), ("ref", "abnormal")):
        low, high = _number(r.get(f"{prefix}_low")), _number(r.get(f"{prefix}_high"))
        if (low is not None and value < low) or (high is not None and value > high):
            return label
    if all(_number(r.get(f"{p}_{s}")) is None for p in ("crit", "warn", "ref")
           for s in ("low", "high")):
        return "unknown"
    return "normal"


class SystemToWholeBodyConnector(CoupledConnector, spec="SystemToWholeBodyConnector",
                                 any_source=True):
    """Summary of one physiological twin for the Whole-Body twin."""

    FIELDS: ClassVar[tuple[FieldDefinition, ...]] = ()
    ENUMS = {"status": cc.SYSTEM_STATUSES}

    def map_outbound(self, source_state: Mapping[str, Any]) -> dict[str, Any]:
        assert self.OUT_CONTRACT is not None
        view = SourceView(source_state)
        key_values: dict[str, Any] = {}
        bands: list[str] = [str(v) for k, v in view.state.items() if k.endswith("_status")]
        for f in self.FIELDS:
            value = view.first((f"field:{f.name}", f"state:{f.name}"), f.ucum)
            number = _number(value)
            if number is None:
                continue
            key_values[f.name] = number
            if f.ref:
                bands.append(range_band(f.ref, number))
        statuses = [_BAND_STATUS[b] for b in bands if b in _BAND_STATUS]
        payload: dict[str, Any] = {"key_values": key_values}
        if statuses:
            payload["status"] = max(statuses, key=_STATUS_RANK.__getitem__)
        components = view.value("context:news2_components")
        if components is not None:
            payload["news2_components"] = components
        return self.checked(self.OUT_CONTRACT, payload)


@cache
def system_connector(kind: DTKind) -> type[SystemToWholeBodyConnector]:
    """The generated SystemToWholeBodyConnector of one physiological twin."""
    if not kind.is_physiological:
        raise ValueError(f"{kind.value} is not a physiological twin")
    definition = load_registry().get(kind)
    fields = tuple(definition.fields) if definition else ()
    name = "".join(p.title() for p in kind.value.split("_")) + "ToWholeBodyConnector"
    return type(name, (SystemToWholeBodyConnector,),
                {"SOURCE_KIND": kind, "FIELDS": fields, "__module__": __name__,
                 "__doc__": f"SystemToWholeBodyConnector of the {kind.value} twin."})


# ---------------------------------------------------------------------------
# Lookup by 3.16 name
# ---------------------------------------------------------------------------

CLASSES: Mapping[str, type[CoupledConnector]] = {
    cls.spec_name(): cls for cls in (
        CardiovascularRespiratoryConnector, EndocrineBehaviouralConnector,
        IndividualToPopulationConnector, ClinicalFindingWriteBackConnector,
        DeteriorationEventConnector, RenalHepatobiliaryConnector,
        InfectionHaemodynamicsConnector, InfectionNeuroConnector, HaemolysisConnector,
        OxygenCarriageConnector, GlucoseRenalConnector, HepaticClearanceConnector,
        RenalClearanceConnector, NeuroEndocrineConnector, EndocrineReproductiveConnector,
        MusculoskeletalBehaviouralConnector, IntegumentaryThermoConnector,
        SensoryBehaviouralConnector, DigestiveEndocrineConnector, RespiratoryRenalConnector,
        SystemToWholeBodyConnector, ContextToBehaviourConnector, ExposomeConnector,
        PriorConnector, NormsConnector, BehaviourToSocialConnector, AHDTEventToAPDTConnector,
        ReferralConnector, RegistryContributionConnector)}


def connector_class(spec_name: str, source: DTKind) -> type[CoupledConnector]:
    """The class for one concrete connector of `connector_contracts.expanded_pairs()`."""
    if spec_name == "SystemToWholeBodyConnector":
        return system_connector(source)
    return CLASSES[spec_name]

