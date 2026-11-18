# ahdt.nervous.pain

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | nervous |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Pain intensity from self-report coupled to inflammation |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.pain_nrs |

## Inputs

- `inflammation_index` (1) from `connector:InfectionNeuroConnector#inflammation_index`

## Outputs

- `pain_nrs` ({score})
- `pain_nrs_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_pain_nrs` | 6 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_pain_nrs`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
