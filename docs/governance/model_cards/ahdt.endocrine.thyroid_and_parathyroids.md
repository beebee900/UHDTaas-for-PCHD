# ahdt.endocrine.thyroid_and_parathyroids

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002046 |
| Intended use | TSH, free T4, PTH and calcium state against reference ranges |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.tsh, state.calcium, state.ft4, state.pth, state.tsh_drive |

## Inputs

- none

## Outputs

- `tsh` (m[IU]/L)
- `tsh_drive` (1)
- `ft4` (pmol/L)
- `pth` (pmol/L)
- `calcium` (mmol/L)
- `tsh_status` ({status})
- `tsh_drive_status` ({status})
- `ft4_status` ({status})
- `pth_status` ({status})
- `calcium_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_tsh` | 168 | h | atra-t3-dynamics | assumption |
| `tau_tsh_drive` | 24 | h | atra-t3-dynamics | assumption |
| `tau_ft4` | 168 | h | atra-t3-dynamics | assumption |
| `tau_pth` | 24 | h | atra-t3-dynamics | assumption |
| `tau_calcium` | 24 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_tsh`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_tsh_drive`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_ft4`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_pth`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_calcium`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
