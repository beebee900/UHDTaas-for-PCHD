# ahdt.population.population_priors_and_norms

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | population |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Prevalence by condition x age band x sex x season x region and field percentiles, with a differentially private federated update |
| Regulatory status | research |
| Source | Beta-smoothed prevalence tables with Laplace noise per tenant; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator): mean_brier_dp = 0.04087 (2026-10-11) |

## Inputs

- `cohort_size` (1)

## Outputs

- `prevalence` (1)
- `field_percentiles` (1)

## Validation report: ahdt.population.population_priors_and_norms 1.0.0

atra-synthetic-population (WP02 generator): mean_brier_dp = 0.04087 (2026-10-11).

| Metric | Value |
|---|---|
| brier.dp.cond.diabetes_type2 | 0.02548 |
| brier.dp.cond.diabetes_type2.baseline | 0.02447 |
| brier.dp.cond.hiv | 0.007606 |
| brier.dp.cond.hiv.baseline | 0.006879 |
| brier.dp.cond.hypertension | 0.08793 |
| brier.dp.cond.hypertension.baseline | 0.1341 |
| brier.dp.cond.malaria_falciparum | 0.04245 |
| brier.dp.cond.malaria_falciparum.baseline | 0.04253 |
| brier.exact.cond.diabetes_type2 | 0.02213 |
| brier.exact.cond.diabetes_type2.baseline | 0.02228 |
| brier.exact.cond.hiv | 0.005108 |
| brier.exact.cond.hiv.baseline | 0.005055 |
| brier.exact.cond.hypertension | 0.08664 |
| brier.exact.cond.hypertension.baseline | 0.1344 |
| brier.exact.cond.malaria_falciparum | 0.04218 |
| brier.exact.cond.malaria_falciparum.baseline | 0.04248 |
| p05_p95_coverage.glucose | 0.8808 |
| p05_p95_coverage.sbp | 0.8964 |

Split: tenants 3, unit person.

- Slice MAE: the differentially private hypertension prior against the 0/1 outcome. Slice coverage: all field values inside p05 to p95.
- Federated update: Laplace noise with epsilon 1.0 per tenant and cell, numpy implementation.


### Fairness slices: ahdt.population.population_priors_and_norms

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 97 | 0.349 |  | 0.794 |
| sex | male | 96 | 0.334 |  | 0.781 |
| age_band | 18-39 | 106 | 0.206 |  | 0.783 |
| age_band | 40-59 | 62 | 0.517 |  | 0.839 |
| age_band | 60+ | 25 | 0.483 |  | 0.680 |
| region | island_and_coast | 59 | 0.297 |  | 0.797 |
| region | mainland_core | 53 | 0.402 |  | 0.792 |
| region | north_west | 38 | 0.310 |  | 0.789 |
| region | west_and_ikorodu | 43 | 0.357 |  | 0.767 |
| facility_level | primary | 100 | 0.322 |  | 0.790 |
| facility_level | secondary | 72 | 0.370 |  | 0.792 |
| facility_level | tertiary | 21 | 0.337 |  | 0.762 |
| language | en | 73 | 0.380 |  | 0.699 |
| language | ha | 9 | 0.323 |  | 0.778 |
| language | ig | 24 | 0.292 |  | 0.875 |
| language | pcm | 25 | 0.334 |  | 0.800 |
| language | yo | 62 | 0.322 |  | 0.855 |

| Attribute | Disparity |
|---|---|
| sex | mae 0.015, coverage 0.013 |
| age_band | mae 0.311, coverage 0.159 |
| region | mae 0.105, coverage 0.029 |
| facility_level | mae 0.048, coverage 0.030 |
| language | mae 0.087, coverage 0.176 |

Flags: age_band: coverage disparity 0.159 > 0.05; language: coverage disparity 0.176 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
