# ahdt.population.in_silico_trial

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | population |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Paired comparison of an antihypertensive scenario on a virtual cohort of twins |
| Regulatory status | research |
| Source | ATRA design 01 rule R5 assumption register; the heart model ahdt.cardiovascular.heart_chambers_and_valves |
| Fidelity note | The virtual cohort is drawn around the published heart parameters and an assumed resistance distribution. Differences between arms are model results, not trial evidence. |

## Inputs

- `subjects` ({persons}) from `input:scenario`
- `seed` (1) from `input:scenario`

## Outputs

- `control_mean_sbp` (mm[Hg])
- `treated_mean_sbp` (mm[Hg])
- `mean_difference` (mm[Hg])
- `controlled_share_control` (1)
- `controlled_share_treated` (1)
- `responder_share_10mmhg` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `resistance_factor_mean` | 1.35 | 1 | atra-assumption | assumption |
| `resistance_factor_sd` | 0.1 | 1 | atra-assumption | assumption |
| `treatment_resistance_reduction` | 0.14 | 1 | atra-assumption | assumption |

## Sources

- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `resistance_factor_mean`: Systemic resistance factor of a hypertensive virtual twin; the value the synthetic population uses for persons with hypertension, tuned so that they sit above 140/90 mmHg with the published heart parameters.
- `resistance_factor_sd`: Spread of the resistance factor between virtual twins; the value of the synthetic population.
- `treatment_resistance_reduction`: Relative fall of systemic resistance on the trial drug; two titration steps of the synthetic therapy trajectories. A simulator parameter, not a drug effect.
