# ahdt.whole_body.anatomical_avatar

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | simulation |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Scale factors of the 3-D body viewer and body size indices |
| Regulatory status | research |
| Source | Mosteller RD. Simplified calculation of body-surface area. N Engl J Med. 1987;317(17):1098. doi:10.1056/NEJM198710223171717; ATRA viewer reference mesh (WP19); its own dimensions, not clinical values |
| Validation | Mosteller 1987: 180 cm and 80 kg give 2.0 m2: bsa_error_m2 = 0 (tolerance 1e-09, passed) |

## Inputs

- `height` (cm) from `field:8302-2`
- `weight` (kg) from `field:29463-7`
- `waist` (cm) from `field:8280-0`

## Outputs

- `scale_vertical` (1)
- `scale_lateral` (1)
- `scale_depth` (1)
- `bmi` (kg/m2)
- `bsa` (m2)

## Parameters

| Name | Value | Unit | Source | Status |
|---|---|---|---|---|
| `mesh_height` | 175 | cm | atra-mesh | assumption |
| `mesh_weight` | 70 | kg | atra-mesh | assumption |
| `mesh_waist` | 85 | cm | atra-mesh | assumption |

## Sources

- **mosteller1987**: Mosteller RD. Simplified calculation of body-surface area. N Engl J Med. 1987;317(17):1098. doi:10.1056/NEJM198710223171717
- **atra-mesh**: ATRA viewer reference mesh (WP19); its own dimensions, not clinical values

## Open items for sign-off

- `mesh_height`: Height of the reference mesh as modelled
- `mesh_weight`: Body mass the reference mesh represents
- `mesh_waist`: Waist circumference of the reference mesh
