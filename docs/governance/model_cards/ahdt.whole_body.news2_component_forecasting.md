# ahdt.whole_body.news2_component_forecasting

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Forecast the next 6 h of the NEWS2 vital signs with 90 % bands |
| Regulatory status | research |
| Source | Oreshkin BN, Carpov D, Chapados N, Bengio Y. N-BEATS: neural basis expansion analysis for interpretable time series forecasting. ICLR 2020; via Darts (Herzen J et al. Darts: user-friendly modern machine learning for time series. JMLR 2022;23(124):1-6); bands: Lei J, G'Sell M, Rinaldo A, Tibshirani RJ, Wasserman L. Distribution-free predictive inference for regression. JASA 2018;113(523):1094-1111; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.respiration_rate = 2.583 (2026-10-11) |

## Inputs

- `respiratory_rate` (/min)
- `spo2` (%)
- `sbp` (mm[Hg])
- `heart_rate` (/min)
- `temperature` (Cel)

## Outputs

- `vital_sign_forecast` (1)

## Validation report: ahdt.whole_body.news2_component_forecasting 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.respiration_rate = 2.583 (2026-10-11).

| Metric | Value |
|---|---|
| coverage_90.pulse | 0.8409 |
| coverage_90.respiration_rate | 0.8977 |
| coverage_90.spo2 | 0.8712 |
| coverage_90.systolic_bp | 0.8864 |
| coverage_90.temperature | 0.8485 |
| halfwidth_90_last_step.pulse | 21.21 |
| halfwidth_90_last_step.respiration_rate | 5.333 |
| halfwidth_90_last_step.spo2 | 4.328 |
| halfwidth_90_last_step.systolic_bp | 19.58 |
| halfwidth_90_last_step.temperature | 0.7215 |
| mae.pulse | 9.885 |
| mae.respiration_rate | 2.583 |
| mae.spo2 | 1.62 |
| mae.systolic_bp | 8.669 |
| mae.temperature | 0.3624 |
| naive_mae.pulse | 9.887 |
| naive_mae.respiration_rate | 2.841 |
| naive_mae.spo2 | 1.771 |
| naive_mae.systolic_bp | 9.858 |
| naive_mae.temperature | 0.3782 |

Split: train 161, cal 54, test 44, unit person.

- Fairness rows use the mean forecast of the first output over the horizon; coverage counts a person when every step of the first output is inside its band.


### Fairness slices: ahdt.whole_body.news2_component_forecasting

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 25 | 1.997 |  | 0.760 |
| sex | male | 19 | 2.003 |  | 0.632 |
| age_band | 18-39 | 21 | 1.380 |  | 0.762 |
| age_band | 40-59 | 14 | 2.833 |  | 0.571 |
| age_band | 5-17 | 4 | 2.417 |  | 0.750 |
| age_band | 60+ | 5 | 1.933 |  | 0.800 |
| region | island_and_coast | 17 | 1.685 |  | 0.706 |
| region | mainland_core | 9 | 2.314 |  | 0.667 |
| region | north_west | 8 | 2.618 |  | 0.625 |
| region | west_and_ikorodu | 10 | 1.758 |  | 0.800 |
| facility_level | primary | 20 | 1.491 |  | 0.850 |
| facility_level | secondary | 19 | 2.076 |  | 0.632 |
| facility_level | tertiary | 5 | 3.746 |  | 0.400 |
| language | en | 19 | 2.232 |  | 0.632 |
| language | ha | 1 | 0.358 |  | 1.000 |
| language | ig | 2 | 0.922 |  | 1.000 |
| language | pcm | 4 | 1.525 |  | 0.750 |
| language | yo | 18 | 2.071 |  | 0.722 |

| Attribute | Disparity |
|---|---|
| sex |  |
| age_band |  |
| region |  |
| facility_level |  |
| language |  |

Flags: none.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
