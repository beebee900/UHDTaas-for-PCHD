# ahdt.nervous.circadian_rhythm_and_sleep

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | nervous |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000955 |
| Intended use | Sleep pressure, circadian phase and predicted sleep timing |
| Regulatory status | research |
| Source | Daan S, Beersma DG, Borbely AA. Timing of human sleep: recovery process gated by a circadian pacemaker. Am J Physiol. 1984;246(2 Pt 2):R161-R183. doi:10.1152/ajpregu.1984.246.2.R161; Skeldon AC, Dijk DJ, Derks G. Mathematical models for sleep-wake dynamics: comparison of the two-process model and a mutual inhibition neuronal model. PLoS One. 2014;9(8):e103877. doi:10.1371/journal.pone.0103877 |
| Validation | Two-process model fitted to a 23:00 to 07:00 sleep schedule: duration_error_h = 0 (tolerance 0.25, passed) |

## Inputs

- `asleep` (1) from `input:wearable`
- `clock_h` (h) from `input:clock`

## Outputs

- `sleep_pressure` (1)
- `circadian_process` (1)
- `asleep` (1)
- `upper_threshold` (1)
- `lower_threshold` (1)
- `circadian_phase` (h)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `chi_w` | 18.2 | h | skeldon2014 | published |
| `chi_s` | 4.2 | h | skeldon2014 | published |
| `mu` | 1 | 1 | skeldon2014 | published |
| `H0_plus` | 0.6 | 1 | skeldon2014 | published |
| `H0_minus` | 0.17 | 1 | skeldon2014 | published |
| `a` | 0.1 | 1 | skeldon2014 | published |
| `period` | 24 | h | skeldon2014 | published |
| `alpha` | 0 | h | skeldon2014 | assumption |

## Sources

- **daan1984**: Daan S, Beersma DG, Borbely AA. Timing of human sleep: recovery process gated by a circadian pacemaker. Am J Physiol. 1984;246(2 Pt 2):R161-R183. doi:10.1152/ajpregu.1984.246.2.R161
- **skeldon2014**: Skeldon AC, Dijk DJ, Derks G. Mathematical models for sleep-wake dynamics: comparison of the two-process model and a mutual inhibition neuronal model. PLoS One. 2014;9(8):e103877. doi:10.1371/journal.pone.0103877 Via: Parameter set stated as 'as in Daan et al. 1984, Figure 3' (arXiv:1311.1734).

## Open items for sign-off

- `alpha`: Circadian phase offset; Skeldon et al. plot sin(omega t). It is fitted to the person's sleep diary or wearable sleep data
