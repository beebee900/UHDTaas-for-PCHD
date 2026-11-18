# apdt.language.lora_ig

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | slm |
| Fidelity tier | T1 |
| Intended use | Igbo health dialogue style for the local small model (research) |
| Regulatory status | research |
| Source | Hu EJ, Shen Y, Wallis P, et al. LoRA: low-rank adaptation of large language models. ICLR 2022; PEFT (Mangrulkar S et al., Hugging Face); base model Qwen2.5-0.5B-Instruct (Qwen Team, Apache-2.0) |
| Licence | The base voice facebook/mms-tts-yor and the NLLB-200 translations used for the training text are CC BY-NC 4.0: research use only, no commercial use. |
| Validation | MAFAND-MT test (n=40), English to the language: chrf = 17.28 (2026-10-12) |

## Limits

- Medical-dialogue quality in this language is not verified by a clinician or a native-speaking rater.
- The training text is machine-translated or templated; the numbers measure agreement with those references and with human translations of news text.

## Training

- steps: 191
- batch: 2
- rank: 16
- train_examples: 618
- seconds: 3858
- dev_loss: 0.7923
- train_loss_first10: 4.171
- train_loss_last10: 0.6199
