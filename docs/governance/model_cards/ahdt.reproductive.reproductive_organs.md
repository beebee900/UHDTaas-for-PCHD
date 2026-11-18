# ahdt.reproductive.reproductive_organs

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | reproductive |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0000991 |
| Intended use | Organ state and screening status of the reproductive organs |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: range.oestradiol, state.psa_state, state.screening_status, state.uterine_state |

## Inputs

- none

## Outputs

- `screening_status` ({code})
- `uterine_state` ({code})
- `psa_state` (ug/L)
- `oestradiol` (pmol/L)
- `screening_status_status` ({status})
- `uterine_state_status` ({status})
- `psa_state_status` ({status})
- `oestradiol_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_screening_status` | 8760 | h | atra-t3-dynamics | assumption |
| `tau_uterine_state` | 720 | h | atra-t3-dynamics | assumption |
| `tau_psa_state` | 8760 | h | atra-t3-dynamics | assumption |
| `tau_oestradiol` | 24 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_screening_status`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_uterine_state`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_psa_state`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_oestradiol`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
