# ahdt.haematological.anaemia_and_sickle_cell_crisis_risk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | haematological |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of a vaso-occlusive crisis in the next 30 days for a person with HbSS |
| Regulatory status | research |
| Source | Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.7383 (2026-10-11) |

## Inputs

- `hb` (g/dL)
- `hbf` (%)
- `temperature` (Cel)

## Outputs

- `crisis_risk` (1)

## Validation report: ahdt.haematological.anaemia_and_sickle_cell_crisis_risk 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.7383 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.7383 |
| brier | 0.05516 |
| coverage_90 | 0.8953 |
| ece | 0.02518 |
| mean_set_size | 0.9421 |
| operating_threshold | 0.006013 |
| prevalence_test | 0.05945 |
| sensitivity | 0.9829 |
| specificity | 0.1421 |

Split: train 6024, cal 1608, test 1968, unit hdt_id.


### Fairness slices: ahdt.haematological.anaemia_and_sickle_cell_crisis_risk

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 1008 | 0.740 | 0.026 | 0.900 |
| sex | male | 960 | 0.735 | 0.027 | 0.891 |
| age_band | 0-4 | 360 | 0.695 | 0.019 | 0.903 |
| age_band | 18-39 | 648 | 0.673 | 0.044 | 0.869 |
| age_band | 40-59 | 384 | 0.866 | 0.017 | 0.909 |
| age_band | 5-17 | 528 | 0.755 | 0.025 | 0.913 |
| age_band | 60+ | 48 | 0.785 | 0.040 | 0.896 |
| region | island_and_coast | 696 | 0.741 | 0.038 | 0.881 |
| region | mainland_core | 456 | 0.700 | 0.020 | 0.895 |
| region | north_west | 336 | 0.732 | 0.030 | 0.899 |
| region | west_and_ikorodu | 480 | 0.775 | 0.020 | 0.915 |
| facility_level | primary | 960 | 0.693 | 0.032 | 0.884 |
| facility_level | secondary | 696 | 0.775 | 0.026 | 0.907 |
| facility_level | tertiary | 312 | 0.782 | 0.028 | 0.904 |
| language | en | 672 | 0.738 | 0.020 | 0.911 |
| language | ha | 72 | 0.711 | 0.059 | 0.847 |
| language | ig | 240 | 0.768 | 0.039 | 0.863 |
| language | pcm | 336 | 0.815 | 0.030 | 0.896 |
| language | yo | 648 | 0.687 | 0.027 | 0.897 |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.006, coverage 0.009 |
| age_band | auroc 0.194, coverage 0.044 |
| region | auroc 0.075, coverage 0.034 |
| facility_level | auroc 0.089, coverage 0.022 |
| language | auroc 0.128, coverage 0.063 |

Flags: age_band: auroc disparity 0.194 > 0.05; region: auroc disparity 0.075 > 0.05; facility_level: auroc disparity 0.089 > 0.05; language: auroc disparity 0.128 > 0.05; language: coverage disparity 0.063 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
