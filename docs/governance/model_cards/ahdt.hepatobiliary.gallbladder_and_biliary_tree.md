# ahdt.hepatobiliary.gallbladder_and_biliary_tree

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | hepatobiliary |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002107 |
| Intended use | Cholestasis index and bile flow |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.bile_flow, state.cholestasis_index |

## Inputs

- `bilirubin` (umol/L) from `field:1975-2`

## Outputs

- `cholestasis_index` (1)
- `bile_flow` (1)
- `cholestasis_index_status` ({status})
- `bile_flow_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_cholestasis_index` | 72 | h | atra-t3-dynamics | assumption |
| `tau_bile_flow` | 24 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_cholestasis_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_bile_flow`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
