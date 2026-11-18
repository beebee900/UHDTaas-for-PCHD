# ahdt.musculoskeletal.bone_remodelling_and_density

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | musculoskeletal |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001434 |
| Intended use | Bone mass change over remodelling cycles and its density trend |
| Regulatory status | research |
| Source | Komarova SV, Smith RJ, Dixon SJ, Sims SM, Wahl LM. Mathematical model predicts a critical role for osteoclast autocrine regulation in the control of bone remodeling. Bone. 2003;33(2):206-215. doi:10.1016/S8756-3282(03)00157-1 |
| Validation | Komarova 2003 single remodelling cycle; bone mass restored: bone_mass_change_pct = -0.101543 (tolerance 0.5, passed) |

## Inputs

- `bmd0` (g/cm2) from `field:38265-5`

## Outputs

- `osteoclasts` (1)
- `osteoblasts` (1)
- `bone_mass` (%)
- `bone_density` (g/cm2)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `alpha1` | 3 | /d | komarova2003 | published |
| `alpha2` | 4 | /d | komarova2003 | published |
| `beta1` | 0.2 | /d | komarova2003 | published |
| `beta2` | 0.02 | /d | komarova2003 | published |
| `g11` | 0.5 | 1 | komarova2003 | published |
| `g12` | 1 | 1 | komarova2003 | published |
| `g21` | -0.5 | 1 | komarova2003 | published |
| `g22` | 0 | 1 | komarova2003 | published |
| `k1` | 0.24 | %/cell/d | komarova2003 | published |
| `k2` | 0.0017 | %/cell/d | komarova2003 | published |
| `x1_0` | 10.0607 | cells | komarova2003 | published |
| `x2_0` | 212.132 | cells | komarova2003 | published |

## Sources

- **komarova2003**: Komarova SV, Smith RJ, Dixon SJ, Sims SM, Wahl LM. Mathematical model predicts a critical role for osteoclast autocrine regulation in the control of bone remodeling. Bone. 2003;33(2):206-215. doi:10.1016/S8756-3282(03)00157-1 Via: Physiome Model Repository, komarova_2003.cellml.
