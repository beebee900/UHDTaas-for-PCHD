# ahdt.cardiovascular.arrhythmia_beat_classification

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | AAMI beat class of each beat of a lead II ECG |
| Regulatory status | research |
| Source | 1D-CNN trained on the MIT-BIH Arrhythmia Database 1.0.0 (Moody GB, Mark RG. IEEE Eng Med Biol 2001;20(3):45-50) |
| Training data | mitdb (vm) |
| Validation | mitdb 1.0.0 (DS2 inter-patient test records): macro_f1_nsvf = 0.4241 (2026-10-11) |

## Inputs

- `ecg_lead_ii` (mV)

## Outputs

- `beat_class_probability` (1)

## Validation report: ahdt.cardiovascular.arrhythmia_beat_classification 1.0.0

mitdb 1.0.0 (DS2 inter-patient test records): macro_f1_nsvf = 0.4241 (2026-10-11).

| Metric | Value |
|---|---|
| accuracy | 0.6975 |
| coverage_90 | 0.9465 |
| ece | 0.06842 |
| macro_f1_nsvf | 0.4241 |
| mean_set_size | 2.52 |
| n_test_F | 388 |
| n_test_N | 4.422e+04 |
| n_test_Q | 7 |
| n_test_S | 1836 |
| n_test_V | 3219 |
| ppv_F | 0.02275 |
| ppv_N | 0.9612 |
| ppv_S | 0.09472 |
| ppv_V | 0.6154 |
| sensitivity_F | 0.4613 |
| sensitivity_N | 0.7101 |
| sensitivity_Q | 0 |
| sensitivity_S | 0.2533 |
| sensitivity_V | 0.8074 |

Split: train_records 17, validation_records 5, test_records 22, train_beats 39108, test_beats 49667, unit record.

- AAMI mapping and DS1/DS2 from Guo et al. 2019 (arXiv 1810.04121), Table 1 and Section IV.A.
- Headline macro-F1 is over N, S, V and F; Q has almost no beats.
- Validation and calibration records (from DS1): [101, 109, 112, 201, 203].


### Fairness slices: ahdt.cardiovascular.arrhythmia_beat_classification

Metric: macro_f1. Slices with fewer than 20 persons are listed but not used for the disparity.

| Attribute | Slice | n | macro_f1 | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 23238 | 0.252 | 0.065 | 0.959 |
| sex | male | 26429 | 0.341 | 0.074 | 0.936 |
| age_band | 18-39 | 4539 | 0.254 | 0.138 | 1.000 |
| age_band | 40-59 | 10210 | 0.253 | 0.254 | 0.858 |
| age_band | 60+ | 30684 | 0.360 | 0.076 | 0.966 |
| age_band | unknown | 4234 | 0.462 | 0.061 | 0.963 |

| Attribute | Disparity |
|---|---|
| sex | macro_f1 0.089, coverage 0.023 |
| age_band | macro_f1 0.209, coverage 0.141 |

Not in this dataset: region, facility_level, language.

Flags: age_band: coverage disparity 0.141 > 0.05.

Slices use the dataset's own age and sex. Rows are beats or recordings of few persons, and the cohorts are not African, so these numbers do not show equity for the ATRA population.
