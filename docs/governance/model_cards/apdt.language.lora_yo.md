# apdt.language.lora_yo

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Twin | apdt |
| Family | slm |
| Fidelity tier | T1 |
| Intended use | Yoruba health dialogue style for the local small model (research) |
| Regulatory status | research |
| Source | Hu EJ, Shen Y, Wallis P, et al. LoRA: low-rank adaptation of large language models. ICLR 2022; PEFT (Mangrulkar S et al., Hugging Face); base model Qwen2.5-0.5B-Instruct (Qwen Team, Apache-2.0) |
| Licence | The base voice facebook/mms-tts-yor and the NLLB-200 translations used for the training text are CC BY-NC 4.0: research use only, no commercial use. |
| Validation | MENYO-20k test (n=40), English to the language: chrf = 14.02 (2026-10-12) |

## Limits

- Medical-dialogue quality in this language is not verified by a clinician or a native-speaking rater.
- The training text is machine-translated or templated; the numbers measure agreement with those references and with human translations of news text.

## Training

- steps: 159
- batch: 2
- rank: 16
- train_examples: 618
- seconds: 3706
- dev_loss: 0.4972
- train_loss_first10: 3.242
- train_loss_last10: 1.702
