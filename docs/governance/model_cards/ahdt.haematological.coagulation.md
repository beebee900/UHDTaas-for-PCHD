# ahdt.haematological.coagulation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | haematological |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0000178 |
| Intended use | INR state coupled to hepatic synthesis of clotting factors |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.inr |

## Inputs

- `clotting_factor_synthesis` (1) from `facet:UBERON:0002107/haematological#clotting_factor_synthesis`

## Outputs

- `inr` ({INR})
- `inr_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_inr` | 24 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_inr`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
