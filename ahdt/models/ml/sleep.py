"""Sleep-EDF sleep staging (VM job): a 1D-CNN on 30-s Fpz-Cz epochs plus a continual step.

    python -m ahdt.models.ml.sleep

Data: the 153 sleep-cassette recordings of the Sleep-EDF Database Expanded 1.0.0
(`SC4ssNE0-PSG.edf`, ss = subject, N = night; PhysioNet page). The R&K hypnogram stages
map to AASM classes: W, 1 -> N1, 2 -> N2, 3 and 4 -> N3, R -> REM; `?` and movement epochs
are left out. Each night keeps its epochs from 30 min before the first to 30 min after
the last sleep epoch and is z-scored with its own mean and standard deviation.

Subjects split 60/20/20 into train, calibration and test by a hash of the subject number,
so both nights of a subject are in one part. Age and sex per subject and night come from
the dataset's `SC-subjects.xls` (column `sex (F=1)`: 1 female, 2 male).

Continual step (Avalanche Replay, when avalanche is installed): the trained model sees
two experiences, a sample of the training epochs and then the first night of each test
subject that has two nights. The report gives the macro-F1 on their second night and on
the calibration subjects before and after the step.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score
from torch import nn

from ahdt.models.ml import conformal, torchjob
from ahdt.models.ml.artifacts import Result, model_dir, write_result
from ahdt.models.ml.common import age_band, split_of
from ahdt.models.ml.slices import bands
from ahdt.models.ml.torchjob import GlobalPool, block, log, smoke
from evaluation.models.ahdt.fairness import multiclass_ece, slice_report

MODEL_ID = "ahdt.nervous.eeg_analysis_and_sleep_staging"
VERSION = "1.0.0"
CHANNEL = "EEG Fpz-Cz"
FS = 100
EPOCH_S = 30
SAMPLES = FS * EPOCH_S
STAGES = ("W", "N1", "N2", "N3", "REM")
RK_TO_AASM = {"Sleep stage W": 0, "Sleep stage 1": 1, "Sleep stage 2": 2, "Sleep stage 3": 3,
              "Sleep stage 4": 3, "Sleep stage R": 4}
WAKE_MARGIN = 60
LEVEL = 0.9
REPLAY_MEMORY = 2000
REPLAY_SAMPLE = 20000
NOTE = ("Slices use the Sleep-EDF age and sex of healthy Caucasian adults aged 25 to 101, so "
        "the tables do not show equity for the ATRA population.")


def data_root() -> Path:
    return Path(os.environ.get("ATRA", "/home/ubuntu/atra")) / "data" / "sleep-edfx"


def night(psg: Path, hypnogram: Path) -> tuple[NDArray[np.float16], NDArray[np.int8]]:
    import mne

    raw = mne.io.read_raw_edf(psg, include=[CHANNEL], preload=True, verbose="error")
    if raw.info["sfreq"] != FS:
        raise ValueError(f"{psg.name}: {raw.info['sfreq']} Hz, expected {FS}")
    raw.set_annotations(mne.read_annotations(hypnogram), emit_warning=False)
    present = {k: v for k, v in RK_TO_AASM.items() if k in set(raw.annotations.description)}
    events, _ = mne.events_from_annotations(raw, event_id=present,
                                              chunk_duration=float(EPOCH_S), verbose="error")
    signal = raw.get_data(picks=[CHANNEL])[0] * 1e6
    starts = events[:, 0] - raw.first_samp
    y = events[:, 2].astype(np.int8)
    ok = starts + SAMPLES <= len(signal)
    starts, y = starts[ok], y[ok]
    sleep = np.flatnonzero(y > 0)
    if sleep.size:
        keep = slice(max(0, sleep[0] - WAKE_MARGIN), sleep[-1] + WAKE_MARGIN + 1)
        starts, y = starts[keep], y[keep]
    x = np.stack([signal[s:s + SAMPLES] for s in starts])
    x = np.clip((x - x.mean()) / (x.std() + 1e-6), -20, 20)
    return x.astype(np.float16), y


def recordings(root: Path) -> list[dict[str, Any]]:
    import pandas as pd

    sheet = pd.read_excel(root / "SC-subjects.xls")
    demo = {(int(r.subject), int(r.night)): (int(r.age), int(r["sex (F=1)"]))
            for _, r in sheet.iterrows()}
    out = []
    for psg in sorted((root / "sleep-cassette").glob("SC4*-PSG.edf")):
        stem = psg.name[:6]
        hyp = sorted(psg.parent.glob(f"{stem}*-Hypnogram.edf"))
        if len(hyp) != 1:
            raise ValueError(f"{psg.name}: {len(hyp)} hypnograms")
        subject, n = int(stem[3:5]), int(stem[5])
        age, sex = demo[(subject, n)]
        out.append({"id": stem, "psg": psg, "hypnogram": hyp[0], "subject": subject,
                    "night": n, "sex": {1: "female", 2: "male"}.get(sex, "unknown"),
                    "age_band": age_band(float(age), bands()),
                    "split": split_of(f"sleep-edfx:{subject}")})
    return out


def cached(rec: dict[str, Any], cache: Path) -> tuple[NDArray[np.float16], NDArray[np.int8]]:
    path = cache / f"{rec['id']}.npz"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        x, y = night(rec["psg"], rec["hypnogram"])
        tmp = cache / f"{rec['id']}.tmp.npz"
        np.savez(tmp, x=x, y=y)
        tmp.replace(path)
        log(f"sleep: {rec['id']} {len(y)} epochs")
    d = np.load(path)
    return d["x"], d["y"]


class SleepNet(nn.Module):
    """1D-CNN on one 30-s epoch at 100 Hz, input [N, 3000], logits [N, 5]."""

    def __init__(self, k: int = len(STAGES)) -> None:
        super().__init__()
        self.conv = nn.Sequential(block(1, 32, 49, 4), nn.MaxPool1d(4), block(32, 64, 7, 1),
                                  nn.MaxPool1d(2), block(64, 64, 7, 1), nn.MaxPool1d(2),
                                  block(64, 64, 5, 1), GlobalPool())
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(128, k))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.conv(x.unsqueeze(1)))


def gather(recs: list[dict[str, Any]], cache: Path) -> dict[str, Any]:
    parts = [(r, *cached(r, cache)) for r in recs]
    return {"x": np.concatenate([p[1] for p in parts]),
            "y": np.concatenate([p[2] for p in parts]).astype(np.int64),
            "sex": np.concatenate([[p[0]["sex"]] * len(p[2]) for p in parts]),
            "age_band": np.concatenate([[p[0]["age_band"]] * len(p[2]) for p in parts])}


class _Epochs(torch.utils.data.Dataset[tuple[torch.Tensor, int, int]]):
    """(epoch, stage, task 0) rows for Avalanche."""

    def __init__(self, x: NDArray[np.float16], y: NDArray[np.int64]) -> None:
        self.x, self.y = x, y
        self.targets = [int(v) for v in y]

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int, int]:
        return torch.from_numpy(self.x[i].astype(np.float32)), int(self.y[i]), 0


def continual(model: nn.Module, train: dict[str, Any], adapt: dict[str, Any],
              epochs: int) -> nn.Module:
    from avalanche.benchmarks.scenarios import benchmark_from_datasets
    from avalanche.benchmarks.utils import as_classification_dataset
    from avalanche.training import Replay
    from avalanche.training.plugins import EvaluationPlugin

    rng = np.random.default_rng(0)
    pick = np.sort(rng.choice(len(train["y"]), min(REPLAY_SAMPLE, len(train["y"])),
                              replace=False))
    streams = [as_classification_dataset(_Epochs(train["x"][pick], train["y"][pick])),
               as_classification_dataset(_Epochs(adapt["x"], adapt["y"]))]
    bench = benchmark_from_datasets(train=streams)
    adapted = copy.deepcopy(model)
    strategy = Replay(model=adapted, optimizer=torch.optim.Adam(adapted.parameters(), lr=1e-4),
                      criterion=nn.CrossEntropyLoss(), mem_size=REPLAY_MEMORY,
                      train_mb_size=128, train_epochs=epochs, eval_mb_size=512, device="cpu",
                      evaluator=EvaluationPlugin(loggers=[]))
    for exp in bench.train_stream:
        strategy.train(exp)
        log(f"sleep: continual experience {exp.current_experience} done")
    return adapted


def _f1(model: nn.Module, d: dict[str, Any]) -> float:
    return torchjob.macro_f1(d["y"], torchjob.predict_proba(model, [d["x"]], 512), range(5))


def train(out: Path) -> Result:
    torchjob.setup(0)
    recs = recordings(data_root())
    epochs, cl_epochs = 15, 2
    if smoke():
        two = [s for s in {r["subject"] for r in recs if r["split"] == "test"}
               if sum(o["subject"] == s for o in recs) == 2][:1]
        recs = ([r for r in recs if r["split"] == "train"][:2]
                + [r for r in recs if r["split"] == "cal"][:1]
                + [r for r in recs if r["subject"] in two])
        epochs, cl_epochs = 1, 1
    cache = out / "ckpt" / "nights"
    parts = {s: [r for r in recs if r["split"] == s] for s in ("train", "cal", "test")}
    tr, cal, te = (gather(parts[s], cache) for s in ("train", "cal", "test"))
    log(f"sleep: epochs train {len(tr['y'])}, calibration {len(cal['y'])}, test {len(te['y'])}")
    model = SleepNet()
    cfg = torchjob.Fit(epochs=epochs, batch=128, lr=1e-3, patience=3)
    torchjob.fit(model, [tr["x"]], tr["y"], [cal["x"]], cal["y"], cfg, out / "ckpt" / "fit.pt",
                 weights=torchjob.class_weights(tr["y"], 5))
    p_cal = torchjob.predict_proba(model, [cal["x"]], 512)
    p_test = torchjob.predict_proba(model, [te["x"]], 512)
    q = conformal.classification_threshold(cal["y"], p_cal, LEVEL)
    sets = conformal.prediction_sets(p_test, q)
    covered = conformal.set_covers(sets, te["y"])
    pred = p_test.argmax(axis=1)
    metrics = {"macro_f1": float(f1_score(te["y"], pred, labels=range(5), average="macro",
                                          zero_division=0)),
               "accuracy": float(accuracy_score(te["y"], pred)),
               "cohen_kappa": float(cohen_kappa_score(te["y"], pred)),
               "ece": multiclass_ece(te["y"], p_test), "coverage_90": float(covered.mean()),
               "mean_set_size": float(sets.sum(axis=1).mean())}
    for k, s in enumerate(STAGES):
        metrics[f"f1_{s}"] = float(f1_score(te["y"] == k, pred == k, zero_division=0))
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    notes = ["Stages: R&K 3 and 4 merged into N3; 30 min of wake kept on each side of sleep.",
             f"Subjects: train {len({r['subject'] for r in parts['train']})}, calibration "
             f"{len({r['subject'] for r in parts['cal']})}, test "
             f"{len({r['subject'] for r in parts['test']})}."]
    two_nights = [r["subject"] for r in parts["test"] if r["night"] == 2
                  and any(o["subject"] == r["subject"] and o["night"] == 1
                          for o in parts["test"])]
    try:
        import avalanche  # noqa: F401
    except ImportError:
        notes.append("Continual step not run: avalanche is not installed.")
    else:
        if two_nights:
            first = gather([r for r in parts["test"] if r["subject"] in two_nights
                            and r["night"] == 1], cache)
            second = gather([r for r in parts["test"] if r["subject"] in two_nights
                             and r["night"] == 2], cache)
            adapted = continual(model, tr, first, cl_epochs)
            torch.save(adapted.state_dict(), out / "continual.pt")
            metrics |= {"continual_night2_macro_f1_before": _f1(model, second),
                        "continual_night2_macro_f1_after": _f1(adapted, second),
                        "continual_cal_macro_f1_before": _f1(model, cal),
                        "continual_cal_macro_f1_after": _f1(adapted, cal)}
            notes.append(f"Continual step: Avalanche Replay (memory {REPLAY_MEMORY}) on the "
                         f"first night of {len(two_nights)} test subjects; continual.pt.")
    report = slice_report(MODEL_ID, "multiclass", te["y"], p_test,
                          {"sex": te["sex"], "age_band": te["age_band"]}, covered=covered)
    report.note = NOTE
    torchjob.write_json(out / "model.json", {
        "stages": list(STAGES), "channel": CHANNEL, "fs": FS, "epoch_s": EPOCH_S,
        "normalisation": "z-score per night", "conformal_threshold": q, "level": LEVEL,
        "history": cfg.history})
    result = Result(MODEL_ID, VERSION, "sleep-edfx 1.0.0 sleep cassette (test subjects)",
                    "macro_f1", metrics["macro_f1"], metrics, report.to_dict(),
                    split={"train": len(tr["y"]), "cal": len(cal["y"]), "test": len(te["y"]),
                           "unit": "subject"}, notes=notes)
    write_result(result, out, fairness_md=report.markdown())
    return result


def main() -> int:
    atra = Path(os.environ.get("ATRA", "/home/ubuntu/atra"))
    r = train(model_dir(MODEL_ID, atra / ("out-smoke" if smoke() else "out")))
    log(f"{r.model_id}: {r.metric} = {r.value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
