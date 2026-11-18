# ahdt.whole_body.early_warning

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | whole_body |
| Family | semantic |
| Fidelity tier | T2 |
| Anatomy | none |
| Intended use | Physiological early-warning score and escalation band |
| Regulatory status | research |
| Source | Royal College of Physicians. National Early Warning Score (NEWS) 2: standardising the assessment of acute-illness severity in the NHS. London: RCP; 2017. NHS England. National PEWS observation and escalation charts. 2023. Scoring tables in kb/news2.yaml and kb/pews.yaml |
| Validation | NEWS2 chart: RR 24, SpO2 95 %, SBP 105, HR 112, 38.6 Cel, alert scores 7: score_error = 0 (tolerance 0, passed) |

## Inputs

- `respiration_rate` (/min) from `field:9279-1`
- `spo2` (%) from `field:59408-5`
- `systolic_bp` (mm[Hg]) from `field:8480-6`
- `pulse` (/min) from `field:8867-4`
- `temperature` (Cel) from `field:8310-5`
- `consciousness` ({ACVPU}) from `consciousness`
- `on_oxygen` (1) from `on_oxygen`
- `spo2_scale` (1) from `spo2_scale`
- `age` (a) from `age`
- `respiratory_distress` ({grade}) from `respiratory_distress`
- `respiratory_support` ({device}) from `respiratory_support`
- `oxygen_flow` (L/min) from `oxygen_flow`
- `fio2` (%) from `fio2`
- `capillary_refill` (s) from `capillary_refill`
- `pews_triggers` ({trigger}) from `pews_triggers`

## Outputs

- `news2` ({score})
- `news2_band` ({band})
- `pews` ({score})
- `pews_level` ({level})
