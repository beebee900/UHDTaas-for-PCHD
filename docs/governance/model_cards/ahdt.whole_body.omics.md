# ahdt.whole_body.omics

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Synthetic omics indices against reference distributions |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.epigenetic_age, state.metabolome_glycaemic_index, state.proteome_inflammation_index |

## Inputs

- none

## Outputs

- `proteome_inflammation_index` (1)
- `metabolome_glycaemic_index` (1)
- `epigenetic_age` (a)
- `proteome_inflammation_index_status` ({status})
- `metabolome_glycaemic_index_status` ({status})
- `epigenetic_age_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_proteome_inflammation_index` | 720 | h | atra-t3-dynamics | assumption |
| `tau_metabolome_glycaemic_index` | 720 | h | atra-t3-dynamics | assumption |
| `tau_epigenetic_age` | 8760 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_proteome_inflammation_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_metabolome_glycaemic_index`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_epigenetic_age`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
