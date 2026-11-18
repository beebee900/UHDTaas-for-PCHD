# ahdt.immune_lymphatic.infection_response

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | immune_lymphatic |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Course of malaria, bacterial, HIV and TB infection under treatment |
| Regulatory status | research |
| Source | Hoshen MB, Heinrich R, Stein WD, Ginsburg H. Mathematical modelling of the within-host dynamics of Plasmodium falciparum. Parasitology. 2000;121(3):227-235. doi:10.1017/S0031182099006368; Perelson AS, Kirschner DE, De Boer R. Dynamics of HIV infection of CD4+ T cells. Math Biosci. 1993;114(1):81-125. doi:10.1016/0025-5564(93)90043-a; ATRA design 01 rule R5 assumption register |
| Validation | Hoshen 2000 delay model; multiplication per 48 h cycle: relative_error_cycle_multiplication = 0.000352251 (tolerance 0.05, passed) |

## Inputs

- `rbc` (10*6/uL) from `field:789-8`
- `merozoite_release` (/uL) from `input:scenario`
- `antimalarial_kill` (/d) from `input:treatment`
- `bacterial_inoculum` (1) from `input:scenario`
- `antimicrobial_kill` (/h) from `input:treatment`
- `hiv` (1) from `input:condition`
- `art_efficacy` (1) from `input:treatment`
- `tb_active` (1) from `input:condition`
- `tb_treatment_start_d` (d) from `input:treatment`

## Outputs

- `parasitaemia` (%)
- `parasite_density` (/uL)
- `haemolysis_rate` (10*6/uL/d)
- `bacterial_load` (1)
- `cd4` (/mm3)
- `viral_load` (/mm3)
- `tb_activity` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `mal_beta` | 70 | /d | hoshen2000 | published |
| `mal_r` | 16 | 1 | hoshen2000 | published |
| `mal_delta` | 72 | /d | hoshen2000 | published |
| `mal_alpha` | 0.05 | /d | hoshen2000 | published |
| `mal_tau` | 2 | d | hoshen2000 | published |
| `mal_rbc_lifespan` | 120 | d | hoshen2000 | published |
| `hiv_s` | 10 | /mm3/d | perelson1993 | published |
| `hiv_r` | 0.03 | /d | perelson1993 | published |
| `hiv_T_max` | 1500 | /mm3 | perelson1993 | published |
| `hiv_mu_T` | 0.02 | /d | perelson1993 | published |
| `hiv_k_1` | 2.4e-05 | mm3/d | perelson1993 | published |
| `hiv_k_2` | 0.003 | /d | perelson1993 | published |
| `hiv_mu_b` | 0.24 | /d | perelson1993 | published |
| `hiv_mu_V` | 2.4 | /d | perelson1993 | published |
| `hiv_N` | 1000 | 1 | perelson1993 | published |
| `tb_tau_active` | 60 | d | atra-assumption | assumption |
| `tb_tau_treated` | 60 | d | atra-assumption | assumption |

## Sources

- **hoshen2000**: Hoshen MB, Heinrich R, Stein WD, Ginsburg H. Mathematical modelling of the within-host dynamics of Plasmodium falciparum. Parasitology. 2000;121(3):227-235. doi:10.1017/S0031182099006368 Via: Equations 1a-1c and the values used for Figures 1 and 2; the merozoite kill rate is the estimate quoted from Anderson, May and Gupta (1989).
- **perelson1993**: Perelson AS, Kirschner DE, De Boer R. Dynamics of HIV infection of CD4+ T cells. Math Biosci. 1993;114(1):81-125. doi:10.1016/0025-5564(93)90043-a Via: BioModels BIOMD0000000874 (model A).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `tb_tau_active`: Time constant of the rise of the TB activity state in untreated active disease; no computable published within-host model fits the laptop build
- `tb_tau_treated`: Time constant of the fall of the TB activity state on effective treatment; to be replaced by a sourced response time
