"""Source states per 3.16 connector: a valid one, its expected payload, and an invalid one.

`REPLIES` holds the reverse direction of the bidirectional connectors.
"""

from dataclasses import dataclass
from typing import Any

from atra.connector_contracts import expanded_pairs
from atra.connectors import DTKind as K


@dataclass(frozen=True)
class Case:
    valid: dict[str, Any]
    expected: dict[str, Any]
    invalid: dict[str, Any]


def st(values, units=None, fields=None, context=None):
    return {"state": values, "units": units or {}, "fields": fields or {},
            "context": context or {}}


def obs(**values):
    return {k: {"value": v, "unit": u} for k, (v, u) in values.items()}


SUMMARY = Case(st({"x_status": "warning"}), {"key_values": {}, "status": "watch"},
               st({"x_status": "unknown"}))

CASES: dict[str, Case] = {
    "CardiovascularRespiratoryConnector": Case(
        st({"heart_rate": 72, "stroke_volume": 70, "map": 93},
           {"heart_rate": "/min", "stroke_volume": "mL", "map": "mm[Hg]"}),
        {"cardiac_output": 5.04, "heart_rate": 72.0, "mean_arterial_pressure": 93.0},
        st({"heart_rate": 400, "stroke_volume": 70, "map": 93})),
    "EndocrineBehaviouralConnector": Case(
        st({"glucose": 9.0}, {"glucose": "mmol/L"}, obs(time_in_range_24h=(68, "%")),
           {"cortisol_z": 1.2}),
        {"glucose": 9.0, "time_in_range_24h": 68.0, "stress_index": 0.7},
        st({"glucose": 50.0}, {"glucose": "mmol/L"}, obs(time_in_range_24h=(68, "%")))),
    "IndividualToPopulationConnector": Case(
        st({}, fields=obs(weight=(78, "kg"), height=(163, "cm")),
           context={"age_years": 47, "sex": "female", "condition_codes": ["44054006"],
                    "address": {"street": "12 Example Rd", "state": "Lagos"}}),
        {"age_band": "45-49", "sex": "female", "state": "Lagos", "conditions": ["44054006"],
         "bmi": 29.4},
        st({}, fields=obs(weight=(1, "kg"), height=(163, "cm")),
           context={"age_years": 47, "sex": "female", "address": {"state": "Lagos"}})),
    "ClinicalFindingWriteBackConnector": Case(
        {"resourceType": "Observation", "status": "final", "author_role": "medical_officer",
         "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5",
                              "display": "Body temperature"}]},
         "recorded_at": "2026-10-11T08:00:00Z", "signed_by": "mo-1",
         "valueQuantity": {"value": 38.9, "unit": "Cel"}},
        {"resource_type": "Observation", "code": "8310-5", "system": "http://loinc.org",
         "display": "Body temperature", "status": "final", "author_role": "medical_officer",
         "recorded_at": "2026-10-11T08:00:00Z", "value": 38.9, "unit": "Cel"},
        {"resourceType": "Observation", "author_role": "medical_officer",
         "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5"}]},
         "recorded_at": "2026-10-11T08:00:00Z"}),
    "DeteriorationEventConnector": Case(
        st({}, context={"news2": 7, "risk": 0.42, "horizon_h": 12, "drivers": ["spo2"],
                        "output_id": "out-1"}),
        {"news2": 7, "risk": 0.42, "horizon_h": 12.0, "drivers": ["spo2"],
         "source_output_id": "out-1"},
        st({}, context={"news2": 25, "risk": 0.42, "horizon_h": 12, "drivers": [],
                        "output_id": "out-1"})),
    "RenalHepatobiliaryConnector": Case(
        st({"egfr": 88}, {"egfr": "mL/min/{1.73_m2}"}), {"egfr": 88.0},
        st({"egfr": 500}, {"egfr": "mL/min/{1.73_m2}"})),
    "InfectionHaemodynamicsConnector": Case(
        st({"inflammation_index": 0.3}, {"inflammation_index": "1"},
           obs(temperature=(38.9, "Cel")), {"conditions": ["cond.malaria_falciparum"]}),
        {"core_temp": 38.9, "inflammation_index": 0.3, "sepsis_flag": False},
        st({"inflammation_index": 0.3}, {"inflammation_index": "1"},
           obs(temperature=(50.0, "Cel")), {"conditions": []})),
    "InfectionNeuroConnector": Case(
        st({"inflammation_index": 0.6}, {"inflammation_index": "1"},
           obs(temperature=(39.4, "Cel")), {"conditions": ["cond.sepsis"]}),
        {"core_temp": 39.4, "inflammation_index": 0.6, "sepsis_flag": True},
        st({"inflammation_index": 1.5}, {"inflammation_index": "1"},
           obs(temperature=(39.4, "Cel")), {"conditions": []})),
    "HaemolysisConnector": Case(
        st({"parasitaemia": 2.5}, {"parasitaemia": "%"},
           context={"conditions": ["cond.malaria_falciparum"]}),
        {"parasitaemia": 2.5, "species": "Plasmodium falciparum"},
        st({"parasitaemia": 80.0}, {"parasitaemia": "%"},
           context={"parasite_species": "Plasmodium falciparum"})),
    "OxygenCarriageConnector": Case(
        st({"hb": 11.2, "platelets": 180}, {"hb": "g/dL", "platelets": "10*3/uL"}),
        {"hb": 11.2, "platelets": 180.0},
        st({"hb": 40.0, "platelets": 180}, {"hb": "g/dL", "platelets": "10*3/uL"})),
    "GlucoseRenalConnector": Case(
        st({"glucose": 7.8}, {"glucose": "mmol/L"}, obs(hba1c=(7.1, "%"))),
        {"glucose": 7.8, "hba1c": 7.1},
        st({"glucose": 0.5}, {"glucose": "mmol/L"})),
    "HepaticClearanceConnector": Case(
        st({"clearance_factor": 0.9}, {"clearance_factor": "1"},
           obs(alt=(40, "U/L"), bilirubin=(17, "umol/L"))),
        {"alt": 40.0, "bilirubin": 17.0, "clearance_factor": 0.9},
        st({"clearance_factor": 3.0}, {"clearance_factor": "1"},
           obs(alt=(40, "U/L"), bilirubin=(17, "umol/L")))),
    "RenalClearanceConnector": Case(
        st({}, fields=obs(egfr=(61, "mL/min/{1.73_m2}"))), {"egfr": 61.0},
        st({}, fields=obs(egfr=(0.2, "mL/min/{1.73_m2}")))),
    "NeuroEndocrineConnector": Case(
        st({"stress_drive": 0.4, "circadian_phase": 14.5},
           {"stress_drive": "1", "circadian_phase": "h"}),
        {"stress_drive": 0.4, "circadian_phase": 14.5},
        st({"stress_drive": 0.4, "circadian_phase": 30.0},
           {"stress_drive": "1", "circadian_phase": "h"})),
    "EndocrineReproductiveConnector": Case(
        st({}, fields=obs(oestradiol=(300, "pmol/L"))), {"oestradiol": 300.0},
        st({}, fields=obs(oestradiol=(-5, "pmol/L")))),
    "MusculoskeletalBehaviouralConnector": Case(
        st({}, fields=obs(gait_speed=(1.1, "m/s"), fall_risk=(0.2, "1"))),
        {"gait_speed": 1.1, "fall_risk": 0.2},
        st({}, fields=obs(gait_speed=(5.0, "m/s"), fall_risk=(0.2, "1")))),
    "IntegumentaryThermoConnector": Case(
        st({"skin_temp": 33.5, "sweat_rate": 40.0, "heat_index": 31.0},
           {"skin_temp": "Cel", "sweat_rate": "g/(m2.h)", "heat_index": "Cel"},
           obs(sweat_rate=(0.3, "1"))),
        {"skin_temp": 33.5, "sweat_rate": 0.3, "heat_index": 31.0},
        st({"skin_temp": 50.0, "heat_index": 31.0}, {"skin_temp": "Cel", "heat_index": "Cel"},
           obs(sweat_rate=(0.3, "1")))),
    "SensoryBehaviouralConnector": Case(
        st({}, fields=obs(visual_acuity_logmar=(0.3, "1"), hearing_threshold=(25, "dB"))),
        {"visual_acuity_logmar": 0.3, "hearing_threshold": 25.0},
        st({}, fields=obs(hearing_threshold=(150, "dB")))),
    "DigestiveEndocrineConnector": Case(
        st({"absorption_rate": 2.0, "weight": 70.0, "oral_intake_ok": 1.0},
           {"absorption_rate": "mg/kg/min", "weight": "kg", "oral_intake_ok": "1"}),
        {"carb_appearance": 0.7771, "oral_intake_ok": True},
        st({"absorption_rate": 200.0, "weight": 70.0, "oral_intake_ok": 1.0},
           {"absorption_rate": "mg/kg/min", "weight": "kg", "oral_intake_ok": "1"})),
    "RespiratoryRenalConnector": Case(
        st({"paco2": 40.0}, {"paco2": "mm[Hg]"}, context={"ph": 7.4}),
        {"paco2": 5.332895496600001, "ph": 7.4},
        st({"paco2": 40.0}, {"paco2": "mm[Hg]"}, context={"ph": 8.0})),
    "ContextToBehaviourConnector": Case(
        st({}, fields=obs(household_support=(0.8, "1"), distance_to_facility=(12, "km"),
                          food_security=(0.6, "1")), context={"bednet_use": True}),
        {"household_support": 0.8, "distance_km": 12.0, "bednet_use": True,
         "food_security": 0.6},
        st({}, fields=obs(household_support=(0.8, "1"), distance_to_facility=(900, "km"),
                          food_security=(0.6, "1")), context={"bednet_use": True})),
    "ExposomeConnector": Case(
        st({}, fields=obs(pm25=(35, "ug/m3"), ambient_temp=(31, "Cel"), humidity=(70, "%"))),
        {"pm25": 35.0, "temp_c": 31.0, "humidity": 70.0},
        st({}, fields=obs(pm25=(35, "ug/m3"), humidity=(120, "%")))),
    "PriorConnector": Case(
        {"condition": "cond.malaria_falciparum", "prevalence": 0.034, "age_band": "45-49",
         "season": "rainy", "region": "Lagos"},
        {"condition": "cond.malaria_falciparum", "prevalence": 0.034, "age_band": "45-49",
         "season": "rainy", "region": "Lagos"},
        {"condition": "cond.malaria_falciparum", "prevalence": 1.5, "age_band": "45-49",
         "season": "rainy", "region": "Lagos"}),
    "NormsConnector": Case(
        {"field": "hb", "p05": 11, "p50": 13.5, "p95": 16.0},
        {"field": "hb", "p05": 11.0, "p50": 13.5, "p95": 16.0},
        {"field": "hb", "p05": 11, "p50": "high", "p95": 16.0}),
    "BehaviourToSocialConnector": Case(
        st({}, fields=obs(adherence=(0.85, "1")), context={"needs_carer": False}),
        {"needs_carer": False, "adherence": 0.85},
        st({}, fields=obs(adherence=(2.0, "1")), context={"needs_carer": False})),
    "AHDTEventToAPDTConnector": Case(
        {"kind": "critical_reading", "code": "2160-0", "value": 450.0, "output_id": "out-2"},
        {"kind": "critical_reading", "code": "2160-0", "value": 450.0, "output_id": "out-2"},
        {"kind": "gossip", "code": "2160-0"}),
    "ReferralConnector": Case(
        {"bundle_ref": "bundles/ref-1.json", "reason": "Suspected severe malaria",
         "urgency": "urgent"},
        {"bundle_ref": "bundles/ref-1.json", "reason": "Suspected severe malaria",
         "urgency": "urgent"},
        {"bundle_ref": "bundles/ref-1.json", "reason": "x", "urgency": "whenever"}),
    "RegistryContributionConnector": Case(
        {"condition": "cond.malaria_falciparum", "age_years": 47, "sex": "female",
         "address": {"street": "12 Example Rd", "state": "Lagos"}, "outcome": "recovered",
         "name": "Never leaves the APDT"},
        {"condition": "cond.malaria_falciparum", "age_band": "45-49", "sex": "female",
         "state": "Lagos", "outcome": "recovered"},
        {"condition": "cond.malaria_falciparum", "age_years": 47, "sex": "female",
         "state": "Lagos"}),
    "SystemToWholeBodyConnector": SUMMARY,
}

REPLIES: dict[str, Case] = {
    "CardiovascularRespiratoryConnector": Case(
        st({"spo2": 97, "pao2": 95, "paco2": 40},
           {"spo2": "%", "pao2": "mm[Hg]", "paco2": "mm[Hg]"},
           obs(respiratory_rate=(14, "/min"))),
        {"spo2": 97.0, "pao2": 95.0, "paco2": 40.0, "respiratory_rate": 14.0},
        st({"spo2": 40}, {"spo2": "%"}, obs(respiratory_rate=(14, "/min")))),
    "EndocrineBehaviouralConnector": Case(
        st({}, fields=obs(active_minutes=(35, "min"), sleep_duration=(6.2, "h"),
                          adherence=(0.9, "1"))),
        {"active_minutes_24h": 35.0, "sleep_hours": 6.2, "medication_adherence": 0.9},
        st({}, fields=obs(active_minutes=(2000, "min"), sleep_duration=(6.2, "h")))),
    "EndocrineReproductiveConnector": Case(
        st({}, fields=obs(gestation_weeks=(20, "wk")), context={"conditions": ["cond.pregnancy"]}),
        {"pregnant": True, "gestation_weeks": 20.0},
        st({}, fields=obs(gestation_weeks=(50, "wk")), context={"conditions": []})),
    "MusculoskeletalBehaviouralConnector": Case(
        st({}, context={"steps_target": 8000}), {"steps_target": 8000.0},
        st({}, context={"steps_target": 90000})),
}

REFERRAL = ("ReferralConnector", K.PATIENT, K.PATIENT)
ALL_PAIRS = [*expanded_pairs()]


def pair_id(pair):
    name, source, target = pair
    return f"{name}:{source.value}->{target.value}"
