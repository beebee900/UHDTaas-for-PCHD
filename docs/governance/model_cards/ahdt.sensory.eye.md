# ahdt.sensory.eye

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | sensory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0000970 |
| Intended use | Visual acuity and lens opacity state |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.visual_acuity_logmar, state.lens_opacity |

## Inputs

- none

## Outputs

- `visual_acuity_logmar` ({logMAR})
- `lens_opacity` (1)
- `visual_acuity_logmar_status` ({status})
- `lens_opacity_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_visual_acuity_logmar` | 4380 | h | atra-t3-dynamics | assumption |
| `tau_lens_opacity` | 4380 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_visual_acuity_logmar`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_lens_opacity`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
