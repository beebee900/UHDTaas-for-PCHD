# ahdt.whole_body.deterioration_risk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of entering the critical state within 24 h (T1 part of the early-warning item) |
| Regulatory status | research |
| Source | Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.6243 (2026-10-11) |

## Inputs

- `news2` (1)
- `respiratory_rate` (/min)
- `spo2` (%)
- `sbp` (mm[Hg])

## Outputs

- `deterioration_risk` (1)

## Validation report: ahdt.whole_body.deterioration_risk 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.6243 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.6243 |
| brier | 0.1051 |
| coverage_90 | 0.8965 |
| ece | 0.06412 |
| mean_set_size | 1.065 |
| operating_threshold | 0.04276 |
| prevalence_test | 0.1152 |
| sensitivity | 0.6825 |
| specificity | 0.3654 |

Split: train 9964, cal 3347, test 2734, unit hdt_id.


### Fairness slices: ahdt.whole_body.deterioration_risk

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 1552 | 0.557 | 0.076 | 0.888 |
| sex | male | 1182 | 0.708 | 0.048 | 0.908 |
| age_band | 18-39 | 1296 | 0.657 | 0.083 | 0.878 |
| age_band | 40-59 | 865 | 0.441 | 0.081 | 0.895 |
| age_band | 5-17 | 257 | 0.709 | 0.059 | 0.953 |
| age_band | 60+ | 316 | 0.936 | 0.045 | 0.930 |
| region | island_and_coast | 1083 | 0.682 | 0.068 | 0.893 |
| region | mainland_core | 590 | 0.350 | 0.094 | 0.942 |
| region | north_west | 508 | 0.726 | 0.057 | 0.856 |
| region | west_and_ikorodu | 553 | 0.497 | 0.091 | 0.892 |
| facility_level | primary | 1194 | 0.825 | 0.032 | 0.939 |
| facility_level | secondary | 1219 | 0.433 | 0.138 | 0.859 |
| facility_level | tertiary | 321 | 0.699 | 0.081 | 0.882 |
| language | en | 1148 | 0.744 | 0.042 | 0.916 |
| language | ha | 66 |  | 0.073 | 1.000 |
| language | ig | 132 |  | 0.086 | 1.000 |
| language | pcm | 264 | 0.658 | 0.086 | 0.985 |
| language | yo | 1124 | 0.508 | 0.120 | 0.838 |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.152, coverage 0.020 |
| age_band | auroc 0.496, coverage 0.075 |
| region | auroc 0.375, coverage 0.086 |
| facility_level | auroc 0.392, coverage 0.080 |
| language | auroc 0.236, coverage 0.162 |

Flags: sex: auroc disparity 0.152 > 0.05; age_band: auroc disparity 0.496 > 0.05; age_band: coverage disparity 0.075 > 0.05; region: auroc disparity 0.375 > 0.05; region: coverage disparity 0.086 > 0.05; facility_level: auroc disparity 0.392 > 0.05; facility_level: coverage disparity 0.080 > 0.05; language: auroc disparity 0.236 > 0.05; language: coverage disparity 0.162 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
