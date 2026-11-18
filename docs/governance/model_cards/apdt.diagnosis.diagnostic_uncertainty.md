# apdt.diagnosis.diagnostic_uncertainty

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Conformal prediction sets, Bayesian model averaging weights and the result that would change the top diagnosis |
| Regulatory status | research |
| Source | Split-conformal prediction; BIC model averaging (Hoeting JA et al. Stat Sci 1999;14(4):382-417) |
| Validation | not validated yet |

## Inputs

- `differential` (1)

## Outputs

- `conformal_set` ({condition})
- `bma_weight` (1)
