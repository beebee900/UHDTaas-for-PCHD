# ahdt.cardiovascular.baroreflex_regulation

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Short-term autonomic control of heart rate, contractility and resistance |
| Regulatory status | research |
| Source | Ursino M. Interaction between carotid baroregulation and the pulsating heart: a mathematical model. Am J Physiol. 1998;275(5):H1733-H1747. doi:10.1152/ajpheart.1998.275.5.H1733; Kana M. Mathematical models of cardiovascular control by the autonomic nervous system. Doctoral thesis, Czech Technical University in Prague; 2010. Tables 2.5.2 to 2.5.14, values from Ursino M, Magosso E. Acute cardiovascular response to isocapnic hypoxia. I. A mathematical model. Am J Physiol Heart Circ Physiol. 2000;279(1):H149-H165 |
| Validity | {'timescale': 'seconds to minutes'} |
| Validation | Ursino 1998 afferent sigmoid; firing at P_n is the midpoint: midpoint_error_hz = 0 (tolerance 1e-09, passed) |

## Inputs

- `map` (mm[Hg]) from `model:ahdt.cardiovascular.heart_chambers_and_valves#map`

## Outputs

- `heart_rate` (/min)
- `contractility_factor` (1)
- `resistance_factor` (1)
- `sympathetic_activity` (Hz)
- `vagal_activity` (Hz)
- `afferent_activity` (Hz)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `P_n` | 92 | mm[Hg] | ursino1998 | unverified |
| `k_ab` | 11.758 | mm[Hg] | ursino1998 | unverified |
| `f_ab_min` | 2.52 | Hz | ursino1998 | unverified |
| `f_ab_max` | 47.78 | Hz | ursino1998 | unverified |
| `tau_z` | 6.37 | s | ursino1998 | unverified |
| `tau_p` | 2.076 | s | ursino1998 | unverified |
| `f_es_inf` | 2.1 | Hz | kana2010 | published |
| `f_es_0` | 16.11 | Hz | kana2010 | published |
| `f_es_min` | 2.66 | Hz | kana2010 | published |
| `k_es` | 0.0675 | s | kana2010 | published |
| `f_ev_0` | 3.2 | Hz | kana2010 | published |
| `f_ev_inf` | 6.3 | Hz | ursino1998 | unverified |
| `f_ab_0` | 25 | Hz | ursino1998 | unverified |
| `k_ev` | 7.06 | Hz | kana2010 | published |
| `G_E` | 0.475 | mm[Hg]/mL | kana2010 | published |
| `tau_E` | 8 | s | kana2010 | published |
| `D_E` | 2 | s | kana2010 | published |
| `E_0` | 2.392 | mm[Hg]/mL | kana2010 | published |
| `G_R` | 0.695 | mm[Hg].s/mL | ursino1998 | unverified |
| `tau_R` | 6 | s | kana2010 | published |
| `D_R` | 2 | s | ursino1998 | unverified |
| `R_0` | 2.49 | mm[Hg].s/mL | kana2010 | published |
| `G_Ts` | -0.13 | s | kana2010 | published |
| `tau_Ts` | 2 | s | kana2010 | published |
| `D_Ts` | 2 | s | kana2010 | published |
| `G_Tv` | 0.09 | s | kana2010 | published |
| `tau_Tv` | 1.5 | s | kana2010 | published |
| `D_Tv` | 0.2 | s | kana2010 | published |
| `T_0` | 0.58 | s | ursino1998 | unverified |

## Sources

- **ursino1998**: Ursino M. Interaction between carotid baroregulation and the pulsating heart: a mathematical model. Am J Physiol. 1998;275(5):H1733-H1747. doi:10.1152/ajpheart.1998.275.5.H1733
- **kana2010**: Kana M. Mathematical models of cardiovascular control by the autonomic nervous system. Doctoral thesis, Czech Technical University in Prague; 2010. Tables 2.5.2 to 2.5.14, values from Ursino M, Magosso E. Acute cardiovascular response to isocapnic hypoxia. I. A mathematical model. Am J Physiol Heart Circ Physiol. 2000;279(1):H149-H165

## Open items for sign-off

- `P_n`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `k_ab`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `f_ab_min`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `f_ab_max`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `tau_z`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `tau_p`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `f_ev_inf`: Ursino 1998 value; Kana 2010 Table 2.5.5 lists 2.1 Hz for a differently structured vagal neuron, so the primary value needs a check
- `f_ab_0`: Ursino 1998 Table 1 value; primary text not reachable (HTTP 403)
- `G_R`: Ursino 1998 splanchnic resistance gain; Kana 2010 uses a different vascular-bed structure, so the primary value needs a check
- `D_R`: Ursino 1998 value; Kana 2010 uses 5 s in a different structure
- `T_0`: Ursino 1998 heart period with no autonomic input; primary text not reachable (HTTP 403)
