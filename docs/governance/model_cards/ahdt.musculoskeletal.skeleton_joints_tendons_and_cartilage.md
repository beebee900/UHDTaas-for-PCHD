# ahdt.musculoskeletal.skeleton_joints_tendons_and_cartilage

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | musculoskeletal |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0001434 |
| Intended use | Range of motion, joint pain, strength and connective tissue state |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.cartilage_integrity, state.fatigue, state.joint_pain, state.muscle_strength, state.range_of_motion, state.tendon_stiffness |

## Inputs

- none

## Outputs

- `range_of_motion` (deg)
- `joint_pain` ({score})
- `muscle_strength` (1)
- `fatigue` (1)
- `tendon_stiffness` (1)
- `cartilage_integrity` (1)
- `range_of_motion_status` ({status})
- `joint_pain_status` ({status})
- `muscle_strength_status` ({status})
- `fatigue_status` ({status})
- `tendon_stiffness_status` ({status})
- `cartilage_integrity_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_range_of_motion` | 336 | h | atra-t3-dynamics | assumption |
| `tau_joint_pain` | 48 | h | atra-t3-dynamics | assumption |
| `tau_muscle_strength` | 336 | h | atra-t3-dynamics | assumption |
| `tau_fatigue` | 12 | h | atra-t3-dynamics | assumption |
| `tau_tendon_stiffness` | 720 | h | atra-t3-dynamics | assumption |
| `tau_cartilage_integrity` | 8760 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_range_of_motion`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_joint_pain`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_muscle_strength`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_fatigue`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_tendon_stiffness`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_cartilage_integrity`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
