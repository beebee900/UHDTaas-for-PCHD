# ahdt.integumentary.thermoregulation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | integumentary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0002097 |
| Intended use | Core and skin temperature, sweating and shivering in an environment |
| Regulatory status | research |
| Source | Gagge AP, Fobelets AP, Berglund LG. A standard predictive index of human response to the thermal environment. ASHRAE Trans. 1986;92(2B):709-731; ATRA design 01 rule R5 assumption register |
| Validation | Gagge 1986 two-node model in a neutral environment: core_temperature_shift_k = 0.0606863 (tolerance 0.2, passed) |

## Inputs

- `air_temperature` (Cel) from `connector:ExposomeConnector#temp_c`
- `relative_humidity` (%) from `connector:ExposomeConnector#humidity`
- `air_speed` (m/s) from `input:environment`
- `met` ({met}) from `input:activity`
- `clo` ({clo}) from `input:scenario`
- `fever` (K) from `input:condition`

## Outputs

- `core_temp` (Cel)
- `skin_temp` (Cel)
- `sweat_rate` (g/(m2.h))
- `skin_blood_flow` (L/(m2.h))
- `shivering` (W/m2)
- `skin_wettedness` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `body_weight` | 70 | kg | gagge1986 | published |
| `body_surface_area` | 1.8258 | m2 | gagge1986 | published |
| `met_factor` | 58.2 | W/m2 | gagge1986 | published |
| `c_sw` | 170 | g/(m2.h.K) | gagge1986 | published |
| `c_dil` | 120 | L/(m2.h.K) | gagge1986 | published |
| `c_str` | 0.5 | /K | gagge1986 | published |
| `t_skin_neutral` | 33.7 | Cel | gagge1986 | published |
| `t_core_neutral` | 36.8 | Cel | gagge1986 | published |
| `skin_blood_flow_neutral` | 6.3 | L/(m2.h) | gagge1986 | published |
| `max_skin_blood_flow` | 90 | L/(m2.h) | gagge1986 | published |
| `max_sweating` | 500 | g/(m2.h) | gagge1986 | published |
| `alfa0` | 0.1 | 1 | gagge1986 | published |
| `fever_gain` | 1 | 1 | atra-assumption | assumption |

## Sources

- **gagge1986**: Gagge AP, Fobelets AP, Berglund LG. A standard predictive index of human response to the thermal environment. ASHRAE Trans. 1986;92(2B):709-731 Via: pythermalcomfort two_nodes_gagge implementation (Tartarini and Schiavon 2020, SoftwareX 12:100578), read for the constants and update order.
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `fever_gain`: Fever modelled as an upward shift of the core set point equal to the fever input in kelvin
