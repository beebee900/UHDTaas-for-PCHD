# ahdt.musculoskeletal.skeletal_muscle_and_biomechanics

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | musculoskeletal |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Joint angles and muscle forces of walking from a phone-video pose track |
| Regulatory status | research |
| Source | OpenSim gait2392 generic musculoskeletal model, Thelen 2003 muscles (CC BY 3.0). Delp SL, Loan JP, Hoy MG, Zajac FE, Topp EL, Rosen JM. An interactive graphics-based model of the lower extremity to study orthopaedic surgical procedures. IEEE Trans Biomed Eng. 1990;37(8):757-767.; ATRA design 01 rule R5 assumption register |
| Fidelity note | OpenSim gait2392. The ground reaction force is an assumption: it is estimated from the centre of mass and the foot contact, not measured. Static optimisation covers one stride sampled at 15 Hz and ignores the force-length-velocity dependence of muscle. The reserve force peak shows how much load the muscles could not carry. |
| Validation | Estimated ground reaction force over whole strides; mean vertical force equals body weight: relative_error_mean_vertical_force = 0.0106824 (tolerance 0.05, passed) |

## Inputs

- `pose_track` (1) from `input:scenario`

## Outputs

- `knee_flexion_peak` (deg)
- `hip_flexion_range` (deg)
- `ankle_angle_range` (deg)
- `quadriceps_peak_force` (N)
- `plantarflexor_peak_force` (N)
- `hamstring_peak_force` (N)
- `marker_rms_error` (m)
- `reserve_force_peak` (N)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `toe_tip_ahead_m` | 0.06 | m | atra-assumption | assumption |
| `analysis_seconds` | 3 | s | atra-assumption | assumption |
| `min_coverage` | 0.8 | 1 | atra-assumption | assumption |
| `marker_cutoff_hz` | 6 | Hz | atra-assumption | assumption |
| `coordinate_cutoff_hz` | 6 | Hz | atra-assumption | assumption |
| `weight_hip` | 1 | 1 | atra-assumption | assumption |
| `weight_knee` | 1 | 1 | atra-assumption | assumption |
| `weight_ankle` | 1 | 1 | atra-assumption | assumption |
| `weight_foot` | 0.5 | 1 | atra-assumption | assumption |
| `com_window_s` | 0.3 | s | atra-assumption | assumption |
| `contact_softness_m` | 0.04 | m | atra-assumption | assumption |
| `so_max_iterations` | 40 | 1 | atra-assumption | assumption |
| `so_window_s` | 1.5 | s | atra-assumption | assumption |
| `so_rate_hz` | 15 | Hz | atra-assumption | assumption |

## Sources

- **gait2392**: OpenSim gait2392 generic musculoskeletal model, Thelen 2003 muscles (CC BY 3.0). Delp SL, Loan JP, Hoy MG, Zajac FE, Topp EL, Rosen JM. An interactive graphics-based model of the lower extremity to study orthopaedic surgical procedures. IEEE Trans Biomed Eng. 1990;37(8):757-767. Via: model file credits and publications fields; file pinned in sources.lock.yaml (gait2392).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `toe_tip_ahead_m`: Distance from the metatarsophalangeal joint of the model to the foot index landmark of the pose model; the model has no marker set
- `analysis_seconds`: Length of the analysed window of a pose track; about three strides at a normal cadence, and short enough for one persona run to stay under two minutes
- `min_coverage`: Smallest share of frames in which all leg landmarks are detected; the same limit as the gait feature extraction of the edge service
- `marker_cutoff_hz`: Low-pass cut-off of the landmark paths; the same cut-off as the gait feature extraction of the edge service
- `coordinate_cutoff_hz`: Low-pass cut-off of the joint angles before static optimisation
- `weight_hip`: Inverse kinematics weight of the hip markers
- `weight_knee`: Inverse kinematics weight of the knee markers
- `weight_ankle`: Inverse kinematics weight of the ankle markers
- `weight_foot`: Inverse kinematics weight of the heel and toe markers, lower because the foot landmarks of the pose model are the least stable
- `com_window_s`: Window of the polynomial smoother that differentiates the centre of mass twice for the estimated ground reaction force
- `contact_softness_m`: Height of a foot marker above its standing height over which the estimated contact falls from one to zero
- `so_max_iterations`: Iteration limit of the static optimisation at each frame; a limit of 200 left the objective of the test stride unchanged and took five times as long
- `so_window_s`: Length of the motion given to static optimisation, about one stride at a normal cadence; keeps one persona run under two minutes
- `so_rate_hz`: Sampling rate of the motion given to static optimisation; below the 6 Hz cut-off times two so the accelerations stay defined
