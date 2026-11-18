# ahdt.renal_urinary.ureters_bladder_and_urethra

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | renal_urinary |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0001255 |
| Intended use | Bladder volume, urinary tract obstruction and symptoms |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.bladder_volume, state.obstruction, state.urinary_symptoms |

## Inputs

- none

## Outputs

- `bladder_volume` (mL)
- `obstruction` (1)
- `urinary_symptoms` ({score})
- `bladder_volume_status` ({status})
- `obstruction_status` ({status})
- `urinary_symptoms_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_bladder_volume` | 2 | h | atra-t3-dynamics | assumption |
| `tau_obstruction` | 72 | h | atra-t3-dynamics | assumption |
| `tau_urinary_symptoms` | 48 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_bladder_volume`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_obstruction`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_urinary_symptoms`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
