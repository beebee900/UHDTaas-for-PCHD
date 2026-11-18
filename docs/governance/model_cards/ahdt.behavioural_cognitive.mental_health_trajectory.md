# ahdt.behavioural_cognitive.mental_health_trajectory

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | behavioural_cognitive |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Severity state of the PHQ-9/GAD-7 series and the next PHQ-9 total with a 90 % interval |
| Regulatory status | research |
| Source | Rabiner LR. A tutorial on hidden Markov models and selected applications in speech recognition. Proc IEEE 1989;77(2):257-286; interval: Lei J, G'Sell M, Rinaldo A, Tibshirani RJ, Wasserman L. Distribution-free predictive inference for regression. JASA 2018;113(523):1094-1111; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae_next_phq9 = 2.607 (2026-10-11) |

## Inputs

- `phq9` (1)
- `gad7` (1)

## Outputs

- `phq9_forecast` (1)
- `severity_state` (1)

## Validation report: ahdt.behavioural_cognitive.mental_health_trajectory 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae_next_phq9 = 2.607 (2026-10-11).

| Metric | Value |
|---|---|
| coverage_90 | 0.8982 |
| halfwidth_90 | 5.467 |
| mae_next_phq9 | 2.607 |
| state_macro_f1 | 0.9559 |

Split: train 628, cal 224, test 193, unit person.


### Fairness slices: ahdt.behavioural_cognitive.mental_health_trajectory

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 2231 | 2.624 |  | 0.900 |
| sex | male | 2208 | 2.590 |  | 0.897 |
| age_band | 18-39 | 2438 | 2.636 |  | 0.890 |
| age_band | 40-59 | 1426 | 2.563 |  | 0.909 |
| age_band | 60+ | 575 | 2.591 |  | 0.904 |
| region | island_and_coast | 1357 | 2.593 |  | 0.895 |
| region | mainland_core | 1219 | 2.650 |  | 0.901 |
| region | north_west | 874 | 2.645 |  | 0.896 |
| region | west_and_ikorodu | 989 | 2.538 |  | 0.902 |
| facility_level | primary | 2300 | 2.602 |  | 0.907 |
| facility_level | secondary | 1656 | 2.565 |  | 0.892 |
| facility_level | tertiary | 483 | 2.770 |  | 0.878 |
| language | en | 1679 | 2.618 |  | 0.898 |
| language | ha | 207 | 2.790 |  | 0.879 |
| language | ig | 552 | 2.628 |  | 0.897 |
| language | pcm | 575 | 2.597 |  | 0.901 |
| language | yo | 1426 | 2.563 |  | 0.900 |

| Attribute | Disparity |
|---|---|
| sex | mae 0.034, coverage 0.003 |
| age_band | mae 0.073, coverage 0.018 |
| region | mae 0.112, coverage 0.007 |
| facility_level | mae 0.205, coverage 0.029 |
| language | mae 0.227, coverage 0.022 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
