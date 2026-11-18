# ahdt.behavioural_cognitive.lifestyle

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | behavioural_cognitive |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Per-person online baselines of activity, sleep and screen time with anomaly flags |
| Regulatory status | research |
| Source | Montiel J, Halford M, Mastelini SM, et al. River: machine learning for streaming data in Python. JMLR 2021;22(110):1-8; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.9658 (2026-10-11) |

## Inputs

- `steps` (1)
- `active_minutes` (min)
- `sleep_duration` (h)
- `screen_time` (min)

## Outputs

- `lifestyle_anomaly_score` (1)

## Validation report: ahdt.behavioural_cognitive.lifestyle 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.9658 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.9658 |
| ece_score_map | 0.2765 |
| fading_factor | 0.05 |
| flag_threshold_z | 2.705 |
| sensitivity | 0.7736 |
| specificity | 0.9564 |

Split: train 92880, cal 33960, test 30480, unit person-day.

- ECE and the slice table use the score mapped to (0, 1) with 0.5 at the flag threshold; the score is not a calibrated probability.


### Fairness slices: ahdt.behavioural_cognitive.lifestyle

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 13250 | 0.966 | 0.277 |  |
| sex | male | 13674 | 0.966 | 0.277 |  |
| age_band | 18-39 | 11236 | 0.964 | 0.279 |  |
| age_band | 40-59 | 6572 | 0.969 | 0.275 |  |
| age_band | 5-17 | 6466 | 0.968 | 0.275 |  |
| age_band | 60+ | 2650 | 0.960 | 0.278 |  |
| region | island_and_coast | 8480 | 0.966 | 0.273 |  |
| region | mainland_core | 6678 | 0.960 | 0.277 |  |
| region | north_west | 6042 | 0.962 | 0.281 |  |
| region | west_and_ikorodu | 5724 | 0.975 | 0.276 |  |
| facility_level | primary | 13674 | 0.964 | 0.277 |  |
| facility_level | secondary | 10388 | 0.967 | 0.276 |  |
| facility_level | tertiary | 2862 | 0.970 | 0.278 |  |
| language | en | 9964 | 0.965 | 0.275 |  |
| language | ha | 1060 | 0.975 | 0.283 |  |
| language | ig | 3074 | 0.952 | 0.281 |  |
| language | pcm | 4240 | 0.970 | 0.273 |  |
| language | yo | 8586 | 0.968 | 0.278 |  |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.001 |
| age_band | auroc 0.009 |
| region | auroc 0.015 |
| facility_level | auroc 0.006 |
| language | auroc 0.023 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
