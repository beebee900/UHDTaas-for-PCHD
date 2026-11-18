# ahdt.endocrine.hormone_kinetics

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Decay and accumulation of circulating hormones and hormone doses |
| Regulatory status | research |
| Source | Brown EN, Choe Y, Shanahan TL, Czeisler CA. A mathematical model of diurnal variations in human plasma melatonin levels. Am J Physiol. 1997;272(3 Pt 1):E506-E516. doi:10.1152/ajpendo.1997.272.3.E506; ATRA design 01 rule R5 assumption register |
| Validation | One-compartment decay over one published half-life: relative_error_half = 7.94172e-07 (tolerance 0.0001, passed) |

## Inputs

- `melatonin_secretion` (1/min) from `input:scenario`
- `cortisol_secretion` (1/min) from `input:scenario`
- `t4_secretion` (1/min) from `input:scenario`
- `t3_secretion` (1/min) from `input:scenario`
- `tsh_secretion` (1/min) from `input:scenario`
- `pth_secretion` (1/min) from `input:scenario`

## Outputs

- `melatonin` (1)
- `cortisol` (1)
- `t4` (1)
- `t3` (1)
- `tsh` (1)
- `pth` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `half_life_melatonin` | 23.67 | min | brown1997 | published |
| `half_life_cortisol` | 66 | min | atra-assumption | unverified |
| `half_life_t4` | 10080 | min | atra-assumption | unverified |
| `half_life_t3` | 1440 | min | atra-assumption | unverified |
| `half_life_tsh` | 60 | min | atra-assumption | unverified |
| `half_life_pth` | 4 | min | atra-assumption | unverified |

## Sources

- **brown1997**: Brown EN, Choe Y, Shanahan TL, Czeisler CA. A mathematical model of diurnal variations in human plasma melatonin levels. Am J Physiol. 1997;272(3 Pt 1):E506-E516. doi:10.1152/ajpendo.1997.272.3.E506
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `half_life_cortisol`: Plasma cortisol half-life of about an hour; needs a sourced value (shared with the HPA model)
- `half_life_t4`: Thyroxine half-life of about 7 days; needs a sourced value
- `half_life_t3`: Triiodothyronine half-life of about 1 day; needs a sourced value
- `half_life_tsh`: TSH half-life of about an hour; needs a sourced value
- `half_life_pth`: Intact PTH half-life of a few minutes; needs a sourced value
