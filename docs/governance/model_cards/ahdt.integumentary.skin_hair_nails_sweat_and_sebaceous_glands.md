# ahdt.integumentary.skin_hair_nails_sweat_and_sebaceous_glands

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | integumentary |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002097 |
| Intended use | Skin barrier integrity state |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.barrier_integrity |

## Inputs

- `wound_area` (cm2) from `model:ahdt.integumentary.wound_healing#wound_area`

## Outputs

- `barrier_integrity` (1)
- `barrier_integrity_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_barrier_integrity` | 72 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_barrier_integrity`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
