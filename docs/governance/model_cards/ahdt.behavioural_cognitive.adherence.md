# ahdt.behavioural_cognitive.adherence

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | behavioural_cognitive |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of a refill gap within 180 days |
| Regulatory status | research |
| Source | Cox DR. Regression models and life-tables. J R Stat Soc B 1972;34(2):187-220; lifelines (Davidson-Pilon C. JOSS 2019;4(40):1317); trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): c_index = 0.6474 (2026-10-11) |

## Inputs

- `distance_to_facility` (km)

## Outputs

- `adherence` (1)

## Validation report: ahdt.behavioural_cognitive.adherence 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): c_index = 0.6474 (2026-10-11).

| Metric | Value |
|---|---|
| c_index | 0.6474 |
| calibration_error | 0.0547 |
| observed_gap_180d | 0.6 |
| predicted_gap_180d | 0.5453 |

Split: train 202, cal 55, test 70, unit person.


### Fairness slices: ahdt.behavioural_cognitive.adherence

Metric: c_index. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | c_index | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 35 | 0.676 |  |  |
| sex | male | 35 | 0.614 |  |  |
| age_band | 18-39 | 18 | 0.693 |  |  |
| age_band | 40-59 | 34 | 0.711 |  |  |
| age_band | 60+ | 18 | 0.507 |  |  |
| region | island_and_coast | 16 | 0.701 |  |  |
| region | mainland_core | 21 | 0.608 |  |  |
| region | north_west | 14 | 0.667 |  |  |
| region | west_and_ikorodu | 19 | 0.737 |  |  |
| facility_level | primary | 40 | 0.606 |  |  |
| facility_level | secondary | 24 | 0.667 |  |  |
| facility_level | tertiary | 6 | 0.643 |  |  |
| language | en | 27 | 0.568 |  |  |
| language | ha | 4 | 0.667 |  |  |
| language | ig | 8 | 0.889 |  |  |
| language | pcm | 10 | 0.690 |  |  |
| language | yo | 21 | 0.642 |  |  |

| Attribute | Disparity |
|---|---|
| sex | c_index 0.062 |
| age_band |  |
| region |  |
| facility_level | c_index 0.061 |
| language | c_index 0.074 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
