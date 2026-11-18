# ahdt.whole_body.maternal_foetal

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Foetal growth and maternal physiological adaptation in pregnancy |
| Regulatory status | research |
| Source | Hadlock FP, Harrist RB, Sharman RS, Deter RL, Park SK. Estimation of fetal weight with the use of head, body, and femur measurements: a prospective study. Am J Obstet Gynecol. 1985;151(3):333-337. doi:10.1016/0002-9378(85)90298-4 |
| Validity | {'pregnancy': 'singleton'} |
| Validation | Hadlock 1985 (LOINC 11746-5) at HC 30, AC 30, FL 6.5 cm: relative_error_efw = 0 (tolerance 1e-12, passed) |

## Inputs

- `gestation_weeks` (wk) from `facet:UBERON:0001987/maternal_foetal#gestation_weeks`
- `placental_function` (1) from `facet:UBERON:0001987/maternal_foetal#placental_function`
- `hc` (cm) from `field:11984-2`
- `ac` (cm) from `field:11979-2`
- `fl` (cm) from `field:11963-6`

## Outputs

- `efw` (g)
- `gestation_weeks` (wk)
- `placental_function` (1)
- `cardiac_output_factor` (1)
- `plasma_volume_factor` (1)
- `gfr_factor` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `c0` | 1.326 | 1 | hadlock1985 | published |
| `c_hc` | 0.0107 | /cm | hadlock1985 | published |
| `c_ac` | 0.0438 | /cm | hadlock1985 | published |
| `c_fl` | 0.158 | /cm | hadlock1985 | published |
| `c_acfl` | -0.00326 | /cm2 | hadlock1985 | published |

## Sources

- **hadlock1985**: Hadlock FP, Harrist RB, Sharman RS, Deter RL, Park SK. Estimation of fetal weight with the use of head, body, and femur measurements: a prospective study. Am J Obstet Gynecol. 1985;151(3):333-337. doi:10.1016/0002-9378(85)90298-4 Via: LOINC 11746-5 formula (EFW from AC, FL and HC, Hadlock 1985).
