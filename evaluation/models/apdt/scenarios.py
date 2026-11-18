"""The six demo persona scenarios as model inputs (design 06, 6.4.2).

The persona facts (`synth/personas/facts.yaml`) fix who each patient is and what they take.
The presenting findings, tests and body weights below complete a runnable presentation of the
scenario named in `atra.personas`. Weights other than G.H.'s are assumptions of the scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apdt.models.context import Observations, Patient
from atra.personas import BY_KEY


@dataclass(frozen=True)
class Scenario:
    key: str
    patient: Patient
    observations: Observations
    expected_top: str
    expected_first_option: str
    expected_issues: tuple[str, ...] = ()
    notes: str = ""
    extra_top: tuple[str, ...] = field(default_factory=tuple)


def _p(key: str, **kw: Any) -> Patient:
    persona = BY_KEY[key]
    return Patient(age_years=persona.age_years, sex=persona.sex,
                   tenant_id=persona.tenant_id, **kw)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "ao", _p("ao", weight_kg=62.0),
        Observations(findings={"find.fever_history": True},
                     tests={"test.malaria_rdt_hrp2": True},
                     measurements={"temperature": 38.6}),
        "cond.malaria_falciparum", "tx.malaria.uncomplicated.artemether_lumefantrine",
        notes="Uncomplicated malaria; the worked example."),
    Scenario(
        "bm", _p("bm", weight_kg=25.0),
        Observations(findings={"find.impaired_consciousness": True, "find.prostration": True},
                     tests={"test.malaria_rdt_hrp2": True},
                     measurements={"temperature": 39.2, "glucose": 2.1}, avpu="V"),
        "cond.malaria_falciparum", "tx.malaria.severe.artesunate",
        extra_top=("cond.hypoglycaemia",),
        notes="Severe malaria with falling consciousness and hypoglycaemia."),
    Scenario(
        "cn", _p("cn", weight_kg=65.0, pregnancy="t2"),
        Observations(findings={"find.flank_pain": True, "find.dysuria": True,
                               "find.costovertebral_tenderness": True, "find.pyuria": True,
                               "find.vomiting": True},
                     measurements={"temperature": 38.8}),
        "cond.pyelonephritis", "tx.pyelonephritis.pregnancy.ceftriaxone",
        notes="Pyelonephritis at 22 weeks of pregnancy."),
    Scenario(
        "de", _p("de", weight_kg=82.0, conditions=("cond.hypertension", "cond.diabetes_type2",
                                                    "cond.ckd"),
                 medications=("amlodipine", "lisinopril", "metformin")),
        Observations(measurements={"sbp": 162.0, "dbp": 98.0, "creatinine": 180.0}),
        "cond.hypertension", "tx.hypertension.hearts_ccb_first",
        notes="Hypertension, type 2 diabetes and CKD stage 3."),
    Scenario(
        "ef", _p("ef", weight_kg=52.0, hb_genotype="HbSS",
                 medications=("morphine", "hydroxycarbamide")),
        Observations(findings={"find.bone_pain": True}, measurements={"hb": 7.1}),
        "cond.scd_crisis", "tx.scd_crisis.painful_crisis",
        notes="Vaso-occlusive crisis in HbSS."),
    Scenario(
        "gh", _p("gh", weight_kg=58.0, conditions=("cond.hiv",),
                 medications=("dolutegravir", "tenofovir disoproxil", "lamivudine")),
        Observations(findings={"find.cough": True, "find.weight_loss": True,
                               "find.night_sweats": True}),
        "cond.tb_pulmonary", "tx.tb.ds.six_month_hrze",
        expected_issues=("ix.dolutegravir.rifampicin",),
        notes="TB work-up on ART; rifampicin with dolutegravir."),
)

BY_SCENARIO = {s.key: s for s in SCENARIOS}
