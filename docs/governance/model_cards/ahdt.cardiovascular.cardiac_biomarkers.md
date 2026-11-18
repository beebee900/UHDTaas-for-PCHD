# ahdt.cardiovascular.cardiac_biomarkers

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | none |
| Intended use | Troponin and natriuretic peptide state against reference ranges |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.bnp, range.troponin_i |

## Inputs

- `lvedp` (mm[Hg]) from `model:ahdt.cardiovascular.heart_chambers_and_valves#lvedp`

## Outputs

- `troponin_i` (ng/L)
- `bnp` (pg/mL)
- `troponin_i_status` ({status})
- `bnp_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_troponin_i` | 12 | h | atra-t3-dynamics | assumption |
| `tau_bnp` | 24 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_troponin_i`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_bnp`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
