# ahdt.digestive.stomach_and_intestine_absorption

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | digestive |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000945 |
| Intended use | Rate of appearance of meal glucose and oral drug absorption |
| Regulatory status | research |
| Source | Dalla Man C, Rizza RA, Cobelli C. Meal simulation model of the glucose-insulin system. IEEE Trans Biomed Eng. 2007;54(10):1740-1749. doi:10.1109/TBME.2007.893506 |
| Validation | Dalla Man 2007 meal of 78 g; appearance equals f times the dose: relative_error_absorbed_glucose = 3.69869e-06 (tolerance 0.02, passed) |

## Inputs

- `meals` (g) from `input:scenario`
- `ka` (/h) from `input:drug`

## Outputs

- `absorption_rate` (mg/kg/min)
- `gastric_emptying_rate` (/min)
- `transit_time` (min)
- `stomach_content` (mg)
- `drug_absorption_rate` (mg/h)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `BW` | 78 | kg | dallaman2007 | published |
| `k_max` | 0.0558 | /min | dallaman2007 | published |
| `k_min` | 0.008 | /min | dallaman2007 | published |
| `k_abs` | 0.057 | /min | dallaman2007 | published |
| `k_gri` | 0.0558 | /min | dallaman2007 | published |
| `f` | 0.9 | 1 | dallaman2007 | published |
| `b` | 0.82 | 1 | dallaman2007 | published |
| `d` | 0.01 | 1 | dallaman2007 | published |

## Sources

- **dallaman2007**: Dalla Man C, Rizza RA, Cobelli C. Meal simulation model of the glucose-insulin system. IEEE Trans Biomed Eng. 2007;54(10):1740-1749. doi:10.1109/TBME.2007.893506 Via: BioModels BIOMD0000000379 (curated SBML of the paper).
