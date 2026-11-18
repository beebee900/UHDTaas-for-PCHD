# ahdt.nervous.neuron_and_circuit

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | nervous |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Teaching illustration of action potentials and network excitability |
| Regulatory status | research |
| Source | Hodgkin AL, Huxley AF. A quantitative description of membrane current and its application to conduction and excitation in nerve. J Physiol. 1952;117(4):500-544. doi:10.1113/jphysiol.1952.sp004764; FitzHugh R. Impulses and physiological states in theoretical models of nerve membrane. Biophys J. 1961;1(6):445-466. doi:10.1016/S0006-3495(61)86902-6 |
| Fidelity note | Educational fidelity: squid axon and a dimensionless ring network |
| Validation | Hodgkin and Huxley 1952 action potential of about 100 mV: peak_depolarisation_minus_100_mv = 4.78953 (tolerance 15, passed) |

## Inputs

- `stimulus` (uA/cm2) from `input:scenario`
- `ring_stimulus` (1) from `input:scenario`

## Outputs

- `membrane_depolarisation` (mV)
- `fhn_mean_activity` (1)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `Cm` | 1 | uF/cm2 | hh1952 | published |
| `g_Na` | 120 | mS/cm2 | hh1952 | published |
| `g_K` | 36 | mS/cm2 | hh1952 | published |
| `g_L` | 0.3 | mS/cm2 | hh1952 | published |
| `V_Na` | -115 | mV | hh1952 | published |
| `V_K` | 12 | mV | hh1952 | published |
| `V_L` | -10.613 | mV | hh1952 | published |
| `E_R` | -75 | mV | hh1952 | published |
| `fhn_a` | 0.7 | 1 | fitzhugh1961 | published |
| `fhn_b` | 0.8 | 1 | fitzhugh1961 | published |
| `fhn_c` | 3 | 1 | fitzhugh1961 | published |
| `fhn_coupling` | 0.1 | 1 | fitzhugh1961 | assumption |

## Sources

- **hh1952**: Hodgkin AL, Huxley AF. A quantitative description of membrane current and its application to conduction and excitation in nerve. J Physiol. 1952;117(4):500-544. doi:10.1113/jphysiol.1952.sp004764 Via: BioModels BIOMD0000000020 (original sign convention, V as depolarisation from rest).
- **fitzhugh1961**: FitzHugh R. Impulses and physiological states in theoretical models of nerve membrane. Biophys J. 1961;1(6):445-466. doi:10.1016/S0006-3495(61)86902-6 Via: BioModels BIOMD0000000346.

## Open items for sign-off

- `fhn_coupling`: Diffusive coupling strength of the illustrative ring network; FitzHugh (1961) describes a single unit
