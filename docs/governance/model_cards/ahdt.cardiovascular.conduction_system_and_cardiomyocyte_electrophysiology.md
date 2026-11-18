# ahdt.cardiovascular.conduction_system_and_cardiomyocyte_electrophysiology

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | cardiovascular |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | UBERON:0000948 |
| Intended use | Action potential duration, QT surrogate and conduction velocity of ventricular tissue, with IKr block scenarios |
| Regulatory status | research |
| Source | ten Tusscher KHWJ, Panfilov AV. Alternans and spiral breakup in a human ventricular tissue model. Am J Physiol Heart Circ Physiol. 2006;291(3):H1088-H1100. doi:10.1152/ajpheart.00109.2006; openCARP v20.0 simulator, AppImage pinned in sources.lock.yaml (opencarp-appimage); Plank G et al. The openCARP simulation environment for cardiac electrophysiology. Comput Methods Programs Biomed. 2021;208:106223. doi:10.1016/j.cmpb.2021.106223; ATRA design 01 rule R5 assumption register |
| Fidelity note | Epicardial ten Tusscher-Panfilov cells on a 2D slab; the QT surrogate runs from the first activation to the last repolarisation of the slab, not of the ventricle. |
| Validation | openCARP bench, same ten Tusscher-Panfilov cell paced at 1 Hz, last beat: relative_error_tissue_apd90 = 0.0259553 (tolerance 0.05, passed) |

## Inputs

- `heart_rate` (/min) from `model:ahdt.cardiovascular.heart_chambers_and_valves#heart_rate`
- `ikr_block` (1) from `input:scenario`

## Outputs

- `apd90` (ms)
- `qt_surrogate` (ms)
- `conduction_velocity` (m/s)
- `apd90_dispersion` (ms)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `g_il` | 0.174 | S/m | opencarp | published |
| `g_it` | 0.019 | S/m | opencarp | published |
| `g_el` | 0.625 | S/m | opencarp | published |
| `g_et` | 0.236 | S/m | opencarp | published |
| `slab_length_cm` | 2 | cm | atra-assumption | assumption |
| `slab_width_cm` | 0.5 | cm | atra-assumption | assumption |
| `resolution_um` | 250 | um | atra-assumption | assumption |
| `dt_us` | 25 | us | atra-assumption | assumption |
| `stimulus_strength` | 40 | uA/cm2 | atra-assumption | assumption |
| `stimulus_duration_ms` | 2 | ms | atra-assumption | assumption |
| `activation_threshold_mv` | -40 | mV | atra-assumption | assumption |
| `repolarisation_fraction` | 0.9 | 1 | atra-assumption | assumption |
| `beats` | 2 | 1 | atra-assumption | assumption |

## Sources

- **tt2006**: ten Tusscher KHWJ, Panfilov AV. Alternans and spiral breakup in a human ventricular tissue model. Am J Physiol Heart Circ Physiol. 2006;291(3):H1088-H1100. doi:10.1152/ajpheart.00109.2006 Via: openCARP v20.0 ionic model tenTusscherPanfilov (limpet model file header and source).
- **opencarp**: openCARP v20.0 simulator, AppImage pinned in sources.lock.yaml (opencarp-appimage); Plank G et al. The openCARP simulation environment for cardiac electrophysiology. Comput Methods Programs Biomed. 2021;208:106223. doi:10.1016/j.cmpb.2021.106223 Via: default conductivities read with openCARP --doc gregion.g_il and the related keys.
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `slab_length_cm`: Size of the tissue slab; long enough for a conduction velocity fit and small enough to run in under a minute
- `slab_width_cm`: Width of the tissue slab
- `resolution_um`: Element edge; the usual 200 to 500 micrometre range of tissue simulations
- `dt_us`: Time step of the solver
- `stimulus_strength`: Transmembrane current of the pacing stimulus; supra-threshold, checked by the activation of the whole slab
- `stimulus_duration_ms`: Duration of the pacing stimulus
- `activation_threshold_mv`: Membrane potential crossing that defines the activation time
- `repolarisation_fraction`: APD90 is the time from activation to repolarisation of 90 percent of the amplitude
- `beats`: Paced beats simulated; the last beat is analysed
