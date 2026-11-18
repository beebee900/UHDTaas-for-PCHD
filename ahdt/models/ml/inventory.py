"""The data-fitted (T1) models of design 04, 4.5.3, built by WP14b.

Every T1 inventory item has one entry, plus the forecasters and the deterioration risk that
design 08 (WP14b step 4 and 5) names, and the MIT-BIH beat classifier the arrhythmia model
depends on. `runs_on` says where the model trains: `laptop` (synthetic data, through
`var/bin/heavy`) or `vm` (open datasets, the job queue in `vm/`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ahdt.models.base import ModelSpec, Port
from atra import contracts as c
from atra.connectors import DTKind

ML = c.ModelFamily.ML
T1 = c.Tier.T1
SYNTH = "atra-synthetic-population"

NBEATS = ("Oreshkin BN, Carpov D, Chapados N, Bengio Y. N-BEATS: neural basis expansion "
          "analysis for interpretable time series forecasting. ICLR 2020; via Darts (Herzen J "
          "et al. Darts: user-friendly modern machine learning for time series. JMLR "
          "2022;23(124):1-6)")
LIGHTGBM = ("Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting "
            "decision tree. NeurIPS 2017")
CONFORMAL = ("Lei J, G'Sell M, Rinaldo A, Tibshirani RJ, Wasserman L. Distribution-free "
             "predictive inference for regression. JASA 2018;113(523):1094-1111")
HMM = ("Rabiner LR. A tutorial on hidden Markov models and selected applications in speech "
       "recognition. Proc IEEE 1989;77(2):257-286")
COX = "Cox DR. Regression models and life-tables. J R Stat Soc B 1972;34(2):187-220"
SAGE = ("Hamilton WL, Ying R, Leskovec J. Inductive representation learning on large graphs. "
        "NeurIPS 2017")
RIVER = ("Montiel J, Halford M, Mastelini SM, et al. River: machine learning for streaming "
         "data in Python. JMLR 2021;22(110):1-8")
SYNTH_DATA = ("trained on the ATRA synthetic population "
              "(WP02 persons; ahdt/models/ml/synthetic.yaml)")


@dataclass(frozen=True)
class T1Item:
    spec: ModelSpec
    dataset: str
    runs_on: Literal["laptop", "vm"]
    inventory: str | None
    """The design 04 inventory item id this model implements (None for a component)."""


def _spec(model_id: str, twin: DTKind, use: str, inputs: tuple[Port, ...],
          outputs: tuple[Port, ...], source: str, **kw: object) -> ModelSpec:
    return ModelSpec(model_id=model_id, twin=twin, family=ML, tier=T1, intended_use=use,
                     inputs=inputs, outputs=outputs, source=source, **kw)  # type: ignore[arg-type]


def P(name: str, unit: str = "1", src: str | None = None) -> Port:
    return Port(name, unit, src)


CV, RESP, NERV = DTKind.CARDIOVASCULAR, DTKind.RESPIRATORY, DTKind.NERVOUS
ITEMS: tuple[T1Item, ...] = (
    T1Item(_spec("ahdt.cardiovascular.blood_pressure_forecasting", CV,
                 "Forecast the next 7 days of twice-daily home SBP and DBP with 90 % bands",
                 (P("sbp", "mm[Hg]"), P("dbp", "mm[Hg]")),
                 (P("sbp_forecast", "mm[Hg]"), P("dbp_forecast", "mm[Hg]")),
                 f"{NBEATS}; bands: {CONFORMAL}; {SYNTH_DATA}",
                 explainers=("timeshap",)), SYNTH, "laptop",
           "ahdt.cardiovascular.blood_pressure_forecasting"),
    T1Item(_spec("ahdt.cardiovascular.arrhythmia_detection", CV,
                 "Rhythm class (sinus, AF, other) of a 10-s lead II ECG at the edge",
                 (P("ecg_lead_ii", "mV"),), (P("rhythm_probability"),),
                 "1D-CNN ensemble (5 members) trained on PTB-XL 1.0.3 lead II (Wagner P et al. "
                 "Sci Data 2020;7:154; PhysioNet https://doi.org/10.13026/kfzx-aw45)",
                 depends_on=(("ahdt.cardiovascular.arrhythmia_beat_classification", "1.0.0"),)),
           "ptb-xl", "vm", "ahdt.cardiovascular.arrhythmia_detection"),
    T1Item(_spec("ahdt.cardiovascular.arrhythmia_beat_classification", CV,
                 "AAMI beat class of each beat of a lead II ECG",
                 (P("ecg_lead_ii", "mV"),), (P("beat_class_probability"),),
                 "1D-CNN trained on the MIT-BIH Arrhythmia Database 1.0.0 (Moody GB, Mark RG. "
                 "IEEE Eng Med Biol 2001;20(3):45-50)"), "mitdb", "vm", None),
    T1Item(_spec("ahdt.respiratory.spo2_desaturation_detection", RESP,
                 "Flag a desaturation in a closed SpO2 feature window at the edge",
                 (P("spo2", "%"), P("heart_rate", "/min")), (P("desaturation_probability"),),
                 f"Rule (SpO2 below kb threshold.hypoxaemia_child) + {LIGHTGBM}; {SYNTH_DATA}"),
           SYNTH, "laptop", "ahdt.respiratory.spo2_desaturation_detection"),
    T1Item(_spec("ahdt.respiratory.exacerbation_risk", RESP,
                 "Probability of an asthma or COPD exacerbation in the next 14 days",
                 (P("pef", "L/min"), P("pm25", "ug/m3")), (P("exacerbation_risk"),),
                 f"{LIGHTGBM}; {SYNTH_DATA}"),
           SYNTH, "laptop", "ahdt.respiratory.exacerbation_risk"),
    T1Item(_spec("ahdt.nervous.eeg_analysis_and_sleep_staging", NERV,
                 "Sleep stage (W, N1, N2, N3, REM) of each 30-s EEG epoch; per-person "
                 "continual learning across nights",
                 (P("eeg_fpz_cz", "uV"),), (P("sleep_stage_probability"),),
                 "1D-CNN on the Sleep-EDF Database Expanded 1.0.0 sleep-cassette recordings "
                 "(Kemp B et al. IEEE-BME 2000;47(9):1185-94); continual learning with "
                 "Avalanche (Lomonaco V et al. CVPR Workshops 2021)"),
           "sleep-edfx", "vm", "ahdt.nervous.eeg_analysis_and_sleep_staging"),
    T1Item(_spec("ahdt.haematological.anaemia_and_sickle_cell_crisis_risk",
                 DTKind.HAEMATOLOGICAL, "Probability of a vaso-occlusive crisis in the next 30 "
                 "days for a person with HbSS",
                 (P("hb", "g/dL"), P("hbf", "%"), P("temperature", "Cel")), (P("crisis_risk"),),
                 f"{LIGHTGBM}; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.haematological.anaemia_and_sickle_cell_crisis_risk"),
    T1Item(_spec("ahdt.musculoskeletal.gait_and_fall_risk", DTKind.MUSCULOSKELETAL,
                 "Probability of a fall in the next six months from a gait feature window",
                 (P("gait_speed", "m/s"), P("cadence", "/min"), P("stride_time_cv", "%")),
                 (P("fall_risk"),), f"{LIGHTGBM}; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.musculoskeletal.gait_and_fall_risk"),
    T1Item(_spec("ahdt.whole_body.clinical_health_state", DTKind.WHOLE_BODY,
                 "Posterior over the clinical state (stable, deteriorating, critical, "
                 "recovering) from NEWS2, the problem list and the vital-sign statuses",
                 (P("news2"),), (P("clinical_state_probability"),), f"{HMM}; {SYNTH_DATA}"),
           SYNTH, "laptop", "ahdt.whole_body.clinical_health_state"),
    T1Item(_spec("ahdt.whole_body.deterioration_risk", DTKind.WHOLE_BODY,
                 "Probability of entering the critical state within 24 h (T1 part of the "
                 "early-warning item)", (P("news2"), P("respiratory_rate", "/min"),
                                         P("spo2", "%"), P("sbp", "mm[Hg]")),
                 (P("deterioration_risk"),), f"{LIGHTGBM}; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.whole_body.early_warning"),
    T1Item(_spec("ahdt.whole_body.news2_component_forecasting", DTKind.WHOLE_BODY,
                 "Forecast the next 6 h of the NEWS2 vital signs with 90 % bands",
                 (P("respiratory_rate", "/min"), P("spo2", "%"), P("sbp", "mm[Hg]"),
                  P("heart_rate", "/min"), P("temperature", "Cel")),
                 (P("vital_sign_forecast"),), f"{NBEATS}; bands: {CONFORMAL}; {SYNTH_DATA}",
                 explainers=("timeshap",)), SYNTH, "laptop", None),
    T1Item(_spec("ahdt.endocrine.glucose_forecasting", DTKind.ENDOCRINE,
                 "Forecast the next 2 days of capillary glucose with 90 % bands",
                 (P("glucose", "mmol/L"),), (P("glucose_forecast", "mmol/L"),),
                 f"{NBEATS}; bands: {CONFORMAL}; {SYNTH_DATA}", explainers=("timeshap",)),
           SYNTH, "laptop", None),
    T1Item(_spec("ahdt.behavioural_cognitive.affect_and_stress", DTKind.BEHAVIOURAL_COGNITIVE,
                 "Probability of stress in a 60-s window of ECG-derived HRV, EDA and skin "
                 "temperature", (P("hrv_rmssd", "ms"), P("skin_temp", "Cel")),
                 (P("stress_probability"),),
                 f"{LIGHTGBM}; WESAD (Schmidt P et al. ICMI 2018)"), "wesad", "vm",
           "ahdt.behavioural_cognitive.affect_and_stress"),
    T1Item(_spec("ahdt.behavioural_cognitive.mental_health_trajectory",
                 DTKind.BEHAVIOURAL_COGNITIVE,
                 "Severity state of the PHQ-9/GAD-7 series and the next PHQ-9 total with a 90 % "
                 "interval", (P("phq9"), P("gad7")), (P("phq9_forecast"), P("severity_state")),
                 f"{HMM}; interval: {CONFORMAL}; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.behavioural_cognitive.mental_health_trajectory"),
    T1Item(_spec("ahdt.behavioural_cognitive.lifestyle", DTKind.BEHAVIOURAL_COGNITIVE,
                 "Per-person online baselines of activity, sleep and screen time with "
                 "anomaly flags", (P("steps"), P("active_minutes", "min"),
                                   P("sleep_duration", "h"), P("screen_time", "min")),
                 (P("lifestyle_anomaly_score"),), f"{RIVER}; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.behavioural_cognitive.lifestyle"),
    T1Item(_spec("ahdt.behavioural_cognitive.adherence", DTKind.BEHAVIOURAL_COGNITIVE,
                 "Probability of a refill gap within 180 days",
                 (P("distance_to_facility", "km"),), (P("adherence"),),
                 f"{COX}; lifelines (Davidson-Pilon C. JOSS 2019;4(40):1317); {SYNTH_DATA}"),
           SYNTH, "laptop", "ahdt.behavioural_cognitive.adherence"),
    T1Item(_spec("ahdt.social.social_network", DTKind.SOCIAL,
                 "Probability that support is available to the person in their network",
                 (P("household_support"),), (P("support_probability"),),
                 f"{SAGE}; PyTorch Geometric; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.social.social_network"),
    T1Item(_spec("ahdt.population.cohort", DTKind.POPULATION,
                 "Cohort definitions and statistics over contributed, de-identified records",
                 (P("cohort_size"),), (P("cohort_statistics"),),
                 f"Cohort counts with small-cell suppression; {SYNTH_DATA}"), SYNTH, "laptop",
           "ahdt.population.cohort"),
    T1Item(_spec("ahdt.population.population_priors_and_norms", DTKind.POPULATION,
                 "Prevalence by condition x age band x sex x season x region and field "
                 "percentiles, with a differentially private federated update",
                 (P("cohort_size"),), (P("prevalence"), P("field_percentiles")),
                 f"Beta-smoothed prevalence tables with Laplace noise per tenant; {SYNTH_DATA}"),
           SYNTH, "laptop", "ahdt.population.population_priors_and_norms"),
)

BY_ID: Mapping[str, T1Item] = {i.spec.model_id: i for i in ITEMS}


def inventory_t1_ids() -> list[str]:
    """Design 04 inventory items implemented here (one per T1 row of 4.5.3)."""
    return sorted({i.inventory for i in ITEMS if i.inventory})
