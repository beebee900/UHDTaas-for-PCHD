# ahdt.whole_body.biomechanical_and_kinematic

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Whole-body joint kinematics of walking from a phone-video pose track |
| Regulatory status | research |
| Source | OpenSim gait2392 generic musculoskeletal model, Thelen 2003 muscles (CC BY 3.0). Delp SL, Loan JP, Hoy MG, Zajac FE, Topp EL, Rosen JM. An interactive graphics-based model of the lower extremity to study orthopaedic surgical procedures. IEEE Trans Biomed Eng. 1990;37(8):757-767.; ATRA design 01 rule R5 assumption register |
| Fidelity note | OpenSim gait2392 inverse kinematics of virtual hip, knee, ankle, heel and toe markers; the lateral coordinate is the model's, so frontal-plane motion is not measured. |
| Validation | Inverse kinematics of markers made by the gait2392 model itself; the markers of the recovered pose against the markers given: marker_rms_error_m = 0.000810674 (tolerance 0.005, passed) |

## Inputs

- `pose_track` (1) from `input:scenario`

## Outputs

- `hip_flexion_range` (deg)
- `knee_flexion_peak` (deg)
- `ankle_angle_range` (deg)
- `pelvis_vertical_range` (m)
- `marker_rms_error` (m)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `toe_tip_ahead_m` | 0.06 | m | atra-assumption | assumption |
| `analysis_seconds` | 3 | s | atra-assumption | assumption |
| `min_coverage` | 0.8 | 1 | atra-assumption | assumption |
| `marker_cutoff_hz` | 6 | Hz | atra-assumption | assumption |
| `weight_hip` | 1 | 1 | atra-assumption | assumption |
| `weight_knee` | 1 | 1 | atra-assumption | assumption |
| `weight_ankle` | 1 | 1 | atra-assumption | assumption |
| `weight_foot` | 0.5 | 1 | atra-assumption | assumption |

## Sources

- **gait2392**: OpenSim gait2392 generic musculoskeletal model, Thelen 2003 muscles (CC BY 3.0). Delp SL, Loan JP, Hoy MG, Zajac FE, Topp EL, Rosen JM. An interactive graphics-based model of the lower extremity to study orthopaedic surgical procedures. IEEE Trans Biomed Eng. 1990;37(8):757-767. Via: model file credits and publications fields; file pinned in sources.lock.yaml (gait2392).
- **atra-assumption**: ATRA design 01 rule R5 assumption register

## Open items for sign-off

- `toe_tip_ahead_m`: Distance from the metatarsophalangeal joint of the model to the foot index landmark of the pose model; the model has no marker set
- `analysis_seconds`: Length of the analysed window of a pose track; about three strides at a normal cadence, and short enough for one persona run to stay under two minutes
- `min_coverage`: Smallest share of frames in which all leg landmarks are detected; the same limit as the gait feature extraction of the edge service
- `marker_cutoff_hz`: Low-pass cut-off of the landmark paths; the same cut-off as the gait feature extraction of the edge service
- `weight_hip`: Inverse kinematics weight of the hip markers
- `weight_knee`: Inverse kinematics weight of the knee markers
- `weight_ankle`: Inverse kinematics weight of the ankle markers
- `weight_foot`: Inverse kinematics weight of the heel and toe markers, lower because the foot landmarks of the pose model are the least stable
