# ahdt.digestive.microbiome

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | digestive |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | atra:microbiome |
| Intended use | Gut microbiome diversity and dysbiosis |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.diversity_index, state.dysbiosis |

## Inputs

- `antibiotic_course` (1) from `input:medications`

## Outputs

- `diversity_index` (1)
- `dysbiosis` (1)
- `diversity_index_status` ({status})
- `dysbiosis_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_diversity_index` | 336 | h | atra-t3-dynamics | assumption |
| `tau_dysbiosis` | 336 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_diversity_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_dysbiosis`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
