# ahdt.haematological.platelets

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | haematological |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000178 |
| Intended use | Platelet count under consumption and marrow suppression |
| Regulatory status | research |
| Source | Harker LA, Finch CA. Thrombokinetics in man. J Clin Invest. 1969;48(6):963-974. doi:10.1172/JCI106077; ATRA design 01 rule R5 assumption register |
| Validation | Steady state at the person's baseline platelet count: platelet_drift = -2.92744e-11 (tolerance 0.001, passed) |

## Inputs

- `platelets0` (10*3/uL) from `field:777-3`
- `consumption_rate` (/d) from `input:condition`
- `marrow_suppression` (1) from `input:condition`

## Outputs

- `platelets` (10*3/uL)
- `platelet_production` (10*3/uL/d)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `lifespan` | 9.9 | d | harker1969 | unverified |
| `feedback_gain` | 1 | 1 | atra-assumption | assumption |
| `maturation_days` | 5 | d | atra-assumption | assumption |

## Sources

- **harker1969**: Harker LA, Finch CA. Thrombokinetics in man. J Clin Invest. 1969;48(6):963-974. doi:10.1172/JCI106077
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `lifespan`: Normal platelet survival of about 10 days as recalled from Harker and Finch; needs a check against the paper
- `feedback_gain`: Thrombopoietin feedback: production rises in proportion to the relative platelet deficit; no published gain for this reduced form
- `maturation_days`: Megakaryocyte maturation delay as a two-stage chain; to be sourced
