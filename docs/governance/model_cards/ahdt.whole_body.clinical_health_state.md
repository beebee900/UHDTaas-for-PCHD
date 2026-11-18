# ahdt.whole_body.clinical_health_state

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Posterior over the clinical state (stable, deteriorating, critical, recovering) from NEWS2, the problem list and the vital-sign statuses |
| Regulatory status | research |
| Source | Rabiner LR. A tutorial on hidden Markov models and selected applications in speech recognition. Proc IEEE 1989;77(2):257-286; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): macro_f1_filtered = 0.8667 (2026-10-11) |

## Inputs

- `news2` (1)

## Outputs

- `clinical_state_probability` (1)

## Validation report: ahdt.whole_body.clinical_health_state 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): macro_f1_filtered = 0.8667 (2026-10-11).

| Metric | Value |
|---|---|
| accuracy_filtered | 0.9013 |
| macro_f1_filtered | 0.8667 |

Split: train 161, cal 54, test 44, unit ward stay.

- Filtered (forward) posteriors, as used online; NEWS2 from kb news2.scoring with every patient alert and on air.


### Fairness slices: ahdt.whole_body.clinical_health_state

Metric: macro_f1. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | macro_f1 | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 2400 | 0.869 | 0.037 |  |
| sex | male | 1824 | 0.862 | 0.057 |  |
| age_band | 18-39 | 2016 | 0.844 | 0.050 |  |
| age_band | 40-59 | 1344 | 0.901 | 0.021 |  |
| age_band | 5-17 | 384 | 0.865 | 0.074 |  |
| age_band | 60+ | 480 | 0.859 | 0.079 |  |
| region | island_and_coast | 1632 | 0.847 | 0.065 |  |
| region | mainland_core | 864 | 0.883 | 0.010 |  |
| region | north_west | 768 | 0.834 | 0.052 |  |
| region | west_and_ikorodu | 960 | 0.878 | 0.045 |  |
| facility_level | primary | 1920 | 0.891 | 0.036 |  |
| facility_level | secondary | 1824 | 0.837 | 0.063 |  |
| facility_level | tertiary | 480 | 0.853 | 0.010 |  |
| language | en | 1824 | 0.865 | 0.065 |  |
| language | ha | 96 | 1.000 | 0.007 |  |
| language | ig | 192 | 0.839 | 0.019 |  |
| language | pcm | 384 | 0.791 | 0.029 |  |
| language | yo | 1728 | 0.858 | 0.042 |  |

| Attribute | Disparity |
|---|---|
| sex | macro_f1 0.008 |
| age_band | macro_f1 0.056 |
| region | macro_f1 0.048 |
| facility_level | macro_f1 0.054 |
| language | macro_f1 0.209 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
