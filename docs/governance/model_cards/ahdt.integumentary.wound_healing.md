# ahdt.integumentary.wound_healing

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | integumentary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Expected wound closure and the effect of glycaemia and perfusion |
| Regulatory status | research |
| Source | ATRA design 01 rule R5 assumption register |
| Validation | Logistic closure against its closed-form solution: healed_fraction_error = -9.24761e-07 (tolerance 0.0001, passed) |

## Inputs

- `area0` (cm2) from `input:wound_measurement`
- `hba1c` (%) from `field:4548-4`
- `perfusion_index` (1) from `input:perfusion`

## Outputs

- `healed_fraction` (1)
- `wound_area` (cm2)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `k` | 0.15 | /d | atra-assumption | assumption |
| `healed0` | 0.02 | 1 | atra-assumption | assumption |
| `hba1c_ref` | 6.5 | % | atra-assumption | assumption |
| `hba1c_slope` | 0.1 | /% | atra-assumption | assumption |

## Sources

- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `k`: Logistic closure rate of an uncomplicated wound; calibrated to the person's measured wound areas
- `healed0`: Healed fraction at the first measurement; the logistic form needs a non-zero start
- `hba1c_ref`: HbA1c above which the closure rate falls; to be replaced by a kb threshold
- `hba1c_slope`: Relative fall of the closure rate per percentage point of HbA1c above the reference
