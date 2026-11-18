# ahdt.social.social_network

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | social |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability that support is available to the person in their network |
| Regulatory status | research |
| Source | Hamilton WL, Ying R, Leskovec J. Inductive representation learning on large graphs. NeurIPS 2017; PyTorch Geometric; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.604 (2026-10-11) |

## Inputs

- `household_support` (1)

## Outputs

- `support_probability` (1)

## Validation report: ahdt.social.social_network 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.604 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.604 |
| baseline_auroc_no_graph | 0.5829 |
| ece | 0.2092 |
| edges | 7258 |
| nodes | 2000 |

Split: train 1186, cal 419, test 395, unit person.


### Fairness slices: ahdt.social.social_network

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 194 | 0.581 | 0.218 |  |
| sex | male | 201 | 0.626 | 0.201 |  |
| age_band | 0-4 | 62 | 0.738 | 0.143 |  |
| age_band | 18-39 | 106 | 0.509 | 0.289 |  |
| age_band | 40-59 | 62 | 0.652 | 0.231 |  |
| age_band | 5-17 | 140 | 0.588 | 0.186 |  |
| age_band | 60+ | 25 | 0.681 | 0.320 |  |
| region | island_and_coast | 113 | 0.573 | 0.253 |  |
| region | mainland_core | 103 | 0.665 | 0.207 |  |
| region | north_west | 94 | 0.603 | 0.202 |  |
| region | west_and_ikorodu | 85 | 0.578 | 0.203 |  |
| facility_level | primary | 218 | 0.551 | 0.252 |  |
| facility_level | secondary | 139 | 0.699 | 0.132 |  |
| facility_level | tertiary | 38 | 0.554 | 0.265 |  |
| language | en | 144 | 0.645 | 0.204 |  |
| language | ha | 13 | 0.476 | 0.405 |  |
| language | ig | 45 | 0.664 | 0.238 |  |
| language | pcm | 72 | 0.562 | 0.253 |  |
| language | yo | 121 | 0.555 | 0.212 |  |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.044 |
| age_band | auroc 0.229 |
| region | auroc 0.092 |
| facility_level | auroc 0.147 |
| language | auroc 0.109 |

Flags: age_band: auroc disparity 0.229 > 0.05; region: auroc disparity 0.092 > 0.05; facility_level: auroc disparity 0.147 > 0.05; language: auroc disparity 0.109 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
