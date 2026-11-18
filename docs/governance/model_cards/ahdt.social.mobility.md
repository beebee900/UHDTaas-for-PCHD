# ahdt.social.mobility

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | social |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Places a person visits and how far they range, from their GPS stay points |
| Regulatory status | research |
| Source | Song C, Koren T, Wang P, Barabasi AL. Modelling the scaling properties of human mobility. Nat Phys. 2010;6:818-823. doi:10.1038/nphys1760; ATRA design 01 rule R5 assumption register |
| Fidelity note | Exploration and preferential return model; trace calibration uses stay points, not raw GPS fixes. |
| Validation | Song 2010 model; maximum likelihood recovers rho and gamma from a simulated four-year stay-point trace: max_abs_error_rho_gamma = 0.00446561 (tolerance 0.1, passed) |

## Inputs

- `rho` (1) from `input:calibration`
- `gamma` (1) from `input:calibration`

## Outputs

- `distinct_locations` ({locations})
- `radius_of_gyration_km` (km)
- `top_location_share` (1)
- `new_location_probability` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `rho` | 0.6 | 1 | song2010 | published |
| `gamma` | 0.21 | 1 | song2010 | published |
| `alpha` | 0.55 | 1 | song2010 | published |
| `beta` | 0.8 | 1 | song2010 | published |
| `min_jump_km` | 0.1 | km | atra-assumption | assumption |
| `max_jump_km` | 100 | km | atra-assumption | assumption |
| `min_wait_h` | 1 | h | atra-assumption | assumption |
| `max_wait_h` | 168 | h | atra-assumption | assumption |

## Sources

- **song2010**: Song C, Koren T, Wang P, Barabasi AL. Modelling the scaling properties of human mobility. Nat Phys. 2010;6:818-823. doi:10.1038/nphys1760 Via: arXiv:1010.0436v1, text read for the model definition and the parameter estimates.
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `min_jump_km`: Lower cut-off of the jump size density; the paper gives the exponent, not the cut-offs. Stay points closer than this are one place
- `max_jump_km`: Upper cut-off of the jump size density, a regional travel limit
- `min_wait_h`: Lower cut-off of the waiting time density; the sampling interval of one stay point per hour
- `max_wait_h`: Upper cut-off of the waiting time density, one week
