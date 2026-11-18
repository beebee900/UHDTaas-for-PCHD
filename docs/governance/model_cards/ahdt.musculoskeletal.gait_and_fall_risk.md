# ahdt.musculoskeletal.gait_and_fall_risk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | musculoskeletal |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of a fall in the next six months from a gait feature window |
| Regulatory status | research |
| Source | Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.5872 (2026-10-11) |

## Inputs

- `gait_speed` (m/s)
- `cadence` (/min)
- `stride_time_cv` (%)

## Outputs

- `fall_risk` (1)

## Validation report: ahdt.musculoskeletal.gait_and_fall_risk 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.5872 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.5872 |
| brier | 0.1118 |
| coverage_90 | 0.9615 |
| ece | 0.1228 |
| mean_set_size | 1.423 |
| operating_threshold | 0.1295 |
| prevalence_test | 0.09615 |
| sensitivity | 0.6 |
| specificity | 0.4894 |

Split: train 159, cal 39, test 52, unit hdt_id.


### Fairness slices: ahdt.musculoskeletal.gait_and_fall_risk

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 29 | 0.286 | 0.170 | 0.966 |
| sex | male | 23 | 0.658 | 0.144 | 0.957 |
| age_band | 40-59 | 27 | 0.736 | 0.068 | 0.963 |
| age_band | 60+ | 25 | 0.413 | 0.183 | 0.960 |
| region | island_and_coast | 15 | 0.769 | 0.128 | 1.000 |
| region | mainland_core | 15 | 0.346 | 0.217 | 0.867 |
| region | north_west | 11 |  | 0.247 | 1.000 |
| region | west_and_ikorodu | 11 | 1.000 | 0.176 | 1.000 |
| facility_level | primary | 25 | 0.792 | 0.126 | 1.000 |
| facility_level | secondary | 21 | 0.737 | 0.151 | 1.000 |
| facility_level | tertiary | 6 | 0.250 | 0.404 | 0.667 |
| language | en | 22 | 0.514 | 0.178 | 0.909 |
| language | ha | 2 |  | 0.259 | 1.000 |
| language | ig | 7 |  | 0.180 | 1.000 |
| language | pcm | 7 |  | 0.237 | 1.000 |
| language | yo | 14 | 0.923 | 0.079 | 1.000 |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.372, coverage 0.009 |
| age_band | auroc 0.323, coverage 0.003 |
| region |  |
| facility_level | auroc 0.055, coverage 0.000 |
| language |  |

Flags: sex: auroc disparity 0.372 > 0.05; age_band: auroc disparity 0.323 > 0.05; facility_level: auroc disparity 0.055 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
