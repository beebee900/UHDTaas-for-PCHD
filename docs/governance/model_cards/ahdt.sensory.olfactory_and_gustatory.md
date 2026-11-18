# ahdt.sensory.olfactory_and_gustatory

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | sensory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002268 |
| Intended use | Smell and taste function scores |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.olfaction_score, state.taste_score |

## Inputs

- none

## Outputs

- `olfaction_score` ({score})
- `taste_score` ({score})
- `olfaction_score_status` ({status})
- `taste_score_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_olfaction_score` | 720 | h | atra-t3-dynamics | assumption |
| `tau_taste_score` | 720 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_olfaction_score`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_taste_score`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
