# ahdt.cardiovascular.coronary_cerebral_peripheral_vasculature_and_microcirculation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0001637 |
| Intended use | Regional blood flow and perfusion from arterial pressure |
| Regulatory status | research |
| Source | Westerhof N, Lankhaar JW, Westerhof BE. The arterial Windkessel. Med Biol Eng Comput. 2009;47(2):131-141. doi:10.1007/s11517-008-0359-2; Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021. Blood flow to organs and tissues under basal conditions; ATRA design 01 rule R5 assumption register |
| Validation | Bed flows at the reference pressure equal their cardiac-output shares: relative_error_cerebral_flow = 1.13687e-15 (tolerance 1e-06, passed) |

## Inputs

- `map` (mm[Hg]) from `model:ahdt.cardiovascular.heart_chambers_and_valves#map`
- `resistance_factor` (1) from `model:ahdt.cardiovascular.baroreflex_regulation#resistance_factor`
- `endothelial_function` (1) from `model:ahdt.cardiovascular.vascular_endothelium#endothelial_function`

## Outputs

- `coronary_flow` (mL/min)
- `cerebral_flow` (mL/min)
- `peripheral_flow` (mL/min)
- `resistance` (mm[Hg].s/mL)
- `compliance` (mL/mm[Hg])
- `perfusion_index` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `share_coronary` | 0.04 | 1 | guyton | unverified |
| `share_cerebral` | 0.14 | 1 | guyton | unverified |
| `share_peripheral` | 0.21 | 1 | guyton | unverified |
| `rc_fraction` | 0.05 | 1 | westerhof2009 | assumption |
| `tau_bed` | 1.5 | s | atra-assumption | assumption |
| `map_ref` | 93 | mm[Hg] | atra-assumption | assumption |
| `co_ref` | 5 | L/min | guyton | unverified |

## Sources

- **westerhof2009**: Westerhof N, Lankhaar JW, Westerhof BE. The arterial Windkessel. Med Biol Eng Comput. 2009;47(2):131-141. doi:10.1007/s11517-008-0359-2
- **guyton**: Hall JE, Hall ME. Guyton and Hall Textbook of Medical Physiology. 14th ed. Elsevier; 2021. Blood flow to organs and tissues under basal conditions
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `share_coronary`: Basal coronary flow 200 of 5000 mL/min as recalled from the Guyton and Hall table; edition and page need a check
- `share_cerebral`: Basal brain flow 700 of 5000 mL/min as recalled from the Guyton and Hall table; edition and page need a check
- `share_peripheral`: Basal skeletal muscle (15 %) plus skin (6 %) flow as recalled from the Guyton and Hall table; needs a check
- `rc_fraction`: Characteristic impedance taken as 5 % of bed resistance, the order of magnitude described for the systemic Windkessel
- `tau_bed`: Bed diastolic decay time constant R*C; no per-bed published value located
- `map_ref`: Reference mean arterial pressure used to size bed resistances
- `co_ref`: Basal cardiac output of the Guyton and Hall table; needs a check
