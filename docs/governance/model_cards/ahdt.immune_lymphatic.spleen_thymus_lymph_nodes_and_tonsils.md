# ahdt.immune_lymphatic.spleen_thymus_lymph_nodes_and_tonsils

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | immune_lymphatic |
| Family | semantic |
| Fidelity tier | T3 |
| Anatomy | UBERON:0002106 |
| Intended use | Lymphoid organ activity and splenic red cell clearance |
| Regulatory status | research |
| Source | Reference state over kb reference ranges: state.clearance_rate, state.immune_activity, state.t_cell_output |

## Inputs

- `inflammation_index` (1) from `model:ahdt.immune_lymphatic.inflammation#inflammation_index`
- `parasitaemia` (%) from `model:ahdt.immune_lymphatic.infection_response#parasitaemia`

## Outputs

- `immune_activity` (1)
- `t_cell_output` (1)
- `clearance_rate` (1)
- `immune_activity_status` ({status})
- `t_cell_output_status` ({status})
- `clearance_rate_status` ({status})

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `tau_immune_activity` | 48 | h | atra-t3-dynamics | assumption |
| `tau_t_cell_output` | 720 | h | atra-t3-dynamics | assumption |
| `tau_clearance_rate` | 48 | h | atra-t3-dynamics | assumption |

## Sources

- **atra-t3-dynamics**: ATRA design 01 rule R3: T3 reference-state relaxation time constants are modelling assumptions, not published values

## Open items for sign-off

- `tau_immune_activity`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_t_cell_output`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
- `tau_clearance_rate`: Relaxation time constant of a T3 state; a modelling assumption (design 01, rule R3)
