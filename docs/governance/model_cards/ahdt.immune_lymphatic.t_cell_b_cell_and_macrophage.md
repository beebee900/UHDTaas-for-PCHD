# ahdt.immune_lymphatic.t_cell_b_cell_and_macrophage

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | immune_lymphatic |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Adaptive immune response to an antigen: T cell, B cell and macrophage counts |
| Regulatory status | research |
| Source | Murali-Krishna K, Altman JD, Suresh M, Sourdive DJ, Zajac AJ, Miller JD, Slansky J, Ahmed R. Counting antigen-specific CD8 T cells: a reevaluation of bystander activation during viral infection. Immunity. 1998;8:177-187. doi:10.1016/s1074-7613(00)80470-7; ATRA design 01 rule R5 assumption register |
| Fidelity note | Qualitative agent-based model on a lymph node section. Cell counts are those of the model population, not of the whole body. Rate parameters are assumptions listed on the card. |
| Validation | Murali-Krishna 1998: memory cells are about 5 percent of the peak effector number; antigen cleared by day 16: memory_fraction_error = -0.0115832 (tolerance 0.03, passed) |

## Inputs

- `antigen_load` (1) from `input:scenario`

## Outputs

- `naive_t_cells` ({cells})
- `effector_t_cells` ({cells})
- `memory_t_cells` ({cells})
- `naive_b_cells` ({cells})
- `plasma_cells` ({cells})
- `active_macrophages` ({cells})
- `antibody` (1)
- `antigen` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `grid_size` | 30 | {cells} | atra-assumption | assumption |
| `naive_t` | 1000 | {cells} | atra-assumption | assumption |
| `naive_b` | 300 | {cells} | atra-assumption | assumption |
| `macrophages` | 60 | {cells} | atra-assumption | assumption |
| `p_activation` | 0.05 | 1 | atra-assumption | assumption |
| `division_ticks` | 16 | {ticks} | atra-assumption | assumption |
| `effector_limit` | 2500 | {cells} | atra-assumption | assumption |
| `effector_death_rate` | 0.005 | 1 | atra-assumption | assumption |
| `memory_fraction` | 0.05 | 1 | murali-krishna1998 | unverified |
| `p_b_activation` | 0.02 | 1 | atra-assumption | assumption |
| `antibody_secretion` | 0.002 | 1 | atra-assumption | assumption |
| `plasma_death_rate` | 0.0015 | 1 | atra-assumption | assumption |
| `neutralisation` | 0.0004 | 1 | atra-assumption | assumption |
| `antibody_half_life_ticks` | 1008 | {ticks} | atra-assumption | assumption |
| `uptake_resting` | 0.0005 | 1 | atra-assumption | assumption |
| `uptake_active` | 0.004 | 1 | atra-assumption | assumption |
| `uptake_half` | 50 | 1 | atra-assumption | assumption |
| `dendritic_arrival` | 0.1 | {cells} | atra-assumption | assumption |
| `dendritic_lifetime_ticks` | 100 | {ticks} | atra-assumption | assumption |
| `antigen_growth` | 0.02 | 1 | atra-assumption | assumption |
| `antigen_ceiling` | 100000 | 1 | atra-assumption | assumption |
| `antigen_half` | 100 | 1 | atra-assumption | assumption |
| `antigen_floor` | 0.5 | 1 | atra-assumption | assumption |
| `antigen_clearance_threshold` | 1 | 1 | atra-assumption | assumption |
| `effector_kill` | 0.03 | 1 | atra-assumption | assumption |
| `effector_kill_half` | 300 | {cells} | atra-assumption | assumption |
| `p_memory_recall` | 0.2 | 1 | atra-assumption | assumption |

## Sources

- **murali-krishna1998**: Murali-Krishna K, Altman JD, Suresh M, Sourdive DJ, Zajac AJ, Miller JD, Slansky J, Ahmed R. Counting antigen-specific CD8 T cells: a reevaluation of bystander activation during viral infection. Immunity. 1998;8:177-187. doi:10.1016/s1074-7613(00)80470-7
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `grid_size`: Lymph node section of 30 x 30 grid cells at 100 micrometres each (3 mm square); the size keeps one run under a minute
- `naive_t`: Population of the modelled section, sized so that dendritic cell contacts occur on the hour scale; not a body-wide count
- `naive_b`: Population of the modelled section, one third of the naive T cell number
- `macrophages`: Resident antigen-clearing cells of the modelled section
- `p_activation`: No published per-tick contact outcome matches this grid; chosen so that priming takes a few days
- `division_ticks`: A tick is 30 minutes, so 16 ticks is 8 hours; the interval is an assumption of this model
- `effector_limit`: Caps clonal expansion at the modelled section size; the peak magnitude is not calibrated to data
- `effector_death_rate`: Sets contraction over days after clearance; the rate is an assumption
- `memory_fraction`: The paper reports memory cells at about 5 percent of the peak effector number; the value was not re-checked against the figure data
- `p_b_activation`: T cell help is required; the rate is an assumption
- `antibody_secretion`: Arbitrary antibody units; scaled with the neutralisation rate
- `plasma_death_rate`: Short-lived plasma cells; the rate is an assumption
- `neutralisation`: Arbitrary units paired with antibody_secretion
- `antibody_half_life_ticks`: 1008 ticks is 21 days, the half-life of IgG in blood; applied to the modelled section
- `uptake_resting`: Resting macrophages clear slowly; the rate is an assumption
- `uptake_active`: Activation by effector T cells raises uptake several fold; the factor is an assumption
- `uptake_half`: Saturating uptake; the level is an assumption
- `dendritic_arrival`: Antigen-driven recruitment; the rate is an assumption
- `dendritic_lifetime_ticks`: 100 ticks is about 2 days of antigen presentation; an assumption
- `antigen_growth`: Growth per 30-minute tick of a replicating pathogen, about 2.6 fold per day; set so that antigen peaks on day 2 to 3 and clears within a week
- `antigen_ceiling`: Arbitrary units
- `antigen_half`: Arbitrary units
- `antigen_floor`: Arbitrary units; removes a numerical tail
- `antigen_clearance_threshold`: Arbitrary units
- `effector_kill`: Maximum fraction of antigen removed per tick by effector T cells; tuned so that clearance follows the effector expansion over days
- `effector_kill_half`: Effector number at half the maximum kill rate; the value is an assumption
- `p_memory_recall`: Faster secondary response; the rate is an assumption
