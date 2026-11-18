# ahdt.cardiovascular.vascular_endothelium

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Endothelial function driven by glycaemia, blood pressure and inflammation |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.endothelial_function |

## Inputs

- `glucose` (mmol/L) from `field:15074-8`
- `sbp` (mm[Hg]) from `field:8480-6`
- `inflammation_index` (1) from `connector:InfectionHaemodynamicsConnector#inflammation_index`

## Outputs

- `endothelial_function` (1)
- `endothelial_function_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_endothelial_function` | 720 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_endothelial_function`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
