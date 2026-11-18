# ahdt.integumentary.heat_stress

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | integumentary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Heat index of the person's environment and core temperature |
| Regulatory status | research |
| Source | Rothfusz LP. The heat index equation (or, more than you ever wanted to know about heat index). NWS Southern Region Technical Attachment SR 90-23. National Weather Service; 1990 |
| Validation | NWS heat index table: 90 degF at 60 % relative humidity reads 100 degF: heat_index_error_degf = -0.322282 (tolerance 0.6, passed) |

## Inputs

- `air_temperature` (Cel) from `connector:ExposomeConnector#temp_c`
- `relative_humidity` (%) from `connector:ExposomeConnector#humidity`
- `core_temp` (Cel) from `model:ahdt.integumentary.thermoregulation#core_temp`

## Outputs

- `heat_index` (Cel)
- `core_temp` (Cel)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `c1` | -42.379 | [degF] | rothfusz1990 | published |
| `c2` | 2.04902 | 1 | rothfusz1990 | published |
| `c3` | 10.1433 | [degF]/% | rothfusz1990 | published |
| `c4` | -0.224755 | 1/% | rothfusz1990 | published |
| `c5` | -0.00683783 | /[degF] | rothfusz1990 | published |
| `c6` | -0.0548172 | [degF]/%2 | rothfusz1990 | published |
| `c7` | 0.00122874 | /[degF]/% | rothfusz1990 | published |
| `c8` | 0.00085282 | 1/%2 | rothfusz1990 | published |
| `c9` | -1.99e-06 | /[degF]/%2 | rothfusz1990 | published |

## Sources

- **rothfusz1990**: Rothfusz LP. The heat index equation (or, more than you ever wanted to know about heat index). NWS Southern Region Technical Attachment SR 90-23. National Weather Service; 1990 Via: NOAA Weather Prediction Center, The Heat Index Equation.
