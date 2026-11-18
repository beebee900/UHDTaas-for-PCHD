# ahdt.endocrine.gonadal_hormones

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000991 |
| Intended use | Female gonadal and pituitary hormone profile over the menstrual cycle |
| Regulatory status | research |
| Source | Röblitz S, Stötzel C, Deuflhard P, Jones HM, Azulay DO, van der Graaf PH, Martin SW. A mathematical model of the human menstrual cycle for the administration of GnRH analogues. J Theor Biol. 2013;321:8-27. doi:10.1016/j.jtbi.2012.11.020; ATRA design 01 rule R5 assumption register |
| Fidelity note | Female cycle only. A testosterone model for males needs a kb reference range that the kb does not hold. |
| Validation | Roeblitz 2013 (ZIB report 11-16): simulated cycle length is about 28 days: cycle_length_error_days = 0.2 (tolerance 1.4, passed) |

## Inputs

- none

## Outputs

- `lh` (mIU/mL)
- `fsh` (mIU/mL)
- `oestradiol` (pg/mL)
- `progesterone` (ng/mL)
- `inhibin_a` (IU/mL)
- `inhibin_b` (pg/mL)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `agonist_dose` | 0 | 1 | atra-assumption | assumption |
| `antagonist_dose` | 0 | 1 | atra-assumption | assumption |

## Sources

- **roeblitz2013**: Röblitz S, Stötzel C, Deuflhard P, Jones HM, Azulay DO, van der Graaf PH, Martin SW. A mathematical model of the human menstrual cycle for the administration of GnRH analogues. J Theor Biol. 2013;321:8-27. doi:10.1016/j.jtbi.2012.11.020 Via: BioModels BIOMD0000000494, curated, CC0 1.0, SBML L2V4, sha256 7eb01f255157c04ff346d8df279283b5735bee751f9167c31948d3fbfeaf81fe; units from the ZIB report 11-16 (Fig. 4).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `agonist_dose`: The pinned model schedules a Nafarelin dose; the twin models a cycle without GnRH analogues, so the dose is set to zero
- `antagonist_dose`: The pinned model schedules a Cetrorelix dose; the twin models a cycle without GnRH analogues, so the dose is set to zero
