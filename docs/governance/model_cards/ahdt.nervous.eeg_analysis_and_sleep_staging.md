# ahdt.nervous.eeg_analysis_and_sleep_staging

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | nervous |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Sleep stage (W, N1, N2, N3, REM) of each 30-s EEG epoch; per-person continual learning across nights |
| Regulatory status | research |
| Source | 1D-CNN on the Sleep-EDF Database Expanded 1.0.0 sleep-cassette recordings (Kemp B et al. IEEE-BME 2000;47(9):1185-94); continual learning with Avalanche (Lomonaco V et al. CVPR Workshops 2021) |
| Training data | sleep-edfx (vm) |
| Validation | sleep-edfx 1.0.0 sleep cassette (test subjects): macro_f1 = 0.7668 (2026-10-11) |

## Inputs

- `eeg_fpz_cz` (uV)

## Outputs

- `sleep_stage_probability` (1)

## Validation report: ahdt.nervous.eeg_analysis_and_sleep_staging 1.0.0

sleep-edfx 1.0.0 sleep cassette (test subjects): macro_f1 = 0.7668 (2026-10-11).

| Metric | Value |
|---|---|
| accuracy | 0.8249 |
| cohen_kappa | 0.7597 |
| continual_cal_macro_f1_after | 0.6952 |
| continual_cal_macro_f1_before | 0.6984 |
| continual_night2_macro_f1_after | 0.7611 |
| continual_night2_macro_f1_before | 0.7635 |
| coverage_90 | 0.9359 |
| ece | 0.01022 |
| f1_N1 | 0.4846 |
| f1_N2 | 0.8694 |
| f1_N3 | 0.7929 |
| f1_REM | 0.7593 |
| f1_W | 0.9276 |
| macro_f1 | 0.7668 |
| mean_set_size | 1.403 |

Split: train 137024, cal 31362, test 27093, unit subject.

- Stages: R&K 3 and 4 merged into N3; 30 min of wake kept on each side of sleep.
- Subjects: train 53, calibration 13, test 12.
- Continual step: Avalanche Replay (memory 2000) on the first night of 11 test subjects; continual.pt.


### Fairness slices: ahdt.nervous.eeg_analysis_and_sleep_staging

Metric: macro_f1. Slices with fewer than 20 persons are listed but not used for the disparity.

| Attribute | Slice | n | macro_f1 | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 16665 | 0.773 | 0.008 | 0.931 |
| sex | male | 10428 | 0.686 | 0.016 | 0.943 |
| age_band | 18-39 | 10807 | 0.779 | 0.008 | 0.934 |
| age_band | 40-59 | 8660 | 0.750 | 0.020 | 0.928 |
| age_band | 60+ | 7626 | 0.719 | 0.018 | 0.947 |

| Attribute | Disparity |
|---|---|
| sex | macro_f1 0.087, coverage 0.012 |
| age_band | macro_f1 0.060, coverage 0.020 |

Not in this dataset: region, facility_level, language.

Flags: none.

Slices use the Sleep-EDF age and sex of healthy Caucasian adults aged 25 to 101, so the tables do not show equity for the ATRA population.
