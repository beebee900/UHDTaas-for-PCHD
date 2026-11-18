"""The models and corpora of WP14d with their licences (design 01, 1.3; design 06, 6.6).

Each Hugging Face entry names the repository, the files to fetch and the licence on its model
card. `fetch.py` downloads them on the VM and records size and SHA-256 per file. The
`MMS` and `NLLB` entries are CC BY-NC 4.0, so the adapters and voices trained from them are
research-only (design 01, 1.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

LICENCE_NC = "CC-BY-NC-4.0"


@dataclass(frozen=True)
class HFModel:
    key: str
    repo: str
    licence: str
    use: str
    files: tuple[str, ...] = ()
    """Files to fetch; empty means every file of the repository that `skip` does not exclude."""
    skip: tuple[str, ...] = ()
    kind: str = "model"
    subfolder_files: tuple[tuple[str, str], ...] = field(default=())


MODELS: tuple[HFModel, ...] = (
    HFModel("qwen", "Qwen/Qwen2.5-0.5B-Instruct", "Apache-2.0",
            "LoRA base model (PEFT) and reference weights of the edge SLM",
            skip=("*.md", "LICENSE")),
    HFModel("mms-asr", "facebook/mms-1b-all", LICENCE_NC, "STT for yo, ha, ig (language adapters)",
            files=("config.json", "model.safetensors", "vocab.json", "tokenizer_config.json",
                   "special_tokens_map.json", "preprocessor_config.json",
                   "adapter.yor.safetensors", "adapter.hau.safetensors",
                   "adapter.ibo.safetensors")),
    HFModel("mms-tts-yor", "facebook/mms-tts-yor", LICENCE_NC, "Yoruba TTS; Igbo fine-tune base",
            files=("config.json", "model.safetensors", "vocab.json", "tokenizer_config.json",
                   "special_tokens_map.json")),
    HFModel("mms-tts-hau", "facebook/mms-tts-hau", LICENCE_NC, "Hausa TTS",
            files=("config.json", "model.safetensors", "vocab.json", "tokenizer_config.json",
                   "special_tokens_map.json")),
    HFModel("mms-tts-eng", "facebook/mms-tts-eng", LICENCE_NC,
            "English and Pidgin round-trip voice (server side)",
            files=("config.json", "model.safetensors", "vocab.json", "tokenizer_config.json",
                   "special_tokens_map.json")),
    HFModel("mms-tts-yor-disc", "facebook/mms-tts", LICENCE_NC,
            "Original Yoruba discriminator checkpoint for the VITS fine-tune",
            files=("full_models/yor/D_100000.pth", "full_models/yor/config.json")),
    HFModel("whisper-small", "Systran/faster-whisper-small", "MIT",
            "STT for en and pcm (CTranslate2 conversion of OpenAI Whisper small)"),
    HFModel("nllb", "facebook/nllb-200-distilled-600M", LICENCE_NC,
            "Translation of the English dialogues into yo, ha, ig; back-translation check",
            files=("config.json", "generation_config.json", "pytorch_model.bin",
                   "sentencepiece.bpe.model", "special_tokens_map.json", "tokenizer.json",
                   "tokenizer_config.json")),
    HFModel("bge-reranker", "BAAI/bge-reranker-base", "MIT", "Cross-encoder re-ranker",
            files=("config.json", "model.safetensors", "sentencepiece.bpe.model",
                   "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json")),
    HFModel("biolord", "FremyCompany/BioLORD-2023", "other (see model card)",
            "Biomedical sentence embeddings",
            skip=("pytorch_model.bin", "*.md", ".gitattributes")),
    HFModel("waxal-ibo", "google/WaxalNLP", "CC-BY-SA-4.0 / CC-BY-4.0 (see dataset card)",
            "Igbo TTS speech for the VITS fine-tune",
            files=("data/TTS/ibo/ibo-train-00000.parquet",
                   "data/TTS/ibo/ibo-validation-00000.parquet",
                   "data/TTS/ibo/ibo-test-00000.parquet"), kind="dataset"),
)

MAFAND_URL = "https://raw.githubusercontent.com/masakhane-io/lafand-mt/main/data/json_files"
MAFAND_PAIRS = ("en-pcm", "en-yor", "en-hau", "en-ibo")
MENYO_URL = "https://github.com/uds-lsv/menyo-20k_MT/archive/refs/heads/master.zip"
FINETUNE_HF_VITS_URL = "https://github.com/ylacombe/finetune-hf-vits/archive/refs/heads/main.zip"
