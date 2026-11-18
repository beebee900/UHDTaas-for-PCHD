"""The local small model: PEFT host with adapters (tiny random model) and the GGUF model."""

from __future__ import annotations

import string
from pathlib import Path

import pytest
import torch

from ahdt.models.language.slm import LocalizedSLM, adapter_dir, slm_factory
from atra.config import ROOT, LLMSettings, Settings

GGUF = ROOT / "var" / "wp14d" / "models" / "gguf" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
TEMPLATE = ("{% for m in messages %}{{ m['content'] }}{% endfor %}"
            "{% if add_generation_prompt %}>{% endif %}")


def tiny_base(path: Path) -> None:
    from tokenizers import Regex, Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

    chars = [*string.printable, "<pad>", "<unk>"]
    tk = Tokenizer(models.WordLevel({c: i for i, c in enumerate(chars)}, unk_token="<unk>"))
    tk.pre_tokenizer = pre_tokenizers.Split(Regex("."), "isolated")
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, pad_token="<pad>", unk_token="<unk>")
    tok.chat_template = TEMPLATE
    tok.save_pretrained(path)
    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=len(chars), hidden_size=16, intermediate_size=32,
                      num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=2,
                      max_position_embeddings=256, pad_token_id=len(chars) - 2)
    Qwen2ForCausalLM(cfg).save_pretrained(path)


def tiny_adapter(base: Path, out: Path, seed: int) -> None:
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM

    model = AutoModelForCausalLM.from_pretrained(base)
    peft = get_peft_model(model, LoraConfig(r=4, lora_alpha=8, target_modules=["q_proj", "v_proj"]))
    gen = torch.Generator().manual_seed(seed)
    for n, p in peft.named_parameters():
        if "lora_B" in n:
            p.data = torch.randn(p.shape, generator=gen) * 2
    peft.save_pretrained(out)


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> LocalizedSLM:
    root = tmp_path_factory.mktemp("models")
    tiny_base(root / "qwen")
    for code, seed in (("yo", 1), ("ha", 2)):
        tiny_adapter(root / "qwen", root / f"lora-{code}" / "adapter", seed)
    return LocalizedSLM.from_dir(root)


MESSAGES = [{"role": "user", "content": "Sannu, ina so in tambaya game da zazzabi."}]


def test_adapters_are_found_by_locale(host: LocalizedSLM, tmp_path: Path) -> None:
    assert set(host.adapters) == {"lora-yo", "lora-ha"}
    assert adapter_dir("ig", tmp_path) is None and adapter_dir("en", tmp_path) is None
    assert host.available()


def test_each_locale_uses_its_own_adapter(host: LocalizedSLM) -> None:
    out = {c: host.for_locale(c).chat(MESSAGES, max_tokens=12) for c in ("en", "yo", "ha", "ig")}
    assert out["en"] == out["ig"]
    assert len({out["en"], out["yo"], out["ha"]}) == 3
    assert host.for_locale("yo").adapter == "lora-yo" and host.for_locale("ig").adapter is None
    assert host.for_locale("yo").count_tokens("abc") == 3


def test_missing_base_model_is_reported(tmp_path: Path) -> None:
    assert slm_factory(Settings(llm=LLMSettings(edge_model_path=tmp_path / "no.gguf")),
                       tmp_path) is None
    with pytest.raises(FileNotFoundError):
        LocalizedSLM(tmp_path / "none").generate(MESSAGES, max_tokens=2, adapter=None)


@pytest.mark.skipif(not GGUF.is_file(), reason="Qwen2.5-0.5B GGUF not downloaded")
def test_llama_cpp_host_runs_the_real_gguf_model() -> None:
    from edge.slm import LlamaCppSLM

    slm = LlamaCppSLM(GGUF, n_ctx=512, n_threads=2)
    reply = slm.chat([{"role": "user", "content": "Reply with the single word: ready"}],
                     max_tokens=8)
    assert isinstance(reply, str) and reply
    assert slm.chat([{"role": "user", "content": "Reply with the single word: ready"}],
                    max_tokens=8) == reply
    assert slm.count_tokens("Hello, how are you today?") > 3
