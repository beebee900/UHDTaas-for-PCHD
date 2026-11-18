# ahdt.endocrine.pineal

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001905 |
| Intended use | Plasma melatonin rhythm and dim-light melatonin onset |
| Regulatory status | research |
| Source | Brown EN, Choe Y, Shanahan TL, Czeisler CA. A mathematical model of diurnal variations in human plasma melatonin levels. Am J Physiol. 1997;272(3 Pt 1):E506-E516. doi:10.1152/ajpendo.1997.272.3.E506 |
| Validation | Brown 1997 melatonin rhythm; daytime level relative to the peak: daytime_to_peak_ratio = 0.0071237 (tolerance 0.05, passed) |

## Inputs

- `clock_min` (min) from `input:clock`

## Outputs

- `melatonin` (pmol/L)
- `pineal_melatonin` (pmol/L)
- `synthesis_rate` (pmol/L/min)
- `circadian_phase` (h)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `t_on` | 1316 | min | brown1997 | published |
| `t_off` | 1794 | min | brown1997 | published |
| `A_max` | 6.51 | pmol/L/min | brown1997 | published |
| `tau_I` | 2.82 | min | brown1997 | published |
| `tau_C` | 23.67 | min | brown1997 | published |
| `tau_alpha` | 25.92 | min | brown1997 | published |
| `tau_lamda` | 24.04 | min | brown1997 | published |

## Sources

- **brown1997**: Brown EN, Choe Y, Shanahan TL, Czeisler CA. A mathematical model of diurnal variations in human plasma melatonin levels. Am J Physiol. 1997;272(3 Pt 1):E506-E516. doi:10.1152/ajpendo.1997.272.3.E506 Via: BioModels BIOMD0000000672.
