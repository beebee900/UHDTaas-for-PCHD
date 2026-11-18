# ahdt.respiratory.spo2_desaturation_detection

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Flag a desaturation in a closed SpO2 feature window at the edge |
| Regulatory status | research |
| Source | Rule (SpO2 below kb threshold.hypoxaemia_child) + Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.9463 (2026-10-11) |

## Inputs

- `spo2` (%)
- `heart_rate` (/min)

## Outputs

- `desaturation_probability` (1)

## Validation report: ahdt.respiratory.spo2_desaturation_detection 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.9463 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.9463 |
| brier | 0.07671 |
| coverage_90 | 0.897 |
| ece | 0.07511 |
| mean_set_size | 0.9681 |
| operating_threshold | 0.9892 |
| prevalence_test | 0.1722 |
| sensitivity | 0.8836 |
| specificity | 0.9144 |

Split: train 14232, cal 5028, test 4740, unit hdt_id.

- The rule threshold is kb threshold.hypoxaemia_child (children), applied to every age until an adult edge threshold is signed off.


### Fairness slices: ahdt.respiratory.spo2_desaturation_detection

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 2328 | 0.947 | 0.077 | 0.899 |
| sex | male | 2412 | 0.946 | 0.074 | 0.896 |
| age_band | 0-4 | 744 | 0.947 | 0.075 | 0.906 |
| age_band | 18-39 | 1272 | 0.933 | 0.091 | 0.878 |
| age_band | 40-59 | 744 | 0.949 | 0.077 | 0.901 |
| age_band | 5-17 | 1680 | 0.955 | 0.066 | 0.905 |
| age_band | 60+ | 300 | 0.943 | 0.081 | 0.900 |
| region | island_and_coast | 1356 | 0.948 | 0.076 | 0.897 |
| region | mainland_core | 1236 | 0.945 | 0.079 | 0.892 |
| region | north_west | 1128 | 0.950 | 0.071 | 0.902 |
| region | west_and_ikorodu | 1020 | 0.940 | 0.082 | 0.898 |
| facility_level | primary | 2616 | 0.952 | 0.069 | 0.904 |
| facility_level | secondary | 1668 | 0.934 | 0.092 | 0.879 |
| facility_level | tertiary | 456 | 0.960 | 0.055 | 0.923 |
| language | en | 1728 | 0.941 | 0.082 | 0.888 |
| language | ha | 156 | 0.967 | 0.044 | 0.904 |
| language | ig | 540 | 0.951 | 0.068 | 0.907 |
| language | pcm | 864 | 0.952 | 0.076 | 0.900 |
| language | yo | 1452 | 0.946 | 0.076 | 0.902 |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.001, coverage 0.003 |
| age_band | auroc 0.021, coverage 0.028 |
| region | auroc 0.010, coverage 0.011 |
| facility_level | auroc 0.026, coverage 0.044 |
| language | auroc 0.026, coverage 0.020 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
