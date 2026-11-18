# ahdt.population.demographic

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | population |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Population by age group and sex over the next 20 years |
| Regulatory status | research |
| Source | ATRA design 01 rule R5 assumption register |
| Fidelity note | Cohort-component projection in five-year steps from assumed Lagos-like rates. |

## Inputs

- `base_population` ({persons}) from `input:scenario`
- `steps` (1) from `input:scenario`

## Outputs

- `total` ({persons})
- `dependency_ratio` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `asfr_15_19` | 0.06 | /a | atra-assumption | assumption |
| `asfr_20_24` | 0.15 | /a | atra-assumption | assumption |
| `asfr_25_29` | 0.17 | /a | atra-assumption | assumption |
| `asfr_30_34` | 0.15 | /a | atra-assumption | assumption |
| `asfr_35_39` | 0.11 | /a | atra-assumption | assumption |
| `asfr_40_44` | 0.05 | /a | atra-assumption | assumption |
| `asfr_45_49` | 0.01 | /a | atra-assumption | assumption |
| `male_birth_share` | 0.512 | 1 | atra-assumption | assumption |
| `mortality_0_4` | 0.02 | /a | atra-assumption | assumption |
| `mortality_5_14` | 0.002 | /a | atra-assumption | assumption |
| `mortality_15_49` | 0.004 | /a | atra-assumption | assumption |
| `mortality_50_64` | 0.012 | /a | atra-assumption | assumption |
| `mortality_65_79` | 0.04 | /a | atra-assumption | assumption |
| `mortality_80_plus` | 0.15 | /a | atra-assumption | assumption |
| `net_migration_15_34` | 0.01 | /a | atra-assumption | assumption |

## Sources

- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `asfr_15_19`: Births per woman per year at 15 to 19; the seven age-specific rates give a total fertility of 3.5, a Lagos-like urban level.
- `asfr_20_24`: Part of the assumed total fertility of 3.5.
- `asfr_25_29`: Part of the assumed total fertility of 3.5.
- `asfr_30_34`: Part of the assumed total fertility of 3.5.
- `asfr_35_39`: Part of the assumed total fertility of 3.5.
- `asfr_40_44`: Part of the assumed total fertility of 3.5.
- `asfr_45_49`: Part of the assumed total fertility of 3.5.
- `male_birth_share`: Share of boys among births (105 boys per 100 girls).
- `mortality_0_4`: Annual death rate of under-fives; a high child mortality level placeholder until a Nigerian life table is sourced.
- `mortality_5_14`: Placeholder until a Nigerian life table is sourced.
- `mortality_15_49`: Placeholder until a Nigerian life table is sourced.
- `mortality_50_64`: Placeholder until a Nigerian life table is sourced.
- `mortality_65_79`: Placeholder until a Nigerian life table is sourced.
- `mortality_80_plus`: Placeholder until a Nigerian life table is sourced.
- `net_migration_15_34`: Net in-migration per year at working ages 15 to 34, for a city that grows by migration; a placeholder.
