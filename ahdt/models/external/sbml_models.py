"""Layer 4 models built on BioModels SBML files (design 04, 4.5.3; design 08, WP14c step 3).

| Model | BioModels | Curation | Twin |
|---|---|---|---|
| Beta-cell mass, insulin and glucose (Topp 2000) | BIOMD0000000341 | curated | Endocrine |
| Hepatocyte glucose metabolism (Bulik 2016, rat) | BIOMD0000000633 | curated | Hepatobiliary |
| Menstrual cycle hormones (Roeblitz 2013) | BIOMD0000000494 | curated | Reproductive, Endocrine |
| Cortisol metabolism and excretion (Kraan 1992) | BIOMD0000000916 | curated | Endocrine |
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, ClassVar

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import ModelSpec, Params, Port
from ahdt.models.external.sbml import SbmlModel, runner
from atra import contracts as c
from atra.connectors import DTKind

DAY_S = 86400.0
HOUR_S = 3600.0


class BetaCellMassModel(SbmlModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.beta_cell_mass_dynamics",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Beta-cell mass adaptation to glucose over months and its failure in diabetes",
        instances=("UBERON:0001264",),
        inputs=(Port("insulin_sensitivity", "mL/uU/d", "input:scenario"),),
        outputs=(Port("beta_cell_mass", "mg"), Port("islet_glucose", "mg/dL"),
                 Port("islet_insulin", "uU/mL")),
        explainers=("sensitivity.local",),
        fidelity_note="The pinned SBML carries no unit definitions; units follow the "
                      "published model: mg/dL, uU/mL, mg and days.")
    params_stem = "beta_cell"
    source_id = "biomodels-341"
    variables = ("G", "I", "B")
    sbml_params = {name: name for name in ("si", "Eg0", "R0", "sigma", "alpha", "k", "d0", "r1",
                                           "r2")}
    sbml_inputs = {"insulin_sensitivity": "si"}
    time_scale_s = DAY_S

    def fixed_point(self, p: Params) -> tuple[float, float, float]:
        """The stable physiological fixed point of the three equations.

        Beta-cell mass is constant where r1 G - r2 G^2 = d0; the smaller root is stable.
        Glucose and insulin are then constant at the values that follow from their equations.
        """
        root = math.sqrt(p["r1"] ** 2 - 4 * p["r2"] * p["d0"])
        g = (p["r1"] - root) / (2 * p["r2"])
        i = (p["R0"] / g - p["Eg0"]) / p["si"]
        b = i * p["k"] * (p["alpha"] + g * g) / (p["sigma"] * g * g)
        return g, i, b

    def reference_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        q = dict(p)
        if "insulin_sensitivity" in inputs:
            q["si"] = float(inputs["insulin_sensitivity"])
        g, i, b = self.fixed_point(q)
        return {"G": g, "I": i, "B": b}

    def read(self, rr: Any) -> dict[str, Any]:
        return {"beta_cell_mass": float(rr["B"]), "islet_glucose": float(rr["G"]),
                "islet_insulin": float(rr["I"])}


class HepatocyteGlucoseModel(SbmlModel):
    spec = ModelSpec(
        model_id="ahdt.hepatobiliary.hepatocyte_metabolism_and_detoxification",
        twin=DTKind.HEPATOBILIARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Net hepatic glucose release or uptake and glycogen at a given blood glucose",
        instances=("UBERON:0002107",),
        inputs=(Port("blood_glucose", "mmol/L", "input:scenario"),),
        outputs=(Port("hepatic_glucose_output", "mmol/L/h"), Port("glycogenolysis", "mmol/L/h"),
                 Port("gluconeogenesis", "mmol/L/h"), Port("hepatocyte_glycogen", "mmol/L"),
                 Port("insulin_signal", "mmol/L"), Port("glucagon_signal", "mmol/L")),
        explainers=("sensitivity.local",),
        fidelity_note="Rat hepatocyte kinetics; rates per litre of cell volume. Human liver "
                      "volume scaling is not applied. Detoxification is carried by "
                      "ahdt.hepatobiliary.liver_drug_clearance_capacity.")
    params_stem = "hepatocyte"
    source_id = "biomodels-633"
    variables = ()
    sbml_params = {"reference_blood_glucose": "glc_ext"}
    sbml_inputs = {"blood_glucose": "glc_ext"}
    time_scale_s = HOUR_S
    steady = True

    @property
    def state_names(self) -> tuple[str, ...]:
        return self.variable_ids()

    def variable_ids(self) -> tuple[str, ...]:
        return tuple(runner(self.source_id).model.getFloatingSpeciesIds())

    def selections(self) -> list[str]:
        return [f"[{v}]" for v in self.variable_ids()]

    def current_state(self, rr: Any) -> dict[str, float]:
        return {v: float(rr[f"[{v}]"]) for v in self.variable_ids()}

    def apply_state(self, rr: Any, state: Mapping[str, Any]) -> None:
        for sid in self.variable_ids():
            if sid in state:
                rr[sid] = float(state[sid])

    def rates(self, rr: Any) -> dict[str, float]:
        return dict(zip(rr.model.getReactionIds(), (float(x) for x in rr.model.getReactionRates()),
                        strict=True))

    def read(self, rr: Any) -> dict[str, Any]:
        v = self.rates(rr)
        return {"hepatic_glucose_output": -v["GLUT2"], "glycogenolysis": v["GP"] - v["GS"],
                "gluconeogenesis": v["PEPCK"] + v["PEPCK_mito"],
                "hepatocyte_glycogen": float(rr["[glyglc]"]),
                "insulin_signal": float(rr["ins"]), "glucagon_signal": float(rr["glucagon"])}


class RoeblitzModel(SbmlModel):
    """Common part of the two views of the Roeblitz menstrual cycle model."""

    source_id = "biomodels-494"
    variables = ()
    sbml_params = {"agonist_dose": "p272", "antagonist_dose": "p472"}
    time_scale_s = DAY_S
    cycle_length_d: ClassVar[float] = 28.0

    def variable_ids(self) -> tuple[str, ...]:
        return tuple(runner(self.source_id).model.getFloatingSpeciesIds())

    @property
    def state_names(self) -> tuple[str, ...]:
        return self.variable_ids()

    def selections(self) -> list[str]:
        return [f"[{v}]" for v in self.variable_ids()]

    def current_state(self, rr: Any) -> dict[str, float]:
        return {v: float(rr[f"[{v}]"]) for v in self.variable_ids()}

    def apply_state(self, rr: Any, state: Mapping[str, Any]) -> None:
        for sid in self.variable_ids():
            if sid in state:
                rr[sid] = float(state[sid])

    def hormones(self, rr: Any) -> dict[str, float]:
        return {"lh": float(rr["[LH_bld]"]), "fsh": float(rr["[FSH_bld]"]),
                "oestradiol": float(rr["[E2]"]), "progesterone": float(rr["[P4]"]),
                "inhibin_a": float(rr["[InhA]"]), "inhibin_b": float(rr["[InhB]"])}


class GonadalHormonesModel(RoeblitzModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.gonadal_hormones",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Female gonadal and pituitary hormone profile over the menstrual cycle",
        instances=("UBERON:0000991",),
        outputs=(Port("lh", "mIU/mL"), Port("fsh", "mIU/mL"), Port("oestradiol", "pg/mL"),
                 Port("progesterone", "ng/mL"), Port("inhibin_a", "IU/mL"),
                 Port("inhibin_b", "pg/mL")),
        explainers=("sensitivity.local",),
        fidelity_note="Female cycle only. A testosterone model for males needs a kb reference "
                      "range that the kb does not hold.")
    params_stem = "gonadal"

    def read(self, rr: Any) -> dict[str, Any]:
        return self.hormones(rr)

    def events(self, t_model: Array, series: Mapping[str, Array]) -> list[c.TrajectoryEvent]:
        return lh_peaks(t_model, series.get("lh"))


class MenstrualCycleModel(RoeblitzModel):
    spec = ModelSpec(
        model_id="ahdt.reproductive.menstrual_and_fertility_cycle",
        twin=DTKind.REPRODUCTIVE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Cycle phase, ovulation timing and endometrial phase from the hormone cycle",
        instances=("UBERON:0000991", "UBERON:0000995"),
        outputs=(Port("cycle_phase", "{phase}"), Port("endometrial_phase", "{phase}"),
                 Port("lh", "mIU/mL"), Port("fsh", "mIU/mL"), Port("oestradiol", "pg/mL"),
                 Port("progesterone", "ng/mL")),
        explainers=("sensitivity.local",),
        fidelity_note="Phase codes: 1 follicular, 2 ovulatory surge, 3 luteal. The endometrial "
                      "phase is 1 proliferative or 2 secretory.")
    params_stem = "menstrual"

    def read(self, rr: Any) -> dict[str, Any]:
        h = self.hormones(rr)
        p = self.base_params()
        luteal = h["progesterone"] > p["luteal_p4_threshold"]
        surge = h["lh"] > p["lh_surge_threshold"]
        phase = 3 if luteal else 2 if surge else 1
        return {"cycle_phase": float(phase), "endometrial_phase": 2.0 if luteal else 1.0,
                "lh": h["lh"], "fsh": h["fsh"], "oestradiol": h["oestradiol"],
                "progesterone": h["progesterone"]}

    def events(self, t_model: Array, series: Mapping[str, Array]) -> list[c.TrajectoryEvent]:
        return lh_peaks(t_model, series.get("lh"))


def lh_peaks(t_model: Array, lh: Array | None) -> list[c.TrajectoryEvent]:
    """Ovulatory LH surges: local maxima above 10 mIU/mL."""
    if lh is None or len(lh) < 3:
        return []
    mid = lh[1:-1]
    hits = np.nonzero((mid > lh[:-2]) & (mid >= lh[2:]) & (mid > 10.0))[0] + 1
    return [c.TrajectoryEvent(t=float(t_model[i] * DAY_S), kind="lh_surge",
                              detail={"lh_mIU_per_mL": float(lh[i])}) for i in hits]


class CortisolDispositionModel(SbmlModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.cortisol_metabolism_and_excretion",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Fate of a cortisol dose: circulation, metabolism, urine and bile",
        outputs=(Port("cortisol_circulating_fraction", "1"),
                 Port("cortisol_tissue_fraction", "1"), Port("cortisol_biliary_fraction", "1"),
                 Port("cortisol_urinary_fraction", "1"),
                 Port("cortisol_nonurinary_fraction", "1")),
        explainers=("sensitivity.local",),
        fidelity_note="Tracer kinetics in fractions of the dose. The model clears the circulation "
                      "with a half-life of 37.5 min; the source reports 30 min for the label.")
    params_stem = "cortisol_kinetics"
    source_id = "biomodels-916"
    sbml_params = {name: name for name in ("K1", "K2", "K3", "K4", "K5")}
    time_scale_s = DAY_S
    _ids: ClassVar[tuple[str, ...]] = (
        "The_FOD_in_the_circulation__X1", "The_FOD_in_the_metabolizing_tissues__X4",
        "The_FOD_in_the_gallbladder___intestinal_lumen__X5",
        "The_cumulative_FOD_excreted_in_the_urine__X2",
        "The_cumulative_FOD_excreted_in_the_non_urinary_pool__X3")
    variables = _ids

    def read(self, rr: Any) -> dict[str, Any]:
        x1, x4, x5, x2, x3 = (float(rr[f"[{v}]"]) for v in self._ids)
        return {"cortisol_circulating_fraction": x1, "cortisol_tissue_fraction": x4,
                "cortisol_biliary_fraction": x5, "cortisol_urinary_fraction": x2,
                "cortisol_nonurinary_fraction": x3}


SBML_MODELS: tuple[type[SbmlModel], ...] = (
    BetaCellMassModel, HepatocyteGlucoseModel, GonadalHormonesModel, MenstrualCycleModel,
    CortisolDispositionModel)

