# ahdt.respiratory.airway_epithelium

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | respiratory |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Airway epithelial inflammation coupled from the Immune twin |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.epithelial_inflammation |

## Inputs

- `crp` (mg/L) from `field:1988-5`

## Outputs

- `epithelial_inflammation` (1)
- `epithelial_inflammation_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_epithelial_inflammation` | 48 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_epithelial_inflammation`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
