# ahdt.sensory.sensory_decline

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | sensory |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Expected age-related hearing and vision change |
| Regulatory status | research |
| Source | ATRA synthetic cohort fit (WP02): power-law decline after an onset age |
| Validation | Recovery of a known decline curve from a synthetic cohort: relative_error_onset = 0.00991426 (tolerance 0.1, passed) |

## Inputs

- `age` (a) from `age`
- `hearing_offset` (dB) from `hearing_offset`
- `vision_offset` ({logMAR}) from `vision_offset`

## Outputs

- `hearing_threshold` (dB)
- `visual_acuity_logmar` ({logMAR})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `hearing_base` | 5 | dB | atra-cohort-fit | assumption |
| `hearing_onset` | 30 | a | atra-cohort-fit | assumption |
| `hearing_rate` | 0.01 | dB | atra-cohort-fit | assumption |
| `hearing_power` | 2 | 1 | atra-cohort-fit | assumption |
| `vision_base` | 0 | {logMAR} | atra-cohort-fit | assumption |
| `vision_onset` | 40 | a | atra-cohort-fit | assumption |
| `vision_rate` | 0.0002 | {logMAR} | atra-cohort-fit | assumption |
| `vision_power` | 2 | 1 | atra-cohort-fit | assumption |

## Sources

- **atra-cohort-fit**: ATRA synthetic cohort fit (WP02): power-law decline after an onset age

## Open items for sign-off

- `hearing_base`: Placeholder until the WP02 cohort fit; replaced by fit()
- `hearing_onset`: Placeholder until the WP02 cohort fit; replaced by fit()
- `hearing_rate`: Placeholder until the WP02 cohort fit; replaced by fit()
- `hearing_power`: Placeholder until the WP02 cohort fit; replaced by fit()
- `vision_base`: Placeholder until the WP02 cohort fit; replaced by fit()
- `vision_onset`: Placeholder until the WP02 cohort fit; replaced by fit()
- `vision_rate`: Placeholder until the WP02 cohort fit; replaced by fit()
- `vision_power`: Placeholder until the WP02 cohort fit; replaced by fit()
