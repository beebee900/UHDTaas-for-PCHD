# ahdt.behavioural_cognitive.affect_and_stress

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | behavioural_cognitive |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of stress in a 60-s window of ECG-derived HRV, EDA and skin temperature |
| Regulatory status | research |
| Source | Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; WESAD (Schmidt P et al. ICMI 2018) |
| Training data | wesad (vm) |
| Validation | wesad (leave-one-subject-out): loso_auroc = 0.9779 (2026-10-11) |

## Inputs

- `hrv_rmssd` (ms)
- `skin_temp` (Cel)

## Outputs

- `stress_probability` (1)

## Validation report: ahdt.behavioural_cognitive.affect_and_stress 1.0.0

wesad (leave-one-subject-out): loso_auroc = 0.9779 (2026-10-11).

| Metric | Value |
|---|---|
| holdout_auroc | 1 |
| holdout_brier | 0.09434 |
| holdout_coverage_90 | 0.8857 |
| holdout_ece | 0.119 |
| holdout_mean_set_size | 1 |
| holdout_operating_threshold | 0.05678 |
| holdout_prevalence_test | 0.3 |
| holdout_sensitivity | 0.9048 |
| holdout_specificity | 1 |
| loso_auroc | 0.9779 |
| loso_auroc_subject_mean | 0.9765 |
| loso_auroc_subject_min | 0.7993 |
| loso_brier | 0.05188 |
| loso_ece | 0.03871 |
| stress_share | 0.2985 |
| windows | 1042 |

Split: train 696, cal 276, test 70, unit subject, subjects 15, validation leave-one-subject-out (headline); person split (holdout_*).

- Stress (protocol label 2) against baseline (1) and amusement (3); meditation (4) left out.
- 60-s windows, 30-s step, chest RespiBAN at 700 Hz; R-peaks with NeuroKit2, EDA at 4 Hz.


### Fairness slices: ahdt.behavioural_cognitive.affect_and_stress

Metric: auroc. Slices with fewer than 20 persons are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 211 | 0.993 | 0.033 |  |
| sex | male | 831 | 0.974 | 0.044 |  |
| age_band | 18-39 | 1042 | 0.978 | 0.039 |  |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.019 |
| age_band |  |

Not in this dataset: region, facility_level, language.

Flags: none.

Slices use the WESAD readme age and sex of 15 young adults (3 female), so the tables show the pipeline, not equity for the ATRA population.
