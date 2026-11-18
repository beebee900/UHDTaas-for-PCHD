# ahdt.reproductive.placenta

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | reproductive |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0001987 |
| Intended use | Placental function and gestational age |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.gestation_weeks, state.placental_function |

## Inputs

- none

## Outputs

- `placental_function` (1)
- `gestation_weeks` (wk)
- `placental_function_status` ({status})
- `gestation_weeks_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_placental_function` | 168 | h | atra-t3-dynamics | assumption |
| `tau_gestation_weeks` | 8760 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_placental_function`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_gestation_weeks`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
