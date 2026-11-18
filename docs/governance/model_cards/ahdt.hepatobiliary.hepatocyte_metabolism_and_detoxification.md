# ahdt.hepatobiliary.hepatocyte_metabolism_and_detoxification

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | hepatobiliary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0002107 |
| Intended use | Net hepatic glucose release or uptake and glycogen at a given blood glucose |
| Regulatory status | research |
| Source | Bulik S, Holzhütter HG, Berndt N. The relative importance of kinetic mechanisms and variable enzyme abundances for the regulation of hepatic glucose metabolism: insights from mathematical modeling. BMC Biol. 2016;14:15. doi:10.1186/s12915-016-0237-6 |
| Fidelity note | Rat hepatocyte kinetics; rates per litre of cell volume. Human liver volume scaling is not applied. Detoxification is carried by ahdt.hepatobiliary.liver_drug_clearance_capacity. |
| Validation | Bulik 2016 reaction network; steady state, relative drift over 1 hour: max_relative_drift = 4.28235e-15 (tolerance 0.0001, passed) |

## Inputs

- `blood_glucose` (mmol/L) from `input:scenario`

## Outputs

- `hepatic_glucose_output` (mmol/L/h)
- `glycogenolysis` (mmol/L/h)
- `gluconeogenesis` (mmol/L/h)
- `hepatocyte_glycogen` (mmol/L)
- `insulin_signal` (mmol/L)
- `glucagon_signal` (mmol/L)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `reference_blood_glucose` | 4 | mmol/L | bulik2016 | published |

## Sources

- **bulik2016**: Bulik S, Holzhütter HG, Berndt N. The relative importance of kinetic mechanisms and variable enzyme abundances for the regulation of hepatic glucose metabolism: insights from mathematical modeling. BMC Biol. 2016;14:15. doi:10.1186/s12915-016-0237-6 Via: BioModels BIOMD0000000633, curated, CC0 1.0, SBML L2V4, sha256 ca360484d69831e4e334562b000e3113fa93cbe70617ca1d06298e2efee6a538.
