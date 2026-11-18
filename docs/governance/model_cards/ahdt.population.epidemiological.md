# ahdt.population.epidemiological

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | population |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Malaria prevalence through the year under bed net, vaccine and treatment coverage |
| Regulatory status | research |
| Source | Smith DL, Battle KE, Hay SI, Barker CM, Scott TW, McKenzie FE. Ross, Macdonald, and a theory for the dynamics and control of mosquito-transmitted pathogens. PLoS Pathog. 2012;8(4):e1002588. doi:10.1371/journal.ppat.1002588; Smith DL, McKenzie FE, Snow RW, Hay SI. Revisiting the basic reproductive number for malaria and its implications for malaria control. PLoS Biol. 2007;5(3):e42. doi:10.1371/journal.pbio.0050042; ATRA design 01 rule R5 assumption register |
| Fidelity note | Seasonal Ross-Macdonald model for one region. The mosquito density is calibrated to the kb prevalence of malaria in Lagos, so the baseline reproduces that prevalence by construction. |

## Inputs

- `bednet_coverage` (1) from `input:scenario`
- `vaccine_coverage` (1) from `input:scenario`
- `treatment_coverage` (1) from `input:scenario`

## Outputs

- `mean_prevalence` (1)
- `peak_prevalence` (1)
- `rainy_prevalence` (1)
- `dry_prevalence` (1)
- `annual_eir` (/a)
- `mean_reproductive_number` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `g` | 0.1 | /d | smith2007 | published |
| `stability_index` | 1 | 1 | smith2007 | published |
| `v` | 10 | d | smith2012 | published |
| `b_over_r` | 170 | d | smith2007 | published |
| `r` | 0.005 | /d | atra-assumption | assumption |
| `c` | 0.2 | 1 | atra-assumption | assumption |
| `dry_season_factor` | 0.6 | 1 | atra-assumption | assumption |
| `bednet_feeding_reduction` | 0.5 | 1 | atra-assumption | assumption |
| `bednet_mortality_increase` | 0.3 | 1 | atra-assumption | assumption |
| `vaccine_efficacy` | 0.4 | 1 | atra-assumption | assumption |
| `treated_clearance_d` | 14 | d | atra-assumption | assumption |

## Sources

- **smith2012**: Smith DL, Battle KE, Hay SI, Barker CM, Scott TW, McKenzie FE. Ross, Macdonald, and a theory for the dynamics and control of mosquito-transmitted pathogens. PLoS Pathog. 2012;8(4):e1002588. doi:10.1371/journal.ppat.1002588 Via: Box 7 (Smith-McKenzie equations), the vectorial capacity and R0 formulas of the 1950-1969 section, and Table 2 (latent periods v = 10, 15, 20 d).
- **smith2007**: Smith DL, McKenzie FE, Snow RW, Hay SI. Revisiting the basic reproductive number for malaria and its implications for malaria control. PLoS Biol. 2007;5(3):e42. doi:10.1371/journal.pbio.0050042 Via: Materials and Methods, Estimate 1 (1/g of 10 to 20 d; b/r of about 170 d) and Results (stability index S = a/g of about 1).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `r`: Recovery rate of an untreated infection (mean duration 200 d). The sources give b/r only; with b/r = 170 d this sets b = 0.85.
- `c`: Infectivity of humans to mosquitoes. Neither source gives a value. The mosquito density is calibrated to the observed prevalence, so c changes the mosquito infection level, not the human prevalence at baseline.
- `dry_season_factor`: Mosquito density in the dry months relative to the rainy months (April to October); the same factor as the synthetic population generator. No Lagos entomological series was sourced.
- `bednet_feeding_reduction`: Share of human bites prevented per person under a net at full coverage; a scenario parameter, not a measured efficacy.
- `bednet_mortality_increase`: Relative rise of the mosquito death rate at full net coverage (insecticide); a scenario parameter.
- `vaccine_efficacy`: Reduction of b in a vaccinated person; a scenario parameter, not a licensed vaccine's trial efficacy.
- `treated_clearance_d`: Mean time to clearance of a treated infection; the mean episode duration of the synthetic population generator.
