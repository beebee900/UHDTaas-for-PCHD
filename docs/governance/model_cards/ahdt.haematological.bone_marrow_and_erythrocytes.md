# ahdt.haematological.bone_marrow_and_erythrocytes

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | haematological |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000178 |
| Intended use | Haemoglobin trajectory under haemolysis, blood loss and recovery |
| Regulatory status | research |
| Source | Semba RD, Broadhead R, Taha TE, Totin D, Ricks MO, Kumwenda N. Erythropoietin response to anemia among human immunodeficiency virus-infected infants in Malawi. Haematologica. 2001;86(11):1221-1222; Hoshen MB, Heinrich R, Stein WD, Ginsburg H. Mathematical modelling of the within-host dynamics of Plasmodium falciparum. Parasitology. 2000;121(3):227-235. doi:10.1017/S0031182099006368; West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 6 (oxygen content); ATRA design 01 rule R5 assumption register |
| Validity | {'epo_regression': 'derived in infants; see the parameter source'} |
| Validation | Steady state at the person's baseline haemoglobin: hb_drift_g_dl = 0 (tolerance 0.001, passed) |

## Inputs

- `hb0` (g/dL) from `field:718-7`
- `haemolysis_rate` (10*6/uL/d) from `input:condition`
- `parasitaemia` (%) from `connector:HaemolysisConnector#parasitaemia`
- `lifespan_factor` (1) from `input:condition`
- `marrow_suppression` (1) from `input:condition`
- `spo2` (%) from `field:59408-5`
- `pao2` (mm[Hg]) from `field:2703-7`

## Outputs

- `hb` (g/dL)
- `rbc` (10*6/uL)
- `haematocrit` (%)
- `epo` ([IU]/L)
- `erythropoiesis_rate` (10*6/uL/d)
- `o2_content` (mL/dL)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `epo_intercept` | 2.9 | log10(IU/L) | semba2001 | published |
| `epo_slope` | 0.013 | log10(IU/L) per g/L | semba2001 | published |
| `rbc_lifespan` | 120 | d | hoshen2000 | published |
| `mch` | 30 | pg | atra-assumption | assumption |
| `maturation_days` | 5 | d | atra-assumption | assumption |
| `epo_gain` | 1 | 1 | atra-assumption | assumption |
| `mcv` | 90 | fL | atra-assumption | assumption |
| `hufner` | 1.34 | mL/g | west | published |
| `o2_solubility` | 0.003 | mL/dL/mm[Hg] | west | published |
| `malaria_cycle_days` | 2 | d | hoshen2000 | published |

## Sources

- **semba2001**: Semba RD, Broadhead R, Taha TE, Totin D, Ricks MO, Kumwenda N. Erythropoietin response to anemia among human immunodeficiency virus-infected infants in Malawi. Haematologica. 2001;86(11):1221-1222
- **hoshen2000**: Hoshen MB, Heinrich R, Stein WD, Ginsburg H. Mathematical modelling of the within-host dynamics of Plasmodium falciparum. Parasitology. 2000;121(3):227-235. doi:10.1017/S0031182099006368
- **west**: West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 6 (oxygen content)
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `mch`: Mean cell haemoglobin converting red cell count to haemoglobin; taken from the person's full blood count when available
- `maturation_days`: Mean marrow transit before release, as a two-stage chain; no single published value located for this simplified form
- `epo_gain`: Exponent of production on relative EPO; 1 makes production proportional to EPO
- `mcv`: Mean cell volume converting red cell count to haematocrit; taken from the person's full blood count when available
