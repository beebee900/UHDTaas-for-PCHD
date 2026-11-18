# ahdt.renal_urinary.kidney_and_renal_function

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | renal_urinary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0002113 |
| Intended use | eGFR, creatinine trajectory and AKI staging |
| Regulatory status | research |
| Source | Inker LA, Eneanya ND, Coresh J, et al. New creatinine- and cystatin C-based equations to estimate GFR without race. N Engl J Med. 2021;385(19):1737-1749. doi:10.1056/NEJMoa2102953; Watson PE, Watson ID, Batt RD. Total body water volumes for adult males and females estimated from simple anthropometric measurements. Am J Clin Nutr. 1980;33(1):27-39. doi:10.1093/ajcn/33.1.27; Mosteller RD. Simplified calculation of body-surface area. N Engl J Med. 1987;317(17):1098. doi:10.1056/NEJM198710223171717; Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021 |
| Validity | {'age_years': [18, 100]} |
| Validation | CKD-EPI 2021 equation; serum creatinine 1.0 mg/dL, male, 50 years: relative_error_egfr = 0 (tolerance 1e-09, passed) |

## Inputs

- `age` (a) from `input:demographics`
- `female` (1) from `input:demographics`
- `height` (cm) from `field:8302-2`
- `weight` (kg) from `field:29463-7`
- `baseline_creatinine` (umol/L) from `input:history`
- `cardiac_output` (L/min) from `facet:UBERON:0000948/haemodynamics#cardiac_output`
- `haematocrit` (%) from `field:4544-3`

## Outputs

- `creatinine` (umol/L)
- `egfr` (mL/min/{1.73_m2})
- `creatinine_clearance` (mL/min)
- `aki_stage` (1)
- `filtration_fraction` (1)
- `gfr_factor` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `ckd_a` | 142 | mL/min/{1.73_m2} | inker2021 | published |
| `kappa_f` | 0.7 | mg/dL | inker2021 | published |
| `kappa_m` | 0.9 | mg/dL | inker2021 | published |
| `alpha_f` | -0.241 | 1 | inker2021 | published |
| `alpha_m` | -0.302 | 1 | inker2021 | published |
| `beta` | -1.2 | 1 | inker2021 | published |
| `age_base` | 0.9938 | 1 | inker2021 | published |
| `female_factor` | 1.012 | 1 | inker2021 | published |
| `creatinine_mw_factor` | 88.4 | umol/mg.dL/L | inker2021 | published |
| `gfr_factor` | 1 | 1 | inker2021 | published |
| `renal_share` | 0.22 | 1 | guyton | unverified |

## Sources

- **inker2021**: Inker LA, Eneanya ND, Coresh J, et al. New creatinine- and cystatin C-based equations to estimate GFR without race. N Engl J Med. 2021;385(19):1737-1749. doi:10.1056/NEJMoa2102953
- **watson1980**: Watson PE, Watson ID, Batt RD. Total body water volumes for adult males and females estimated from simple anthropometric measurements. Am J Clin Nutr. 1980;33(1):27-39. doi:10.1093/ajcn/33.1.27
- **mosteller1987**: Mosteller RD. Simplified calculation of body-surface area. N Engl J Med. 1987;317(17):1098. doi:10.1056/NEJM198710223171717
- **guyton**: Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021

## Open items for sign-off

- `renal_share`: Basal renal blood flow 1100 of 5000 mL/min as recalled from the Guyton and Hall table; needs a page check
