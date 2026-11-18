# ahdt.endocrine.glucose_forecasting

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Forecast the next 2 days of capillary glucose with 90 % bands |
| Regulatory status | research |
| Source | Oreshkin BN, Carpov D, Chapados N, Bengio Y. N-BEATS: neural basis expansion analysis for interpretable time series forecasting. ICLR 2020; via Darts (Herzen J et al. Darts: user-friendly modern machine learning for time series. JMLR 2022;23(124):1-6); bands: Lei J, G'Sell M, Rinaldo A, Tibshirani RJ, Wasserman L. Distribution-free predictive inference for regression. JASA 2018;113(523):1094-1111; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.glucose = 0.5254 (2026-10-11) |

## Inputs

- `glucose` (mmol/L)

## Outputs

- `glucose_forecast` (mmol/L)

## Validation report: ahdt.endocrine.glucose_forecasting 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.glucose = 0.5254 (2026-10-11).

| Metric | Value |
|---|---|
| coverage_90.glucose | 0.9041 |
| halfwidth_90_last_step.glucose | 1.091 |
| mae.glucose | 0.5254 |
| naive_mae.glucose | 1.085 |

Split: train 628, cal 224, test 193, unit person.

- Fairness rows use the mean forecast of the first output over the horizon; coverage counts a person when every step of the first output is inside its band.


### Fairness slices: ahdt.endocrine.glucose_forecasting

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 97 | 0.359 |  | 0.629 |
| sex | male | 96 | 0.380 |  | 0.604 |
| age_band | 18-39 | 106 | 0.406 |  | 0.547 |
| age_band | 40-59 | 62 | 0.331 |  | 0.677 |
| age_band | 60+ | 25 | 0.313 |  | 0.760 |
| region | island_and_coast | 59 | 0.414 |  | 0.542 |
| region | mainland_core | 53 | 0.341 |  | 0.642 |
| region | north_west | 38 | 0.358 |  | 0.632 |
| region | west_and_ikorodu | 43 | 0.355 |  | 0.674 |
| facility_level | primary | 100 | 0.396 |  | 0.570 |
| facility_level | secondary | 72 | 0.336 |  | 0.681 |
| facility_level | tertiary | 21 | 0.363 |  | 0.619 |
| language | en | 73 | 0.360 |  | 0.699 |
| language | ha | 9 | 0.288 |  | 0.667 |
| language | ig | 24 | 0.374 |  | 0.583 |
| language | pcm | 25 | 0.369 |  | 0.640 |
| language | yo | 62 | 0.392 |  | 0.516 |

| Attribute | Disparity |
|---|---|
| sex | mae 0.021, coverage 0.025 |
| age_band | mae 0.093, coverage 0.213 |
| region | mae 0.074, coverage 0.132 |
| facility_level | mae 0.060, coverage 0.111 |
| language | mae 0.032, coverage 0.183 |

Flags: age_band: coverage disparity 0.213 > 0.05; region: coverage disparity 0.132 > 0.05; facility_level: coverage disparity 0.111 > 0.05; language: coverage disparity 0.183 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
