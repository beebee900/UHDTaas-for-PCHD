# apdt.treatment.population_pk

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | simulation |
| Fidelity tier | T2 |
| Intended use | Individual clearance and volume from measured concentrations, given a published population model in the kb |
| Regulatory status | research |
| Source | One-compartment oral model with log-normal random effects; PyMC (Abril-Pla O et al. PeerJ CS 2023;9:e1516); typical values from kb/popk |
| Validation | not validated yet |
| Depends on | ahdt.whole_body.whole_body_pbpk 1.0.0 |

## Inputs

- `concentrations` (mg/L)
- `dose` (mg)

## Outputs

- `clearance` (L/h)
- `volume` (L)
