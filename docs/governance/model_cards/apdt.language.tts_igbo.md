# apdt.language.tts_igbo

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | ml |
| Fidelity tier | T1 |
| Intended use | Igbo text-to-speech voice for phone and kiosk channels (research) |
| Regulatory status | research |
| Source | Kim J, Kong J, Son J. Conditional variational autoencoder with adversarial learning for end-to-end text-to-speech. ICML 2021; Pratap V et al. Scaling speech technology to 1,000+ languages. JMLR 2024 (MMS); recipe by Lacombe Y (finetune-hf-vits, MIT) |
| Licence | The base voice facebook/mms-tts-yor and the NLLB-200 translations used for the training text are CC BY-NC 4.0: research use only, no commercial use. |
| Validation | NLLB-translated Igbo sentences, TTS then STT round trip: wer = 0.975 (2026-10-12) |

## Limits

- Medical-dialogue quality in this language is not verified by a clinician or a native-speaking rater.
- The training text is machine-translated or templated; the numbers measure agreement with those references and with human translations of news text.

## Training

- steps: 192
- batch: 4
- samples: 93
- seconds: 8934
- mel_first_fifth: 0.3997
- mel_last_fifth: 0.3527
