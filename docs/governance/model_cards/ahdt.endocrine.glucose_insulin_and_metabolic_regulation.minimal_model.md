# ahdt.endocrine.glucose_insulin_and_metabolic_regulation.minimal_model

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001264 |
| Intended use | Insulin sensitivity and glucose effectiveness from an FSIGT |
| Regulatory status | research |
| Source | Bergman RN, Ider YZ, Bowden CR, Cobelli C. Quantitative estimation of insulin sensitivity. Am J Physiol. 1979;236(6):E667-E677. doi:10.1152/ajpendo.1979.236.6.E667; Pacini G, Bergman RN. MINMOD: a computer program to calculate insulin sensitivity and pancreatic responsivity from the frequently sampled intravenous glucose tolerance test. Comput Methods Programs Biomed. 1986;23(2):113-122. doi:10.1016/0169-2607(86)90106-9 |
| Validity | {'test': 'frequently sampled intravenous glucose tolerance test'} |
| Validation | Pacini and Bergman 1986 FSIGT (published least-squares fit): max_relative_error_p1_p2_p3 = 0.0533898 (tolerance 0.1, passed) |

## Inputs

- none

## Outputs

- `glucose_mgdl` (mg/dL)
- `insulin` (u[IU]/mL)
- `remote_insulin` (/min)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `p1` | 0.0135258 | /min | pacini1986 | published |
| `p2` | 0.0612416 | /min | pacini1986 | published |
| `p3` | 2.30248e-05 | mL/uU/min2 | pacini1986 | published |
| `n` | 0.272368 | /min | pacini1986 | published |
| `gamma` | 0.00424795 | uU/mL/min2 per mg/dL | pacini1986 | published |
| `h` | 80.2671 | mg/dL | pacini1986 | published |
| `G_b` | 80.2671 | mg/dL | pacini1986 | published |
| `I_b` | 7 | uU/mL | pacini1986 | published |
| `G_0` | 294.868 | mg/dL | pacini1986 | published |
| `I_0` | 373.09 | uU/mL | pacini1986 | published |

## Sources

- **bergman1979**: Bergman RN, Ider YZ, Bowden CR, Cobelli C. Quantitative estimation of insulin sensitivity. Am J Physiol. 1979;236(6):E667-E677. doi:10.1152/ajpendo.1979.236.6.E667
- **pacini1986**: Pacini G, Bergman RN. MINMOD: a computer program to calculate insulin sensitivity and pancreatic responsivity from the frequently sampled intravenous glucose tolerance test. Comput Methods Programs Biomed. 1986;23(2):113-122. doi:10.1016/0169-2607(86)90106-9 Via: Knott GD. Minimal models for glucose and insulin. MLAB application note, Civilized Software Inc. (FSIGT data of Pacini and Bergman 1986 and the combined-model fit).
