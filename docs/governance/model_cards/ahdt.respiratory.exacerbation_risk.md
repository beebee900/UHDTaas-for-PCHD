# ahdt.respiratory.exacerbation_risk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Probability of an asthma or COPD exacerbation in the next 14 days |
| Regulatory status | research |
| Source | Ke G, Meng Q, Finley T, et al. LightGBM: a highly efficient gradient boosting decision tree. NeurIPS 2017; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.7694 (2026-10-11) |

## Inputs

- `pef` (L/min)
- `pm25` (ug/m3)

## Outputs

- `exacerbation_risk` (1)

## Validation report: ahdt.respiratory.exacerbation_risk 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): auroc = 0.7694 (2026-10-11).

| Metric | Value |
|---|---|
| auroc | 0.7694 |
| brier | 0.07774 |
| coverage_90 | 0.8917 |
| ece | 0.05093 |
| mean_set_size | 0.9702 |
| operating_threshold | 0.009972 |
| prevalence_test | 0.1012 |
| sensitivity | 0.9529 |
| specificity | 0.2517 |

Split: train 3800, cal 1480, test 840, unit hdt_id.


### Fairness slices: ahdt.respiratory.exacerbation_risk

Metric: auroc. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | auroc | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 320 | 0.844 | 0.033 | 0.928 |
| sex | male | 520 | 0.726 | 0.062 | 0.869 |
| age_band | 0-4 | 160 | 0.699 | 0.061 | 0.906 |
| age_band | 18-39 | 280 | 0.793 | 0.041 | 0.896 |
| age_band | 40-59 | 80 | 0.722 | 0.125 | 0.850 |
| age_band | 5-17 | 280 | 0.804 | 0.052 | 0.889 |
| age_band | 60+ | 40 | 0.674 | 0.106 | 0.900 |
| region | island_and_coast | 200 | 0.773 | 0.065 | 0.870 |
| region | mainland_core | 160 | 0.685 | 0.064 | 0.881 |
| region | north_west | 280 | 0.790 | 0.043 | 0.907 |
| region | west_and_ikorodu | 200 | 0.796 | 0.063 | 0.900 |
| facility_level | primary | 480 | 0.767 | 0.059 | 0.883 |
| facility_level | secondary | 360 | 0.787 | 0.042 | 0.903 |
| language | en | 440 | 0.801 | 0.036 | 0.911 |
| language | ig | 120 | 0.736 | 0.080 | 0.867 |
| language | pcm | 120 | 0.773 | 0.082 | 0.850 |
| language | yo | 160 | 0.721 | 0.083 | 0.887 |

| Attribute | Disparity |
|---|---|
| sex | auroc 0.118, coverage 0.059 |
| age_band | auroc 0.130, coverage 0.056 |
| region | auroc 0.111, coverage 0.037 |
| facility_level | auroc 0.020, coverage 0.019 |
| language | auroc 0.079, coverage 0.061 |

Flags: sex: auroc disparity 0.118 > 0.05; sex: coverage disparity 0.059 > 0.05; age_band: auroc disparity 0.130 > 0.05; age_band: coverage disparity 0.056 > 0.05; region: auroc disparity 0.111 > 0.05; language: auroc disparity 0.079 > 0.05; language: coverage disparity 0.061 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
