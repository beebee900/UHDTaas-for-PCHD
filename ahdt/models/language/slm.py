"""The local small model with per-language LoRA adapters (design 04, 4.5.3).

`LocalizedSLM` loads Qwen2.5-0.5B-Instruct once (Hugging Face weights) and the LoRA adapter of
each language beside it (PEFT). `for_locale(code)` returns an `EdgeSLM` bound to that
language's adapter, so the converse path and the edge assistant use the same protocol as
`edge.slm.LlamaCppSLM`. English uses the GGUF model through `LlamaCppSLM` when the file is
present; the adapters need the PEFT host because llama.cpp loads LoRA only in GGUF form.

Layout under `var/models/language/`: `qwen/` (the base model), `lora-<code>/adapter/` (PEFT
files written by the VM training job).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ahdt.models.language.locales import DEFAULT_LOCALE, locale_for
from atra.config import ROOT, Settings
from edge.slm import EdgeSLM, LlamaCppSLM

MODELS_DIR = ROOT / "var" / "models" / "language"
BASE_DIR = MODELS_DIR / "qwen"


def adapter_dir(code: str, root: Path = MODELS_DIR) -> Path | None:
    """The PEFT adapter folder of a locale, or None when it is not installed."""
    loc = locale_for(code)
    if loc.adapter is None:
        return None
    path = root / loc.adapter / "adapter"
    return path if (path / "adapter_config.json").is_file() else None


class _Bound:
    """An `EdgeSLM` for one locale of a `LocalizedSLM`."""

    def __init__(self, host: LocalizedSLM, adapter: str | None) -> None:
        self.host, self.adapter = host, adapter

    def chat(self, messages: Sequence[Mapping[str, str]], *, max_tokens: int) -> str:
        return self.host.generate(messages, max_tokens=max_tokens, adapter=self.adapter)

    def count_tokens(self, text: str) -> int:
        return self.host.count_tokens(text)


class LocalizedSLM:
    def __init__(self, base_dir: Path = BASE_DIR, adapters: Mapping[str, Path] | None = None,
                 *, n_threads: int = 2) -> None:
        self.base_dir = base_dir
        self.adapters = dict(adapters or {})
        self.n_threads = n_threads
        self._model: Any = None
        self._tok: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_dir(cls, root: Path = MODELS_DIR, **kw: Any) -> LocalizedSLM:
        found = {loc: p for loc in ("yo", "ha", "ig", "pcm") if (p := adapter_dir(loc, root))}
        return cls(root / "qwen", {f"lora-{k}": v for k, v in found.items()}, **kw)

    def available(self) -> bool:
        return (self.base_dir / "config.json").is_file()

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available():
            raise FileNotFoundError(f"no base model at {self.base_dir}")
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(self.n_threads)
        self._tok = AutoTokenizer.from_pretrained(str(self.base_dir))
        model = AutoModelForCausalLM.from_pretrained(str(self.base_dir), dtype=torch.float32)
        first = True
        for name, path in self.adapters.items():
            if first:
                model = PeftModel.from_pretrained(model, str(path), adapter_name=name)
                first = False
            else:
                model.load_adapter(str(path), adapter_name=name)
        self._model = model.eval()

    def count_tokens(self, text: str) -> int:
        with self._lock:
            self._load()
            return len(self._tok(text, add_special_tokens=False)["input_ids"])

    def generate(self, messages: Sequence[Mapping[str, str]], *, max_tokens: int,
                 adapter: str | None) -> str:
        import contextlib

        import torch

        with self._lock:
            self._load()
            prompt = self._tok.apply_chat_template(
                [dict(m) for m in messages], tokenize=False, add_generation_prompt=True)
            enc = self._tok(prompt, return_tensors="pt")
            peft_model = hasattr(self._model, "set_adapter")
            if peft_model and adapter in self.adapters:
                self._model.set_adapter(adapter)
                ctx: Any = contextlib.nullcontext()
            elif peft_model:
                ctx = self._model.disable_adapter()
            else:
                ctx = contextlib.nullcontext()
            with ctx, torch.no_grad():
                out = self._model.generate(
                    **enc, max_new_tokens=max_tokens, do_sample=False,
                    pad_token_id=self._tok.pad_token_id)
            new = out[0][enc["input_ids"].shape[1]:]
            return str(self._tok.decode(new, skip_special_tokens=True)).strip()

    def for_locale(self, code: str) -> EdgeSLM:
        loc = locale_for(code)
        name = loc.adapter if loc.adapter in self.adapters else None
        return _Bound(self, name)


def slm_factory(settings: Settings, root: Path = MODELS_DIR) -> Callable[[str], EdgeSLM] | None:
    """A `locale -> EdgeSLM` function for `SlmBackend`, or None when no local model exists.

    English uses the GGUF model when `settings.llm.edge_model_path` exists. Other locales use
    the PEFT host with their adapter.
    """
    host = LocalizedSLM.from_dir(root)
    gguf = settings.llm.edge_model_path
    llama = LlamaCppSLM(gguf) if gguf.is_file() else None
    if not host.available() and llama is None:
        return None

    def pick(code: str) -> EdgeSLM:
        if locale_for(code).code == DEFAULT_LOCALE and llama is not None:
            return llama
        if host.available():
            return host.for_locale(code)
        if llama is not None:
            return llama
        raise FileNotFoundError("no local language model installed")

    return pick
