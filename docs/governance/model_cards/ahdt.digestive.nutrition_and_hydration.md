# ahdt.digestive.nutrition_and_hydration

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | digestive |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Energy balance, weight trajectory and hydration |
| Regulatory status | research |
| Source | Mifflin MD, St Jeor ST, Hill LA, Scott BJ, Daugherty SA, Koh YO. A new predictive equation for resting energy expenditure in healthy individuals. Am J Clin Nutr. 1990;51(2):241-247. doi:10.1093/ajcn/51.2.241; Watson PE, Watson ID, Batt RD. Total body water volumes for adult males and females estimated from simple anthropometric measurements. Am J Clin Nutr. 1980;33(1):27-39. doi:10.1093/ajcn/33.1.27; Wishnofsky M. Caloric equivalents of gained or lost weight. Am J Clin Nutr. 1958;6(5):542-546. doi:10.1093/ajcn/6.5.542 |
| Validation | Mifflin-St Jeor: 10 x 70 + 6.25 x 175 - 5 x 30 + 5 kcal/d: ree_error_kcal = 0 (tolerance 1e-09, passed) |

## Inputs

- `weight0` (kg) from `field:29463-7`
- `height` (cm) from `field:8302-2`
- `age` (a) from `age`
- `female` (1) from `female`
- `energy_intake` (kcal/d) from `energy_intake`
- `pal` (1) from `input:activity`
- `water_in` (mL/d) from `water_in`
- `water_out` (mL/d) from `water_out`

## Outputs

- `ree` (kcal/d)
- `energy_balance` (kcal/d)
- `weight` (kg)
- `bmi` (kg/m2)
- `total_body_water` (L)
- `hydration_deficit` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `w_coef` | 10 | kcal/d/kg | mifflin1990 | published |
| `h_coef` | 6.25 | kcal/d/cm | mifflin1990 | published |
| `a_coef` | 5 | kcal/d/a | mifflin1990 | published |
| `male_const` | 5 | kcal/d | mifflin1990 | published |
| `female_const` | -161 | kcal/d | mifflin1990 | published |
| `energy_per_kg` | 7700 | kcal/kg | wishnofsky1958 | unverified |

## Sources

- **mifflin1990**: Mifflin MD, St Jeor ST, Hill LA, Scott BJ, Daugherty SA, Koh YO. A new predictive equation for resting energy expenditure in healthy individuals. Am J Clin Nutr. 1990;51(2):241-247. doi:10.1093/ajcn/51.2.241
- **watson1980**: Watson PE, Watson ID, Batt RD. Total body water volumes for adult males and females estimated from simple anthropometric measurements. Am J Clin Nutr. 1980;33(1):27-39. doi:10.1093/ajcn/33.1.27
- **wishnofsky1958**: Wishnofsky M. Caloric equivalents of gained or lost weight. Am J Clin Nutr. 1958;6(5):542-546. doi:10.1093/ajcn/6.5.542

## Open items for sign-off

- `energy_per_kg`: About 3500 kcal per pound as recalled from Wishnofsky (1958); a known simplification of tissue energy density
