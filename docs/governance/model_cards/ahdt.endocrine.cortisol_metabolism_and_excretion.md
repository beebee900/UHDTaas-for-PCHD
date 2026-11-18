# ahdt.endocrine.cortisol_metabolism_and_excretion

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Fate of a cortisol dose: circulation, metabolism, urine and bile |
| Regulatory status | research |
| Source | Kraan GP, Drayer NM, de Bruin R. Kinetics of cortisol metabolism and excretion. A hypothetic model based on the cumulative urinary radioactivity in eight multiple pituitary deficient patients. J Steroid Biochem Mol Biol. 1992;42(2):169-177. doi:10.1016/0960-0760(92)90025-E |
| Fidelity note | Tracer kinetics in fractions of the dose. The model clears the circulation with a half-life of 37.5 min; the source reports 30 min for the label. |
| Validation | Kraan 1992 compartments; the fractions of the dose add up to the dose: max_mass_balance_error = 1.23191e-08 (tolerance 1e-06, passed) |

## Inputs

- none

## Outputs

- `cortisol_circulating_fraction` (1)
- `cortisol_tissue_fraction` (1)
- `cortisol_biliary_fraction` (1)
- `cortisol_urinary_fraction` (1)
- `cortisol_nonurinary_fraction` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `K1` | 3.6 | 1/d | kraan1992 | published |
| `K2` | 1.2 | 1/d | kraan1992 | published |
| `K3` | 26.6 | 1/d | kraan1992 | published |
| `K4` | 1.2 | 1/d | kraan1992 | published |
| `K5` | 1.2 | 1/d | kraan1992 | published |

## Sources

- **kraan1992**: Kraan GP, Drayer NM, de Bruin R. Kinetics of cortisol metabolism and excretion. A hypothetic model based on the cumulative urinary radioactivity in eight multiple pituitary deficient patients. J Steroid Biochem Mol Biol. 1992;42(2):169-177. doi:10.1016/0960-0760(92)90025-E Via: BioModels BIOMD0000000916, curated, CC0 1.0, SBML L2V4, sha256 f16b05b77ce9a873421cb06079e02d5ab6e19319502a457446cfcf1c516d2cb9.
