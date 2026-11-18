# ahdt.endocrine.hpa_axis

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | endocrine |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001898 |
| Intended use | Cortisol rhythm and its response to stress |
| Regulatory status | research |
| Source | Gupta S, Aslakson E, Gurbaxani BM, Vernon SD. Inclusion of the glucocorticoid receptor in a hypothalamic pituitary adrenal axis model reveals bistability. Theor Biol Med Model. 2007;4:8. doi:10.1186/1742-4682-4-8; ATRA design 01 rule R5 assumption register |
| Validation | Gupta 2007 scaled equations 9 to 12; normal steady state: steady_state_residual = 5.44009e-15 (tolerance 1e-06, passed) |

## Inputs

- `stress_drive` (1) from `connector:NeuroEndocrineConnector#stress_drive`
- `clock_h` (h) from `connector:NeuroEndocrineConnector#circadian_phase`

## Outputs

- `cortisol` (nmol/L)
- `crh_drive` (1)
- `acth` (1)
- `gr` (1)
- `cortisol_scaled` (1)
- `stress_drive` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `kcd` | 1 | 1 | gupta2007 | published |
| `kad` | 10 | 1 | gupta2007 | published |
| `krd` | 0.9 | 1 | gupta2007 | published |
| `kcr` | 0.05 | 1 | gupta2007 | published |
| `k` | 0.001 | 1 | gupta2007 | published |
| `ki1` | 0.1 | 1 | gupta2007 | published |
| `ki2` | 0.1 | 1 | gupta2007 | published |
| `cortisol_half_life` | 66 | min | atra-assumption | unverified |
| `circadian_amplitude` | 0.5 | 1 | atra-assumption | assumption |
| `peak_phase_h` | 8 | h | atra-assumption | assumption |
| `cortisol_scale` | 5000 | nmol/L | atra-assumption | assumption |

## Sources

- **gupta2007**: Gupta S, Aslakson E, Gurbaxani BM, Vernon SD. Inclusion of the glucocorticoid receptor in a hypothalamic pituitary adrenal axis model reveals bistability. Theor Biol Med Model. 2007;4:8. doi:10.1186/1742-4682-4-8 Via: Europe PMC PMC1804264 (equations 9 to 12 and the scaled parameter values).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `cortisol_half_life`: Plasma cortisol half-life of about an hour sets the time scale K_od; a sourced value is needed before sign-off
- `circadian_amplitude`: Gupta et al. omit the circadian input; the CRH drive is modulated by the circadian phase with this relative amplitude
- `peak_phase_h`: Clock time of the CRH drive maximum, placing the cortisol peak in the morning; calibrated per person
- `cortisol_scale`: Conversion of scaled cortisol to nmol/L that maps the scaled steady state (about 0.06) to about 300 nmol/L; fitted to the person's cortisol measurements
