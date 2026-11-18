# ahdt.population.cohort

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | population |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Cohort definitions and statistics over contributed, de-identified records |
| Regulatory status | research |
| Source | Cohort counts with small-cell suppression; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator): max_prevalence_abs_error = 0.004237 (2026-10-11) |

## Inputs

- `cohort_size` (1)

## Outputs

- `cohort_statistics` (1)

## Validation report: ahdt.population.cohort 1.0.0

atra-synthetic-population (WP02 generator): max_prevalence_abs_error = 0.004237 (2026-10-11).

| Metric | Value |
|---|---|
| max_prevalence_abs_error | 0.004237 |
| prevalence_abs_error.cond.diabetes_type2 | 0.004237 |
| prevalence_abs_error.cond.hiv | 0.000265 |
| prevalence_abs_error.cond.hypertension | 0.0008148 |

Split: persons 2000, unit person.

- Cells under 5 records are suppressed.
- Slice MAE compares the age band x sex cohort prevalence of cond.hypertension with each person's WP02 prior probability.


### Fairness slices: ahdt.population.cohort

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 1003 | 0.033 |  |  |
| sex | male | 997 | 0.032 |  |  |
| age_band | 0-4 | 304 | 0.000 |  |  |
| age_band | 18-39 | 630 | 0.064 |  |  |
| age_band | 40-59 | 294 | 0.047 |  |  |
| age_band | 5-17 | 651 | 0.000 |  |  |
| age_band | 60+ | 121 | 0.093 |  |  |
| region | island_and_coast | 567 | 0.033 |  |  |
| region | mainland_core | 509 | 0.031 |  |  |
| region | north_west | 476 | 0.031 |  |  |
| region | west_and_ikorodu | 448 | 0.035 |  |  |
| facility_level | primary | 1179 | 0.033 |  |  |
| facility_level | secondary | 623 | 0.031 |  |  |
| facility_level | tertiary | 198 | 0.034 |  |  |
| language | en | 686 | 0.034 |  |  |
| language | ha | 102 | 0.041 |  |  |
| language | ig | 199 | 0.033 |  |  |
| language | pcm | 338 | 0.030 |  |  |
| language | yo | 675 | 0.031 |  |  |

| Attribute | Disparity |
|---|---|
| sex | mae 0.001 |
| age_band | mae 0.093 |
| region | mae 0.004 |
| facility_level | mae 0.002 |
| language | mae 0.011 |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
