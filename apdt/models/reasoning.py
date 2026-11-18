"""The core reasoning chain: differential, tests, interpretation, treatment options and
safety checks for one patient (design 05, 5.5). WP24 calls this through the APDT agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from apdt.models.care.early_warning import EarlyWarning, score
from apdt.models.context import Observations, Patient
from apdt.models.diagnosis import symbolic
from apdt.models.diagnosis.bn import Differential, DifferentialModel
from apdt.models.diagnosis.interpret import Interpretation, derive_findings, interpret
from apdt.models.diagnosis.tests_select import MindChange, Ranked, rank_tests
from apdt.models.treatment.options import OptionSet, options_for
from apdt.models.treatment.renal import egfr_ckd_epi
from apdt.models.treatment.safety import Issue

VITAL_FIELDS = {"respiratory_rate": "respiration_rate", "spo2": "spo2",
                "sbp": "systolic_bp", "heart_rate": "pulse", "temperature": "temperature"}


@dataclass
class Assessment:
    patient: Patient
    observations: Observations
    differential: Differential
    tests: list[Ranked]
    mind_changes: list[MindChange]
    interpretations: list[Interpretation]
    options: dict[str, OptionSet]
    early_warning: EarlyWarning | None = None
    issues: list[Issue] = field(default_factory=list)
    listing: symbolic.Listing | None = None

    def first_option(self) -> Any:
        top = self.listing.listed[0] if self.listing and self.listing.listed else None
        if top is None or top.condition not in self.options:
            return None
        eligible = self.options[top.condition].eligible
        return eligible[0] if eligible else None


class ClinicalReasoner:
    def __init__(self, model: DifferentialModel | None = None) -> None:
        self.model = model or DifferentialModel()

    def prepare(self, patient: Patient, obs: Observations) -> tuple[Patient, Observations]:
        """Add the findings that the measurements imply and the eGFR from creatinine."""
        derived = derive_findings(obs.measurements, patient)
        findings = {**derived, **obs.findings}
        if patient.egfr is None and "creatinine" in obs.measurements:
            patient = replace(patient, egfr=egfr_ckd_epi(
                obs.measurements["creatinine"], patient.age_years, patient.sex == "female"))
        return patient, replace(obs, findings=findings)

    def assess(self, patient: Patient, obs: Observations, *, hdt_id: str | None = None,
               min_probability: float = 0.5, with_tests: bool = True) -> Assessment:
        patient, obs = self.prepare(patient, obs)
        diff = self.model.differential(patient, obs)
        listing = symbolic.apply(diff, patient, obs)
        tests: list[Ranked] = []
        changes: list[MindChange] = []
        if with_tests:
            tests, changes = rank_tests(self.model, patient, obs)
        interps = [i for f, v in obs.measurements.items()
                   if (i := interpret(f, v, patient)) is not None]
        options: dict[str, OptionSet] = {}
        for rank, cand in enumerate(listing.listed):
            if rank == 0 or cand.probability >= min_probability:
                options[cand.condition] = options_for(cand.condition, patient, obs, hdt_id)
        vitals = {name: obs.measurements.get(f) for f, name in VITAL_FIELDS.items()}
        ews = score({**vitals, "consciousness": obs.avpu, "on_oxygen": False},
                    patient.age_years)
        issues = [i for s in options.values() for o in s.eligible[:1] for i in o.issues]
        return Assessment(patient, obs, diff, tests, changes, interps, options, ews, issues,
                          listing)
