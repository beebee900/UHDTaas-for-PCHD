# ahdt.immune_lymphatic.inflammation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | immune_lymphatic |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Course of an acute inflammatory response and its resolution |
| Regulatory status | research |
| Source | Reynolds A, Rubin J, Clermont G, Day J, Vodovotz Y, Ermentrout GB. A reduced mathematical model of the acute inflammatory response: I. Derivation of model and analysis of anti-inflammation. J Theor Biol. 2006;242(1):220-236. doi:10.1016/j.jtbi.2006.02.016 |
| Validation | Reynolds 2006 healthy outcome from a small inoculum: final_tissue_damage = 0.000100092 (tolerance 0.05, passed) |

## Inputs

- `pathogen_inoculum` (1) from `input:scenario`
- `inoculations` (1) from `input:scenario`
- `antimicrobial_kill` (/h) from `input:treatment`

## Outputs

- `pathogen` (1)
- `activated_phagocytes` (1)
- `tissue_damage` (1)
- `anti_inflammatory` (1)
- `inflammation_index` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `k_pm` | 0.6 | /h | reynolds2006 | published |
| `k_mp` | 0.01 | 1 | reynolds2006 | published |
| `s_m` | 0.005 | /h | reynolds2006 | published |
| `mu_m` | 0.002 | /h | reynolds2006 | published |
| `k_pg` | 0.3 | /h | reynolds2006 | published |
| `p_inf` | 20 | 1 | reynolds2006 | published |
| `k_pn` | 1.8 | /h | reynolds2006 | published |
| `k_np` | 0.1 | /h | reynolds2006 | published |
| `k_nn` | 0.01 | /h | reynolds2006 | published |
| `s_nr` | 0.08 | /h | reynolds2006 | published |
| `mu_nr` | 0.12 | /h | reynolds2006 | published |
| `mu_n` | 0.05 | /h | reynolds2006 | published |
| `k_nd` | 0.02 | /h | reynolds2006 | published |
| `k_dn` | 0.35 | /h | reynolds2006 | published |
| `x_dn` | 0.06 | 1 | reynolds2006 | published |
| `mu_d` | 0.02 | /h | reynolds2006 | published |
| `c_inf` | 0.28 | 1 | reynolds2006 | published |
| `s_c` | 0.0125 | /h | reynolds2006 | published |
| `k_cn` | 0.04 | /h | reynolds2006 | published |
| `k_cnd` | 48 | 1 | reynolds2006 | published |
| `mu_c` | 0.1 | /h | reynolds2006 | published |

## Sources

- **reynolds2006**: Reynolds A, Rubin J, Clermont G, Day J, Vodovotz Y, Ermentrout GB. A reduced mathematical model of the acute inflammatory response: I. Derivation of model and analysis of anti-inflammation. J Theor Biol. 2006;242(1):220-236. doi:10.1016/j.jtbi.2006.02.016 Via: BioModels BIOMD0000000714 (HealthyOutcome.xml).
