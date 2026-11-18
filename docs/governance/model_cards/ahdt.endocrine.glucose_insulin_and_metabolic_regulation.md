# ahdt.endocrine.glucose_insulin_and_metabolic_regulation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001264 |
| Intended use | Plasma glucose and insulin response to meals for glycaemic forecasts |
| Regulatory status | research |
| Source | Dalla Man C, Rizza RA, Cobelli C. Meal simulation model of the glucose-insulin system. IEEE Trans Biomed Eng. 2007;54(10):1740-1749. doi:10.1109/TBME.2007.893506 |
| Validity | {'population': 'adults without diabetes', 'age_years': [18, 90]} |
| Validation | Dalla Man 2007 meal of 78 g; appearance equals f times the dose: relative_error_absorbed_glucose = 3.76751e-06 (tolerance 0.02, passed) |

## Inputs

- `Ra` (mg/kg/min) from `facet:UBERON:0000160/absorption#absorption_rate`
- `meals` (g) from `input:scenario`

## Outputs

- `glucose` (mmol/L)
- `glucose_mgdl` (mg/dL)
- `insulin` (pmol/L)
- `insulin_secretion` (pmol/kg/min)
- `EGP` (mg/kg/min)
- `utilisation` (mg/kg/min)
- `Ra` (mg/kg/min)
- `renal_excretion` (mg/kg/min)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `BW` | 78 | kg | dallaman2007 | published |
| `G_b` | 95 | mg/dL | dallaman2007 | published |
| `I_b` | 25 | pmol/L | dallaman2007 | published |
| `V_G` | 1.88 | dL/kg | dallaman2007 | published |
| `k_1` | 0.065 | /min | dallaman2007 | published |
| `k_2` | 0.079 | /min | dallaman2007 | published |
| `V_I` | 0.05 | L/kg | dallaman2007 | published |
| `m_1` | 0.19 | /min | dallaman2007 | published |
| `m_2` | 0.484 | /min | dallaman2007 | published |
| `m_4` | 0.194 | /min | dallaman2007 | published |
| `m_5` | 0.0304 | min.kg/pmol | dallaman2007 | published |
| `m_6` | 0.6471 | 1 | dallaman2007 | published |
| `k_max` | 0.0558 | /min | dallaman2007 | published |
| `k_min` | 0.008 | /min | dallaman2007 | published |
| `k_abs` | 0.057 | /min | dallaman2007 | published |
| `k_gri` | 0.0558 | /min | dallaman2007 | published |
| `f` | 0.9 | 1 | dallaman2007 | published |
| `b` | 0.82 | 1 | dallaman2007 | published |
| `d` | 0.01 | 1 | dallaman2007 | published |
| `k_p1` | 2.7 | mg/kg/min | dallaman2007 | published |
| `k_p2` | 0.0021 | /min | dallaman2007 | published |
| `k_p3` | 0.009 | mg/kg/min per pmol/L | dallaman2007 | published |
| `k_p4` | 0.0618 | mg/kg/min per pmol/kg | dallaman2007 | published |
| `k_i` | 0.0079 | /min | dallaman2007 | published |
| `F_cns` | 1 | mg/kg/min | dallaman2007 | published |
| `K_m0` | 225.59 | mg/kg | dallaman2007 | published |
| `V_mX` | 0.047 | mg/kg/min per pmol/L | dallaman2007 | published |
| `p_2U` | 0.0331 | /min | dallaman2007 | published |
| `K` | 2.3 | pmol/kg per mg/dL | dallaman2007 | published |
| `alpha` | 0.05 | /min | dallaman2007 | published |
| `beta` | 0.11 | pmol/kg/min per mg/dL | dallaman2007 | published |
| `gamma` | 0.5 | /min | dallaman2007 | published |
| `k_e1` | 0.0005 | /min | dallaman2007 | published |
| `k_e2` | 339 | mg/kg | dallaman2007 | published |
| `V_m0` | 2.5 | mg/kg/min | dallaman2007 | published |
| `S_b` | 1.8 | pmol/kg/min | dallaman2007 | published |

## Sources

- **dallaman2007**: Dalla Man C, Rizza RA, Cobelli C. Meal simulation model of the glucose-insulin system. IEEE Trans Biomed Eng. 2007;54(10):1740-1749. doi:10.1109/TBME.2007.893506 Via: BioModels BIOMD0000000379 (curated SBML of the paper).
