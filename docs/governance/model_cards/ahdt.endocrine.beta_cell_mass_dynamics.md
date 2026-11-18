# ahdt.endocrine.beta_cell_mass_dynamics

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001264 |
| Intended use | Beta-cell mass adaptation to glucose over months and its failure in diabetes |
| Regulatory status | research |
| Source | Topp B, Promislow K, deVries G, Miura RM, Finegood DT. A model of beta-cell mass, insulin, and glucose kinetics: pathways to diabetes. J Theor Biol. 2000;206(4):605-619. doi:10.1006/jtbi.2000.2150 |
| Fidelity note | The pinned SBML carries no unit definitions; units follow the published model: mg/dL, uU/mL, mg and days. |
| Validation | Topp 2000 equations; stable fixed point, relative drift over 10 days: max_relative_drift = 0 (tolerance 0.0001, passed) |

## Inputs

- `insulin_sensitivity` (mL/uU/d) from `input:scenario`

## Outputs

- `beta_cell_mass` (mg)
- `islet_glucose` (mg/dL)
- `islet_insulin` (uU/mL)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `si` | 0.72 | mL/uU/d | topp2000 | published |
| `Eg0` | 1.44 | 1/d | topp2000 | published |
| `R0` | 864 | mg/dL/d | topp2000 | published |
| `sigma` | 43.2 | uU/mg/d | topp2000 | published |
| `alpha` | 20000 | mg2/dL2 | topp2000 | published |
| `k` | 432 | 1/d | topp2000 | published |
| `d0` | 0.06 | 1/d | topp2000 | published |
| `r1` | 0.00084 | 1/d/(mg/dL) | topp2000 | published |
| `r2` | 2.4e-06 | 1/d/(mg/dL)2 | topp2000 | published |

## Sources

- **topp2000**: Topp B, Promislow K, deVries G, Miura RM, Finegood DT. A model of beta-cell mass, insulin, and glucose kinetics: pathways to diabetes. J Theor Biol. 2000;206(4):605-619. doi:10.1006/jtbi.2000.2150 Via: BioModels BIOMD0000000341, curated, CC0 1.0, SBML L2V4, sha256 e86507d1dc05cbc37d5145eaaafb0ac627ba6f71d69652b3c72a9d129e15851a.
