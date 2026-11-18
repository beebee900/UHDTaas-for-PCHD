# ahdt.hepatobiliary.liver_drug_clearance_capacity

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | hepatobiliary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0002107 |
| Intended use | Hepatic clearance capacity for dose adjustment and PBPK |
| Regulatory status | research |
| Source | Rowland M, Benet LZ, Graham GG. Clearance concepts in pharmacokinetics. J Pharmacokinet Biopharm. 1973;1(2):123-136. doi:10.1007/BF01059626; Rowland M, Tozer TN. Clinical Pharmacokinetics and Pharmacodynamics: Concepts and Applications. 4th ed. Lippincott Williams and Wilkins; 2011 |
| Validation | Well-stirred model: clearance tends to hepatic blood flow at high CL_int: relative_error_flow_limit = 1.5e-06 (tolerance 1e-05, passed) |

## Inputs

- `bilirubin` (umol/L) from `field:1975-2`
- `albumin` (g/L) from `field:1751-7`
- `inr` ({INR}) from `facet:UBERON:0000178/coagulation#inr`
- `fu` (1) from `input:drug`
- `cl_int` (L/min) from `input:drug`

## Outputs

- `clearance_factor` (1)
- `child_pugh_score` (1)
- `child_pugh_class` ({class})
- `hepatic_clearance` (L/min)
- `extraction_ratio` (1)
- `clotting_factor_synthesis` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `hepatic_blood_flow` | 1.5 | L/min | rowland-tozer | unverified |

## Sources

- **rowland1973**: Rowland M, Benet LZ, Graham GG. Clearance concepts in pharmacokinetics. J Pharmacokinet Biopharm. 1973;1(2):123-136. doi:10.1007/BF01059626
- **rowland-tozer**: Rowland M, Tozer TN. Clinical Pharmacokinetics and Pharmacodynamics: Concepts and Applications. 4th ed. Lippincott Williams and Wilkins; 2011

## Open items for sign-off

- `hepatic_blood_flow`: Typical adult hepatic blood flow as recalled from Rowland and Tozer; needs a page check
