# ahdt.whole_body.life_course_and_ageing

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Frailty trajectory, biological age and mortality hazard |
| Regulatory status | research |
| Source | Mitnitski AB, Graham JE, Mogilner AJ, Rockwood K. Frailty, fitness and late-life mortality in relation to chronological and biological age. BMC Geriatr. 2002;2:1. doi:10.1186/1471-2318-2-1 |
| Validity | {'age_years': [65, 100], 'population': 'community-dwelling older adults'} |
| Validation | Mitnitski 2002 equation 1 worked values at 67, 77 and 87 years: max_abs_error = 0.00339304 (tolerance 0.01, passed) |

## Inputs

- `age` (a) from `input:demographics`
- `frailty_index` (1) from `input:assessment`

## Outputs

- `expected_frailty_index` (1)
- `biological_age` (a)
- `mortality_hazard` (/a)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `ln_q_intercept` | -4.23 | 1 | mitnitski2002 | published |
| `ln_q_slope` | 0.03 | /a | mitnitski2002 | published |

## Sources

- **mitnitski2002**: Mitnitski AB, Graham JE, Mogilner AJ, Rockwood K. Frailty, fitness and late-life mortality in relation to chronological and biological age. BMC Geriatr. 2002;2:1. doi:10.1186/1471-2318-2-1 Via: Europe PMC PMC88955, equation 1.
