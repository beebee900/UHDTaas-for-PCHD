# ahdt.respiratory.diaphragm

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Respiratory muscle fatigue index |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.muscle_fatigue_index |

## Inputs

- `minute_ventilation` (L/min) from `model:ahdt.respiratory.lungs_and_gas_exchange#minute_ventilation`

## Outputs

- `muscle_fatigue_index` (1)
- `muscle_fatigue_index_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_muscle_fatigue_index` | 12 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_muscle_fatigue_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
