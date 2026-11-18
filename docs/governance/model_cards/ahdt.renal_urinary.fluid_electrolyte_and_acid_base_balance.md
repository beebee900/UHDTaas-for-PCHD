# ahdt.renal_urinary.fluid_electrolyte_and_acid_base_balance

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | renal_urinary |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Sodium, potassium, water and acid-base state under intake and losses |
| Regulatory status | research |
| Source | Edelman IS, Leibman J, O'Meara MP, Birkenfeld LW. Interrelations between serum sodium concentration, serum osmolarity and total exchangeable sodium, total exchangeable potassium and total body water. J Clin Invest. 1958;37(9):1236-1256. doi:10.1172/JCI103712; West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 6 (acid-base status); Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021. Body fluid compartments; ATRA design 01 rule R5 assumption register |
| Validation | Henderson-Hasselbalch at HCO3 24 mmol/L and PaCO2 40 mmHg; pH 7.40: ph_error = -0.00898713 (tolerance 0.015, passed) |

## Inputs

- `paco2` (mm[Hg]) from `facet:UBERON:0002048/gas_exchange#paco2`
- `water_in` (mL/h) from `water_in`
- `water_out` (mL/h) from `water_out`
- `na_in` (mmol/h) from `na_in`
- `na_out` (mmol/h) from `na_out`
- `k_in` (mmol/h) from `k_in`
- `k_out` (mmol/h) from `k_out`
- `acid_load` (mmol/L/h) from `acid_load`
- `age` (a) from `age`
- `female` (1) from `female`
- `height` (cm) from `height`
- `weight` (kg) from `weight`
- `sodium0` (mmol/L) from `sodium0`
- `potassium0` (mmol/L) from `potassium0`
- `hco3_0` (mmol/L) from `hco3_0`

## Outputs

- `sodium` (mmol/L)
- `potassium` (mmol/L)
- `hco3` (mmol/L)
- `ph` ([pH])
- `total_body_water` (L)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `edelman_slope` | 1.11 | 1 | edelman1958 | published |
| `edelman_intercept` | -25.6 | mmol/L | edelman1958 | published |
| `pk_bicarbonate` | 6.1 | 1 | west | published |
| `co2_solubility` | 0.0307 | mmol/L/mm[Hg] | west | unverified |
| `ecf_fraction` | 0.3333 | 1 | guyton | unverified |
| `hco3_tau` | 24 | h | atra-assumption | assumption |

## Sources

- **edelman1958**: Edelman IS, Leibman J, O'Meara MP, Birkenfeld LW. Interrelations between serum sodium concentration, serum osmolarity and total exchangeable sodium, total exchangeable potassium and total body water. J Clin Invest. 1958;37(9):1236-1256. doi:10.1172/JCI103712
- **west**: West JB, Luks AM. West's Respiratory Physiology: The Essentials. 11th ed. Wolters Kluwer; 2020. Chapter 6 (acid-base status)
- **guyton**: Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021. Body fluid compartments
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `co2_solubility`: CO2 solubility at 37 Cel as commonly stated (0.03 in West); value with three digits needs a page check
- `ecf_fraction`: Extracellular fluid as one third of total body water as recalled from Guyton and Hall; needs a page check
- `hco3_tau`: Time constant of renal correction of bicarbonate towards its baseline; no single published value
