# ahdt.cardiovascular.arrhythmia_detection

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Rhythm class (sinus, AF, other) of a 10-s lead II ECG at the edge |
| Regulatory status | research |
| Source | 1D-CNN ensemble (5 members) trained on PTB-XL 1.0.3 lead II (Wagner P et al. Sci Data 2020;7:154; PhysioNet https://doi.org/10.13026/kfzx-aw45) |
| Training data | ptb-xl (vm) |
| Validation | ptb-xl 1.0.3 (strat_fold 10): macro_f1 = 0.7793 (2026-10-11) |
| Depends on | ahdt.cardiovascular.arrhythmia_beat_classification 1.0.0 |

## Inputs

- `ecg_lead_ii` (mV)

## Outputs

- `rhythm_probability` (1)

## Validation report: ahdt.cardiovascular.arrhythmia_detection 1.0.0

ptb-xl 1.0.3 (strat_fold 10): macro_f1 = 0.7793 (2026-10-11).

| Metric | Value |
|---|---|
| accuracy | 0.9542 |
| af_auroc | 0.9787 |
| af_ece | 0.0113 |
| af_operating_threshold | 0.4774 |
| af_sensitivity | 0.8553 |
| af_specificity | 0.982 |
| coverage_90 | 0.8885 |
| ece | 0.01361 |
| f1_af | 0.8037 |
| f1_other | 0.5567 |
| f1_sinus | 0.9775 |
| macro_f1 | 0.7793 |
| mean_set_size | 0.9032 |
| member0_val_macro_f1 | 0.7992 |
| member1_val_macro_f1 | 0.7977 |
| member2_val_macro_f1 | 0.801 |
| member3_val_macro_f1 | 0.7839 |
| member4_val_macro_f1 | 0.7937 |
| n_test_af | 152 |
| n_test_other | 60 |
| n_test_sinus | 1886 |

Split: train 16832, validation 2100, test 2098, unit record (patient-wise folds).

- Folds 1-8 train, 9 validation and calibration, 10 test, as the PhysioNet PTB-XL page recommends.
- Rhythm classes from scp_statements.csv: sinus = SR, STACH, SARRH, SBRAD; af = AFIB; other = any other rhythm code.
- 5-member ensemble (mean probability), exported to arrhythmia.onnx and checked against torch with onnxruntime.


### Fairness slices: ahdt.cardiovascular.arrhythmia_detection

Metric: macro_f1. Slices with fewer than 20 persons are listed but not used for the disparity.

| Attribute | Slice | n | macro_f1 | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 1014 | 0.748 | 0.011 | 0.899 |
| sex | male | 1084 | 0.806 | 0.022 | 0.878 |
| age_band | 0-4 | 1 | 0.000 | 0.718 | 0.000 |
| age_band | 18-39 | 265 | 0.499 | 0.018 | 0.977 |
| age_band | 40-59 | 617 | 0.640 | 0.009 | 0.953 |
| age_band | 5-17 | 12 | 0.455 | 0.191 | 0.750 |
| age_band | 60+ | 1203 | 0.793 | 0.021 | 0.838 |

| Attribute | Disparity |
|---|---|
| sex | macro_f1 0.058, coverage 0.021 |
| age_band | macro_f1 0.294, coverage 0.139 |

Not in this dataset: region, facility_level, language.

Flags: age_band: coverage disparity 0.139 > 0.05.

Slices use the dataset's own age and sex. Rows are beats or recordings of few persons, and the cohorts are not African, so these numbers do not show equity for the ATRA population.
