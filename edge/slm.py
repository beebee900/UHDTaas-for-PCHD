"""The edge small language model (design 04, 4.2.1 tier 2): offline triage text and daily
summaries.

`LlamaCppSLM` runs the GGUF model of `LLMSettings.edge_model_path` (Qwen2.5-0.5B-Instruct,
Q4) through `llama-cpp-python`, greedy and single-threaded per call. `OfflineSLM` is the
deterministic stand-in for tests and for machines without the model: it returns the fact lines
of the prompt joined into one text. Both take the same chat messages, so `EdgeAssistant`
builds the prompts of `edge/prompts.yaml` once for either.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from ahdt.ingest.fields import FieldIndex, field_index
from atra.contracts import Code
from edge.alerts import Alert
from edge.preprocess import FeatureWindow

PROMPTS = Path(__file__).with_name("prompts.yaml")
FACT = "- "

type Message = Mapping[str, str]


@lru_cache(maxsize=1)
def prompts() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = yaml.safe_load(PROMPTS.read_text())
    return loaded


class EdgeSLM(Protocol):
    def chat(self, messages: Sequence[Message], *, max_tokens: int) -> str: ...


class OfflineSLM:
    """Deterministic: the fact lines of the last user message, joined."""

    def chat(self, messages: Sequence[Message], *, max_tokens: int) -> str:
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        facts = [line[len(FACT):].strip() for line in user.splitlines() if line.startswith(FACT)]
        return " ".join(f.rstrip(".") + "." for f in facts)


class LlamaCppSLM:
    def __init__(self, model_path: Path, *, n_ctx: int = 2048, n_threads: int = 2,
                 seed: int = 0) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"no edge model at {model_path}")
        self.model_path = model_path
        self.n_ctx, self.n_threads, self.seed = n_ctx, n_threads, seed
        self._llm: Any = None
        self._lock = threading.Lock()

    def _model(self) -> Any:
        if self._llm is None:
            from llama_cpp import Llama

            self._llm = Llama(model_path=str(self.model_path), n_ctx=self.n_ctx,
                              n_threads=self.n_threads, seed=self.seed, verbose=False)
        return self._llm

    def chat(self, messages: Sequence[Message], *, max_tokens: int) -> str:
        with self._lock:
            out = self._model().create_chat_completion(
                messages=[dict(m) for m in messages], temperature=0.0, max_tokens=max_tokens,
                seed=self.seed)
        return str(out["choices"][0]["message"]["content"]).strip()

    def count_tokens(self, text: str) -> int:
        with self._lock:
            return len(self._model().tokenize(text.encode("utf-8"), add_bos=False))


def _fmt(value: float) -> str:
    return f"{value:.4g}"


class EdgeAssistant:
    def __init__(self, slm: EdgeSLM, *, index: FieldIndex | None = None) -> None:
        self.slm = slm
        self.index = index or field_index()

    def _name(self, code: Mapping[str, Any]) -> str:
        ref = self.index.resolve(Code.model_validate(dict(code)))
        return ref.field.name if ref else str(code["code"])

    def _ask(self, task: str, facts: Iterable[str], **fields: str) -> str:
        p = prompts()[task]
        block = "\n".join(FACT + f for f in facts)
        messages = [{"role": "system", "content": p["system"]},
                    {"role": "user", "content": p["user"].format(facts=block, **fields)}]
        return self.slm.chat(messages, max_tokens=int(p["max_tokens"]))

    def summary_facts(self, windows: Iterable[FeatureWindow],
                      alerts: Iterable[Alert]) -> list[str]:
        by_field: dict[tuple[str, str], list[FeatureWindow]] = {}
        for w in windows:
            by_field.setdefault((self._name(w.code), w.unit), []).append(w)
        facts = []
        for (name, unit), ws in sorted(by_field.items()):
            n = sum(w.n for w in ws)
            mean = sum(w.mean * w.n for w in ws) / n
            facts.append(f"{name}: mean {_fmt(mean)} {unit}, lowest {_fmt(min(w.min for w in ws))}"
                         f", highest {_fmt(max(w.max for w in ws))}, {n} readings")
        facts += [a.text for a in alerts]
        return facts or ["no readings"]

    def daily_summary(self, hdt_id: str, day: date, windows: Iterable[FeatureWindow],
                      alerts: Iterable[Alert] = ()) -> str:
        return self._ask("summary", self.summary_facts(windows, alerts), hdt_id=hdt_id,
                         day=day.isoformat())

    def triage(self, alert: Alert) -> str:
        return self._ask("triage", [alert.text], hdt_id=alert.hdt_id)
