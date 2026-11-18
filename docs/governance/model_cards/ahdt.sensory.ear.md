# ahdt.sensory.ear

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | sensory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0001690 |
| Intended use | Hearing threshold and vestibular balance state |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.hearing_threshold, range.vestibular_score |

## Inputs

- none

## Outputs

- `hearing_threshold` (dB)
- `vestibular_score` ({score})
- `hearing_threshold_status` ({status})
- `vestibular_score_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_hearing_threshold` | 4380 | h | atra-t3-dynamics | assumption |
| `tau_vestibular_score` | 168 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_hearing_threshold`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_vestibular_score`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
