"""Install and register the trained language artifacts (LoRA adapters and the Igbo voice).

The VM jobs of `evaluation/language/` write `lora-<code>/` (PEFT `adapter/`, `metrics.json`) and
`mms-tts-ibo-ft/` (`model/`, `metrics.json`). `register` checks the recorded file hashes, copies
the files to the model folder read by `slm.py` and `tts.py`, registers one entry per artifact in
the model registry and writes a model card.

    python -m ahdt.models.language register --src DIR [--dest DIR]
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ahdt.models.language.locales import LOCALES
from ahdt.models.language.slm import MODELS_DIR
from atra import contracts as c
from atra.backends.base import ModelRegistryBackend
from atra.config import ROOT

CARDS_DIR = ROOT / "docs" / "governance" / "model_cards"
LORA_SOURCE = ("Hu EJ, Shen Y, Wallis P, et al. LoRA: low-rank adaptation of large language "
               "models. ICLR 2022; PEFT (Mangrulkar S et al., Hugging Face); base model "
               "Qwen2.5-0.5B-Instruct (Qwen Team, Apache-2.0)")
VITS_SOURCE = ("Kim J, Kong J, Son J. Conditional variational autoencoder with adversarial "
               "learning for end-to-end text-to-speech. ICML 2021; Pratap V et al. Scaling "
               "speech technology to 1,000+ languages. JMLR 2024 (MMS); recipe by Lacombe Y "
               "(finetune-hf-vits, MIT)")
LICENCE_NOTE = ("The base voice facebook/mms-tts-yor and the NLLB-200 translations used for "
                "the training text are CC BY-NC 4.0: research use only, no commercial use.")


@dataclass
class Status:
    model_id: str
    state: str
    detail: str = ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def model_id(code: str) -> str:
    return f"apdt.language.lora_{code}"


VOICE_ID = "apdt.language.tts_igbo"


def entry_for_adapter(code: str, m: Mapping[str, Any]) -> c.ModelRegistryEntry:
    loc = LOCALES[code]
    v = m["validation"]
    return c.ModelRegistryEntry(
        model_id=model_id(code), version=str(m.get("version", "1.0.0")), twin="apdt",
        family=c.ModelFamily.SLM, tier=c.Tier.T1, anatomy=None,
        inputs=[c.ModelInput.model_validate({"name": "messages", "unit": "text",
                                             "from": "converse"})],
        outputs=[c.ModelIO(name="reply", unit="text")],
        validity={"language": code, "base_model": m.get("base_model")},
        validation=c.Validation(**v),
        intended_use=f"{loc.name} health dialogue style for the local small model (research)",
        source=LORA_SOURCE)


def entry_for_voice(m: Mapping[str, Any]) -> c.ModelRegistryEntry:
    return c.ModelRegistryEntry(
        model_id=VOICE_ID, version=str(m.get("version", "1.0.0")), twin="apdt",
        family=c.ModelFamily.ML, tier=c.Tier.T1, anatomy=None,
        inputs=[c.ModelInput.model_validate({"name": "text", "unit": "text", "from": "converse"})],
        outputs=[c.ModelIO(name="speech", unit="audio/wav")],
        validity={"language": "ig", "base_model": m.get("base"), "data": m.get("data")},
        validation=c.Validation(**m["validation"]),
        intended_use="Igbo text-to-speech voice for phone and kiosk channels (research)",
        source=VITS_SOURCE)


def check_files(directory: Path, metrics: Mapping[str, Any]) -> list[str]:
    bad = []
    for rel, digest in (metrics.get("files") or {}).items():
        path = directory / rel
        if not path.is_file() or sha256(path) != digest:
            bad.append(rel)
    return bad


def card(model: str, entry: c.ModelRegistryEntry, metrics: Mapping[str, Any]) -> str:
    v = entry.validation
    lines = [f"# {model}", "", "| Field | Value |", "|---|---|", f"| Version | {entry.version} |",
             f"| Twin | {entry.twin} |", f"| Family | {entry.family.value} |",
             f"| Fidelity tier | {entry.tier.value} |", f"| Intended use | {entry.intended_use} |",
             "| Regulatory status | research |", f"| Source | {entry.source} |",
             f"| Licence | {LICENCE_NOTE} |"]
    if v:
        lines.append(f"| Validation | {v.dataset}: {v.metric} = {v.value:.4g} ({v.date}) |")
    lines += ["", "## Limits", "",
              "- Medical-dialogue quality in this language is not verified by a clinician or a "
              "native-speaking rater.",
              "- The training text is machine-translated or templated; the numbers measure "
              "agreement with those references and with human translations of news text.",
              "", "## Training", ""]
    for key in ("steps", "batch", "rank", "train_examples", "samples", "seconds", "dev_loss",
                "train_loss_first10", "train_loss_last10", "mel_first_fifth", "mel_last_fifth"):
        if key in metrics:
            val = metrics[key]
            lines.append(f"- {key}: {val:.4g}" if isinstance(val, float) else f"- {key}: {val}")
    return "\n".join(lines) + "\n"


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("work", "state.pt", "*.tmp"))


def install(src: Path, dest: Path, cards_dir: Path | None
            ) -> tuple[list[Status], list[tuple[c.ModelRegistryEntry, dict[str, float]]]]:
    """Check, copy and document every finished artifact; return the entries to register."""
    statuses: list[Status] = []
    entries: list[tuple[c.ModelRegistryEntry, dict[str, float]]] = []
    items: list[tuple[str, str, Path, str]] = [
        (model_id(code), f"lora-{code}", src / f"lora-{code}", code)
        for code in ("yo", "ha", "ig", "pcm")]
    items.append((VOICE_ID, "mms-tts-ibo-ft", src / "mms-tts-ibo-ft", "voice"))
    for mid, folder, directory, code in items:
        path = directory / "metrics.json"
        if not path.is_file():
            statuses.append(Status(mid, "not trained"))
            continue
        metrics = json.loads(path.read_text(encoding="utf-8"))
        bad = check_files(directory, metrics)
        if bad:
            statuses.append(Status(mid, "artifact mismatch", ", ".join(bad)))
            continue
        metrics.setdefault("validation", _validation(code, src))
        entry = entry_for_voice(metrics) if code == "voice" else entry_for_adapter(code, metrics)
        target = dest / folder
        if code == "voice":
            _copy_tree(directory / "model", target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            _copy_tree(directory / "adapter", target / "adapter")
        if cards_dir is not None:
            cards_dir.mkdir(parents=True, exist_ok=True)
            (cards_dir / f"{mid}.md").write_text(card(mid, entry, metrics), encoding="utf-8")
        v = entry.validation
        statuses.append(Status(mid, "registered", f"{v.metric}={v.value:.4g}" if v else ""))
        entries.append((entry, _flat(metrics)))
    return statuses, entries


async def register(backend: ModelRegistryBackend, *, src: Path, dest: Path = MODELS_DIR,
                   cards_dir: Path | None = CARDS_DIR) -> list[Status]:
    statuses, entries = install(src, dest, cards_dir)
    for entry, metrics in entries:
        await backend.register(entry, metrics=metrics)
    return statuses


def _flat(m: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in m.items() if isinstance(v, int | float)}


def _validation(code: str, src: Path) -> dict[str, Any]:
    """The headline number from the evaluation report: chrF of the held-out translation test
    for an adapter, round-trip WER for the voice."""
    today = datetime.now(UTC).date().isoformat()
    ev = src / "eval"
    if code == "voice":
        rt = json.loads((ev / "roundtrip.json").read_text(encoding="utf-8"))["ig"]
        return {"dataset": "NLLB-translated Igbo sentences, TTS then STT round trip",
                "metric": "wer", "value": float(rt["wer"]), "date": today}
    data = json.loads((ev / f"{code}.json").read_text(encoding="utf-8"))["translation"]
    return {"dataset": f"{data['reference_source']} (n={data['n']}), English to the language",
            "metric": "chrf", "value": float(data["chrf_adapter"]), "date": today}
