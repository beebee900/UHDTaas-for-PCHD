"""Reference checks of the WP14a models (design 08, WP14a step 7).

Each check reproduces a published value, a published worked example or an exact property
of the published equations, and reports one metric with its tolerance. The registry
records the metric as the model's validation, and the unit tests assert that every check
passes.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

from ahdt.models.base import Layer4Base
from atra import contracts as c


@dataclass(frozen=True)
class Check:
    dataset: str
    metric: str
    value: float
    tolerance: float

    @property
    def passed(self) -> bool:
        return math.isfinite(self.value) and abs(self.value) <= self.tolerance

    def validation(self) -> c.Validation:
        return c.Validation(dataset=self.dataset, metric=self.metric, value=self.value,
                            date=date.today().isoformat())


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b)


# Frequently sampled IV glucose tolerance test of a normal subject: Pacini and Bergman
# (1986), as tabulated in Knott's MLAB application note.
FSIGT_T = (0, 2, 4, 6, 8, 10, 12, 14, 16, 19, 22, 27, 32, 42, 52, 62, 72, 82, 92, 102, 122,
           142, 162, 182)
FSIGT_G = (92, 350, 287, 251, 240, 216, 211, 205, 196, 192, 172, 163, 142, 124, 105, 92, 84,
           77, 82, 81, 82, 82, 85, 90)
FSIGT_I = (11, 26, 130, 85, 51, 49, 45, 41, 35, 30, 30, 27, 30, 22, 15, 15, 11, 10, 8, 11, 7,
           8, 8, 7)


def minimal_model(m: Layer4Base) -> Check:
    fit = m.fit_glucose(FSIGT_T, FSIGT_G, FSIGT_I, g0=287)  # type: ignore[attr-defined]
    published = (0.03139866193, 0.01877500745, 9.491576611e-06)
    err = max(_rel(fit.p1, published[0]), _rel(fit.p2, published[1]),
              _rel(fit.p3, published[2]))
    return Check("Pacini and Bergman 1986 FSIGT (published least-squares fit)",
                 "max_relative_error_p1_p2_p3", err, 0.10)


def _appeared(m: Layer4Base, series: str, hours: float = 12) -> float:
    record = m.new_record("hdt-000000000000", m.spec.instances[0], m.spec.twin)
    meal = c.Scenario(kind="diet", diet={"meals": [{"t_s": 0, "carbs_g": 78}]})
    tr = asyncio.run(m.simulate(record, meal, hours * 3600, 60))
    ra = np.array(tr.series[series])
    return float(np.trapezoid(ra, np.array(tr.t) / 60.0) * m.base_params()["BW"] / 1000.0)


def glucose_insulin(m: Layer4Base) -> Check:
    f = m.base_params()["f"]
    return Check("Dalla Man 2007 meal of 78 g; appearance equals f times the dose",
                 "relative_error_absorbed_glucose", _rel(_appeared(m, "Ra"), f * 78), 0.02)


def absorption(m: Layer4Base) -> Check:
    f = m.base_params()["f"]
    return Check("Dalla Man 2007 meal of 78 g; appearance equals f times the dose",
                 "relative_error_absorbed_glucose",
                 _rel(_appeared(m, "absorption_rate"), f * 78), 0.02)


def heart(m: Layer4Base) -> Check:
    p = m.parameters()
    _, end = m.beat(p, m.initial_state(p, {}), {})  # type: ignore[attr-defined]
    start = sum(m.initial_state(p, {})[k] for k in ("V_lv", "V_rv", "V_pa", "V_pu", "V_ao",
                                                    "V_vc"))
    total = sum(end[k] for k in ("V_lv", "V_rv", "V_pa", "V_pu", "V_ao", "V_vc"))
    return Check("Smith 2004 reference parameter set; closed-loop volume conservation",
                 "stressed_volume_drift_ml", total - start, 1e-3)


def baroreflex(m: Layer4Base) -> Check:
    from ahdt.models.cardiovascular.baroreflex import afferent

    p = m.parameters()
    return Check("Ursino 1998 afferent sigmoid; firing at P_n is the midpoint",
                 "midpoint_error_hz",
                 afferent(p["P_n"], p) - (p["f_ab_min"] + p["f_ab_max"]) / 2, 1e-9)


def vasculature(m: Layer4Base) -> Check:
    p = m.parameters()
    values = m.evaluate(p, m.initial_state(p, {}), {})
    expected = p["co_ref"] * 1000 * p["share_cerebral"]
    return Check("Bed flows at the reference pressure equal their cardiac-output shares",
                 "relative_error_cerebral_flow", _rel(values["cerebral_flow"], expected), 1e-6)


def gas_exchange(m: Layer4Base) -> Check:
    from ahdt.models.respiratory.gas_exchange import saturation

    return Check("Severinghaus 1979 standard curve; P50 of 26.8 mmHg",
                 "saturation_error_at_p50", saturation(26.8) - 0.5, 0.005)


def ventilation(m: Layer4Base) -> Check:
    p = m.parameters()
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-vc", anatomy="atra:vc",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state=m.initial_state(p, {}))
    base = asyncio.run(m.simulate(record, c.Scenario(kind="environment"), 900, 300))
    load = asyncio.run(m.simulate(record, c.Scenario(kind="environment",
                                                     environment={"vco2": 400}), 900, 300))
    return Check("Chemoreflex with doubled CO2 output; arterial PCO2 held",
                 "paco2_rise_mmhg", load.series["paco2"][-1] - base.series["paco2"][-1], 5.0)


def neuron(m: Layer4Base) -> Check:
    p = m.parameters()
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-neuron", anatomy="atra:neuron",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state=m.initial_state(p, {}))
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention",
                                                   intervention={"stimulus": 10}), 0.1, 1e-4))
    peak = max(tr.series["membrane_depolarisation"])
    return Check("Hodgkin and Huxley 1952 action potential of about 100 mV",
                 "peak_depolarisation_minus_100_mv", peak - 100.0, 15.0)


def sleep(m: Layer4Base) -> Check:
    fit = m.fit_schedule([23.0], [7.0])  # type: ignore[attr-defined]
    return Check("Two-process model fitted to a 23:00 to 07:00 sleep schedule",
                 "duration_error_h", fit["duration_error_h"], 0.25)


def hpa(m: Layer4Base) -> Check:
    p = m.parameters()
    y = np.array(list(m.initial_state(p, {}).values()))
    residual = max(abs(v) for v in m._scaled(y, p, 0.0, 1.0))  # type: ignore[attr-defined]
    return Check("Gupta 2007 scaled equations 9 to 12; normal steady state",
                 "steady_state_residual", residual, 1e-6)


def pineal(m: Layer4Base) -> Check:
    record = m.new_record("hdt-000000000000", "UBERON:0001905", m.spec.twin)
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="activity"), 48 * 3600, 600))
    mel = np.array(tr.series["melatonin"])
    hour = (np.array(tr.t) / 3600.0) % 24
    day = mel[(hour > 10) & (hour < 18) & (np.array(tr.t) > 24 * 3600)]
    return Check("Brown 1997 melatonin rhythm; daytime level relative to the peak",
                 "daytime_to_peak_ratio", float(day.max() / mel.max()), 0.05)


def hormone_kinetics(m: Layer4Base) -> Check:
    p = m.parameters()
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-hk", anatomy="atra:hk",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state={**m.initial_state(p, {}), "melatonin": 100.0})
    half = p["half_life_melatonin"] * 60
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), half, half))
    return Check("One-compartment decay over one published half-life",
                 "relative_error_half", _rel(tr.series["melatonin"][-1], 50.0), 1e-4)


def kidney(m: Layer4Base) -> Check:
    from ahdt.models.renal_urinary.kidney import ckd_epi_2021

    p = m.parameters()
    # 142 x (1.0 / 0.9) ** -1.200 x 0.9938 ** 50 for serum creatinine 1.0 mg/dL, male, 50 y.
    expected = 142 * (1.0 / 0.9) ** -1.2 * 0.9938 ** 50
    return Check("CKD-EPI 2021 equation; serum creatinine 1.0 mg/dL, male, 50 years",
                 "relative_error_egfr", _rel(ckd_epi_2021(88.4, 50, False, p), expected), 1e-9)


def acid_base(m: Layer4Base) -> Check:
    from ahdt.models.renal_urinary.acid_base import henderson_hasselbalch

    return Check("Henderson-Hasselbalch at HCO3 24 mmol/L and PaCO2 40 mmHg; pH 7.40",
                 "ph_error", henderson_hasselbalch(24, 40, m.parameters()) - 7.40, 0.015)


def liver(m: Layer4Base) -> Check:
    from ahdt.models.hepatobiliary.clearance import well_stirred

    q = m.parameters()["hepatic_blood_flow"]
    return Check("Well-stirred model: clearance tends to hepatic blood flow at high CL_int",
                 "relative_error_flow_limit", _rel(well_stirred(q, 1.0, 1e6), q), 1e-5)


def inflammation(m: Layer4Base) -> Check:
    p = m.parameters()
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-inf", anatomy="atra:inf",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state=m.initial_state(p, {"pathogen_inoculum": 1.0}))
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), 600 * 3600, 3600))
    return Check("Reynolds 2006 healthy outcome from a small inoculum",
                 "final_tissue_damage", tr.series["tissue_damage"][-1], 0.05)


def infection(m: Layer4Base) -> Check:
    p = m.parameters()
    out = m.run(p, {"merozoite_release": 0.01},  # type: ignore[attr-defined]
                np.arange(0, 21 * 86400 + 1, 86400))
    y = out["parasite_density"]
    simulated = (y[19] / y[17]) ** 0.5
    analytic = (p["mal_r"] * p["mal_beta"] * math.exp(-p["mal_alpha"] * p["mal_tau"])
                / (p["mal_beta"] + p["mal_delta"]))
    return Check("Hoshen 2000 delay model; multiplication per 48 h cycle",
                 "relative_error_cycle_multiplication", _rel(simulated ** 2, analytic), 0.05)


def erythropoiesis(m: Layer4Base) -> Check:
    record = m.new_record("hdt-000000000000", "UBERON:0000178", m.spec.twin)
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), 120 * 86400, 86400))
    return Check("Steady state at the person's baseline haemoglobin",
                 "hb_drift_g_dl", tr.series["hb"][-1] - tr.series["hb"][0], 1e-3)


def platelets(m: Layer4Base) -> Check:
    record = m.new_record("hdt-000000000000", "UBERON:0000178", m.spec.twin)
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), 60 * 86400, 86400))
    return Check("Steady state at the person's baseline platelet count",
                 "platelet_drift", tr.series["platelets"][-1] - tr.series["platelets"][0], 1e-3)


def bone(m: Layer4Base) -> Check:
    record = m.new_record("hdt-000000000000", "UBERON:0001434", m.spec.twin)
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), 1000 * 86400,
                                10 * 86400))
    return Check("Komarova 2003 single remodelling cycle; bone mass restored",
                 "bone_mass_change_pct", tr.series["bone_mass"][-1] - 100.0, 0.5)


def thermoregulation(m: Layer4Base) -> Check:
    record = m.new_record("hdt-000000000000", "UBERON:0002097", m.spec.twin)
    neutral = {"air_temperature": 25, "relative_humidity": 50, "met": 1.2, "clo": 0.5}
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="environment", environment=neutral),
                                3600, 600))
    return Check("Gagge 1986 two-node model in a neutral environment",
                 "core_temperature_shift_k", tr.series["core_temp"][-1] - 36.8, 0.2)


def heat_stress(m: Layer4Base) -> Check:
    from ahdt.models.integumentary.heat_stress import heat_index_f

    return Check("NWS heat index table: 90 degF at 60 % relative humidity reads 100 degF",
                 "heat_index_error_degf", heat_index_f(90, 60, m.parameters()) - 100.0, 0.6)


def wound(m: Layer4Base) -> Check:
    p = m.parameters()
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-wound", anatomy="atra:wound",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state=m.initial_state(p, {}))
    tr = asyncio.run(m.simulate(record, c.Scenario(kind="intervention"), 20 * 86400,
                                20 * 86400))
    h0, k, t = p["healed0"], p["k"], 20.0
    analytic = 1 / (1 + (1 - h0) / h0 * math.exp(-k * t))
    return Check("Logistic closure against its closed-form solution",
                 "healed_fraction_error", tr.series["healed_fraction"][-1] - analytic, 1e-4)


def nutrition(m: Layer4Base) -> Check:
    from ahdt.models.digestive.nutrition import resting_energy

    value = resting_energy(70, 175, 30, False, m.parameters())
    return Check("Mifflin-St Jeor: 10 x 70 + 6.25 x 175 - 5 x 30 + 5 kcal/d",
                 "ree_error_kcal", value - 1648.75, 1e-9)


def sensory(m: Layer4Base) -> Check:
    from ahdt.models.sensory.decline import SensoryDeclineModel, curve

    rng = np.random.default_rng(7)
    ages = rng.uniform(20, 90, 400)
    values = curve(ages, 5.0, 35.0, 0.02, 1.9) + rng.normal(0, 0.5, 400)
    fit = SensoryDeclineModel.fit("hearing", ages, values, [5, 30, 0.01, 2])
    return Check("Recovery of a known decline curve from a synthetic cohort",
                 "relative_error_onset", _rel(fit["hearing_onset"], 35.0), 0.1)


def early_warning(m: Layer4Base) -> Check:
    out = m.evaluate({}, {}, {"respiration_rate": 24, "spo2": 95, "systolic_bp": 105,
                              "pulse": 112, "temperature": 38.6, "consciousness": "alert"})
    return Check("NEWS2 chart: RR 24, SpO2 95 %, SBP 105, HR 112, 38.6 Cel, alert scores 7",
                 "score_error", float(out["news2"]) - 7.0, 0.0)


def pharmacogenomics(m: Layer4Base) -> Check:
    out = m.evaluate({}, {}, {"diplotypes": {"CYP2D6": "*1/*4", "CYP2C19": "*1/*17"}})
    expected = {"CYP2C19:Rapid Metabolizer", "CYP2D6:Intermediate Metabolizer"}
    return Check("CPIC phenotype tables: CYP2D6 *1/*4 and CYP2C19 *1/*17",
                 "phenotype_mismatches", float(len(expected ^ set(out["phenotypes"]))), 0.0)


def life_course(m: Layer4Base) -> Check:
    p = m.parameters()
    errors = [abs(m.evaluate(p, {}, {"age": a})["expected_frailty_index"] - q)
              for a, q in ((67, 0.11), (77, 0.15), (87, 0.20))]
    return Check("Mitnitski 2002 equation 1 worked values at 67, 77 and 87 years",
                 "max_abs_error", max(errors), 0.01)


def maternal_foetal(m: Layer4Base) -> Check:
    from ahdt.models.whole_body.maternal_foetal import hadlock_efw

    p = m.parameters()
    log10 = 1.326 + 0.0107 * 30 + 0.0438 * 30 + 0.158 * 6.5 - 0.00326 * 30 * 6.5
    return Check("Hadlock 1985 (LOINC 11746-5) at HC 30, AC 30, FL 6.5 cm",
                 "relative_error_efw", _rel(hadlock_efw(30, 30, 6.5, p), 10 ** log10), 1e-12)


def avatar(m: Layer4Base) -> Check:
    out = m.evaluate(m.parameters(), {}, {"height": 180, "weight": 80})
    return Check("Mosteller 1987: 180 cm and 80 kg give 2.0 m2", "bsa_error_m2",
                 out["bsa"] - 2.0, 1e-9)


def cardiac_electrophysiology(m: Layer4Base) -> Check:
    from ahdt.models.external.opencarp import TissueScenario, single_cell_apd90

    p = m.parameters()
    tissue = float(m.initial_state(p, {})["apd90"])
    cell = single_cell_apd90(p, TissueScenario())
    return Check("openCARP bench, same ten Tusscher-Panfilov cell paced at 1 Hz, last beat",
                 "relative_error_tissue_apd90", _rel(tissue, cell), 0.05)


def aorta(m: Layer4Base) -> Check:
    from ahdt.models.external.aorta import foot_to_foot_speed

    g = m.geometry(m.parameters())  # type: ignore[attr-defined]
    return Check("Moens-Korteweg wave speed of the finite-difference solution (Kissas 2020 "
                 "equations); foot-to-foot speed against the speed that sets the wall stiffness",
                 "relative_error_wave_speed", _rel(foot_to_foot_speed(g), g.c0), 0.10)


def _drift(m: Layer4Base, days: float) -> float:
    p = m.parameters()
    state = m.initial_state(p, {})
    final, _ = m.run(p, state, {}, np.array([0.0, days]))  # type: ignore[attr-defined]
    names = getattr(m, "state_names", None) or m.variables  # type: ignore[attr-defined]
    start = np.array([state[n] for n in names])
    return float(np.max(np.abs(final - start) / np.maximum(np.abs(start), 1e-9)))


def beta_cell(m: Layer4Base) -> Check:
    return Check("Topp 2000 equations; stable fixed point, relative drift over 10 days",
                 "max_relative_drift", _drift(m, 10.0), 1e-4)


def hepatocyte(m: Layer4Base) -> Check:
    return Check("Bulik 2016 reaction network; steady state, relative drift over 1 hour",
                 "max_relative_drift", _drift(m, 1.0), 1e-4)


def cortisol(m: Layer4Base) -> Check:
    p = m.parameters()
    state = m.initial_state(p, {})
    _, series = m.run(p, state, {}, np.array([0.0, 0.5, 1.0, 2.0]))  # type: ignore[attr-defined]
    total = sum(series[name] for name in series)
    return Check("Kraan 1992 compartments; the fractions of the dose add up to the dose",
                 "max_mass_balance_error", float(np.max(np.abs(total - total[0]))), 1e-6)


def _cycle_length_days(m: Layer4Base) -> float:
    from ahdt.models.external.sbml_models import lh_peaks

    p = m.parameters()
    t = np.arange(0.0, 90.0, 0.1)
    _, series = m.run(p, m.initial_state(p, {}), {}, t)  # type: ignore[attr-defined]
    peaks = [e.t / 86400.0 for e in lh_peaks(t, series["lh"])]
    if len(peaks) < 2:
        return float("nan")
    return float(np.mean(np.diff(peaks)))


def gonadal(m: Layer4Base) -> Check:
    return Check("Roeblitz 2013 (ZIB report 11-16): simulated cycle length is about 28 days",
                 "cycle_length_error_days", _cycle_length_days(m) - 28.0, 1.4)


def menstrual(m: Layer4Base) -> Check:
    return Check("Roeblitz 2013 (ZIB report 11-16): simulated cycle length is about 28 days",
                 "cycle_length_error_days", _cycle_length_days(m) - 28.0, 1.4)


def immune(m: Layer4Base) -> Check:
    p = m.parameters()
    rows = m.run_days(p, m.initial_state(p, {}), {"antigen_load": 20.0},  # type: ignore[attr-defined]
                      16.0, 1.0)
    peak = max(r.effector_t for r in rows)
    memory = rows[-1].memory_t / peak
    cleared = rows[-1].antigen == 0.0
    return Check("Murali-Krishna 1998: memory cells are about 5 percent of the peak effector "
                 "number; antigen cleared by day 16",
                 "memory_fraction_error", memory - 0.05 if cleared else float("nan"), 0.03)


def mobility(m: Layer4Base) -> Check:
    from ahdt.models.external import mobility_abm

    p = m.parameters()
    model = mobility_abm.MobilityModel(p, seed=7)
    for _ in range(24 * 365 * 4):
        model.step()
    walker = next(iter(model.agents))
    trace = np.array(walker.trace)
    fit = mobility_abm.fit_trace(trace[:, 0], trace[:, 1:], tolerance_km=1e-6)
    return Check("Song 2010 model; maximum likelihood recovers rho and gamma from a simulated "
                 "four-year stay-point trace",
                 "max_abs_error_rho_gamma", max(abs(fit.rho - p["rho"]),
                                                abs(fit.gamma - p["gamma"])), 0.10)


def pbpk(m: Layer4Base) -> Check:
    from ahdt.models.external.pbpk import terminal_half_life_h

    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-pk", anatomy="atra:pk",
                              model_id=m.model_id, version=m.version, owner_dt=m.spec.twin,
                              params={}, state=m.initial_state(m.parameters(), {}))
    scenario = c.Scenario(kind="drug", drug=c.ScenarioDrug(
        atc="A10BA02", dose_mg=500.0, route="oral", schedule_h=[0.0]))
    tr = asyncio.run(m.simulate(record, scenario, 72 * 3600, 600))
    body = (np.array(tr.series["amount_in_body"]) + np.array(tr.series["eliminated_amount"])
            + np.array(tr.series["unabsorbed_amount"]))
    conc = np.array(tr.series["plasma_concentration"])
    hours = np.array(tr.t) / 3600.0
    half = terminal_half_life_h(hours[20:], conc[20:])
    return Check("Mass balance of a 500 mg oral dose (ICRP 89 physiology, FDA label "
                 "clearances); body plus eliminated plus unabsorbed equals the dose. Label "
                 f"comparison, not a pass criterion: metformin Cmax {conc.max():.2f} against "
                 f"1.03 mg/L and plasma half-life {half:.1f} against 6.2 h",
                 "max_relative_mass_error", float(np.max(np.abs(body[1:] - 500.0)) / 500.0),
                 1e-6)


def gait_kinematics(m: Layer4Base) -> Check:
    from ahdt.models.external.opensim_gait import model_check

    r = model_check(m.parameters(), muscles=False)
    return Check("Inverse kinematics of markers made by the gait2392 model itself; the "
                 "markers of the recovered pose against the markers given",
                 "marker_rms_error_m", r["marker_rms_m"], 0.005)


def gait_muscles(m: Layer4Base) -> Check:
    from ahdt.models.external.opensim_gait import model_check

    r = model_check(m.parameters(), muscles=True)
    return Check("Estimated ground reaction force over whole strides; mean vertical force "
                 "equals body weight",
                 "relative_error_mean_vertical_force", r["grf_weight_error"], 0.05)


VALIDATORS: Mapping[str, Callable[[Layer4Base], Check]] = {
    "ahdt.endocrine.glucose_insulin_and_metabolic_regulation.minimal_model": minimal_model,
    "ahdt.endocrine.glucose_insulin_and_metabolic_regulation": glucose_insulin,
    "ahdt.digestive.stomach_and_intestine_absorption": absorption,
    "ahdt.cardiovascular.heart_chambers_and_valves": heart,
    "ahdt.cardiovascular.baroreflex_regulation": baroreflex,
    "ahdt.cardiovascular.coronary_cerebral_peripheral_vasculature_and_microcirculation":
        vasculature,
    "ahdt.respiratory.lungs_and_gas_exchange": gas_exchange,
    "ahdt.respiratory.ventilation_control": ventilation,
    "ahdt.nervous.neuron_and_circuit": neuron,
    "ahdt.nervous.circadian_rhythm_and_sleep": sleep,
    "ahdt.endocrine.hpa_axis": hpa,
    "ahdt.endocrine.pineal": pineal,
    "ahdt.endocrine.hormone_kinetics": hormone_kinetics,
    "ahdt.renal_urinary.kidney_and_renal_function": kidney,
    "ahdt.renal_urinary.fluid_electrolyte_and_acid_base_balance": acid_base,
    "ahdt.hepatobiliary.liver_drug_clearance_capacity": liver,
    "ahdt.immune_lymphatic.inflammation": inflammation,
    "ahdt.immune_lymphatic.infection_response": infection,
    "ahdt.haematological.bone_marrow_and_erythrocytes": erythropoiesis,
    "ahdt.haematological.platelets": platelets,
    "ahdt.musculoskeletal.bone_remodelling_and_density": bone,
    "ahdt.integumentary.thermoregulation": thermoregulation,
    "ahdt.integumentary.heat_stress": heat_stress,
    "ahdt.integumentary.wound_healing": wound,
    "ahdt.digestive.nutrition_and_hydration": nutrition,
    "ahdt.sensory.sensory_decline": sensory,
    "ahdt.whole_body.early_warning": early_warning,
    "ahdt.whole_body.pharmacogenomics": pharmacogenomics,
    "ahdt.whole_body.life_course_and_ageing": life_course,
    "ahdt.whole_body.maternal_foetal": maternal_foetal,
    "ahdt.whole_body.anatomical_avatar": avatar,
    "ahdt.cardiovascular.conduction_system_and_cardiomyocyte_electrophysiology":
        cardiac_electrophysiology,
    "ahdt.cardiovascular.aorta": aorta,
    "ahdt.endocrine.beta_cell_mass_dynamics": beta_cell,
    "ahdt.hepatobiliary.hepatocyte_metabolism_and_detoxification": hepatocyte,
    "ahdt.endocrine.cortisol_metabolism_and_excretion": cortisol,
    "ahdt.endocrine.gonadal_hormones": gonadal,
    "ahdt.reproductive.menstrual_and_fertility_cycle": menstrual,
    "ahdt.immune_lymphatic.t_cell_b_cell_and_macrophage": immune,
    "ahdt.social.mobility": mobility,
    "ahdt.whole_body.whole_body_pbpk": pbpk,
    "ahdt.whole_body.biomechanical_and_kinematic": gait_kinematics,
    "ahdt.musculoskeletal.skeletal_muscle_and_biomechanics": gait_muscles,
}


def run_checks(catalogue: Mapping[str, Layer4Base]) -> dict[str, Check]:
    return {model_id: check(catalogue[model_id]) for model_id, check in VALIDATORS.items()
            if model_id in catalogue}
