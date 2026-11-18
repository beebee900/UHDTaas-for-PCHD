# ahdt.cardiovascular.blood_pressure_forecasting

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Forecast the next 7 days of twice-daily home SBP and DBP with 90 % bands |
| Regulatory status | research |
| Source | Oreshkin BN, Carpov D, Chapados N, Bengio Y. N-BEATS: neural basis expansion analysis for interpretable time series forecasting. ICLR 2020; via Darts (Herzen J et al. Darts: user-friendly modern machine learning for time series. JMLR 2022;23(124):1-6); bands: Lei J, G'Sell M, Rinaldo A, Tibshirani RJ, Wasserman L. Distribution-free predictive inference for regression. JASA 2018;113(523):1094-1111; trained on the ATRA synthetic population (WP02 persons; ahdt/models/ml/synthetic.yaml) |
| Training data | atra-synthetic-population (laptop) |
| Validation | atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.sbp = 4.951 (2026-10-11) |

## Inputs

- `sbp` (mm[Hg])
- `dbp` (mm[Hg])

## Outputs

- `sbp_forecast` (mm[Hg])
- `dbp_forecast` (mm[Hg])

## Validation report: ahdt.cardiovascular.blood_pressure_forecasting 1.0.0

atra-synthetic-population (WP02 generator + ahdt/models/ml/synthetic.yaml): mae.sbp = 4.951 (2026-10-11).

| Metric | Value |
|---|---|
| coverage_90.dbp | 0.8927 |
| coverage_90.sbp | 0.8949 |
| halfwidth_90_last_step.dbp | 8.005 |
| halfwidth_90_last_step.sbp | 11.31 |
| mae.dbp | 3.626 |
| mae.sbp | 4.951 |
| naive_mae.dbp | 4.99 |
| naive_mae.sbp | 6.868 |

Split: train 628, cal 224, test 193, unit person.

- Fairness rows use the mean forecast of the first output over the horizon; coverage counts a person when every step of the first output is inside its band.


### Fairness slices: ahdt.cardiovascular.blood_pressure_forecasting

Metric: mae. Slices with fewer than 20 rows are listed but not used for the disparity.

| Attribute | Slice | n | mae | ECE | Coverage |
|---|---|---|---|---|---|
| sex | female | 97 | 2.436 |  | 0.299 |
| sex | male | 96 | 2.963 |  | 0.281 |
| age_band | 18-39 | 106 | 2.802 |  | 0.264 |
| age_band | 40-59 | 62 | 2.374 |  | 0.403 |
| age_band | 60+ | 25 | 3.065 |  | 0.120 |
| region | island_and_coast | 59 | 2.464 |  | 0.220 |
| region | mainland_core | 53 | 2.513 |  | 0.377 |
| region | north_west | 38 | 2.800 |  | 0.316 |
| region | west_and_ikorodu | 43 | 3.158 |  | 0.256 |
| facility_level | primary | 100 | 2.673 |  | 0.280 |
| facility_level | secondary | 72 | 2.582 |  | 0.319 |
| facility_level | tertiary | 21 | 3.218 |  | 0.238 |
| language | en | 73 | 2.490 |  | 0.342 |
| language | ha | 9 | 2.931 |  | 0.556 |
| language | ig | 24 | 2.615 |  | 0.250 |
| language | pcm | 25 | 3.027 |  | 0.200 |
| language | yo | 62 | 2.810 |  | 0.242 |

| Attribute | Disparity |
|---|---|
| sex | mae 0.527, coverage 0.018 |
| age_band | mae 0.691, coverage 0.283 |
| region | mae 0.694, coverage 0.157 |
| facility_level | mae 0.636, coverage 0.081 |
| language | mae 0.537, coverage 0.142 |

Flags: age_band: coverage disparity 0.283 > 0.05; region: coverage disparity 0.157 > 0.05; facility_level: coverage disparity 0.081 > 0.05; language: coverage disparity 0.142 > 0.05.

These numbers come from synthetic data. They test the reporting pipeline, not real-world equity.
