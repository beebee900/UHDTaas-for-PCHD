# apdt.diagnosis.test_policy_tree

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Decision tree distilled from the test-selection policy for offline use in the CHW app |
| Regulatory status | research |
| Source | CART (Breiman L et al. 1984) distilled from the value-of-information policy; trained on the ATRA synthetic cohort (evaluation/models/apdt) |
| Validation | not validated yet |

## Inputs

- `findings` ({finding})

## Outputs

- `next_test` ({test})
