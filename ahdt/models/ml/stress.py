"""WESAD stress model (VM job): 60-s windows of chest ECG, EDA and skin temperature.

    python -m ahdt.models.ml.stress

Reads the `SX.npz` files of `vm/wesad_compact.py` (RespiBAN chest signals at 700 Hz in mV,
uS and degC, protocol labels 1 to 4). The task follows the WESAD readme labels: stress (2)
against baseline (1) and amusement (3); meditation (4) is left out. Windows are 60 s with a
30-s step inside one uninterrupted stretch of one condition.

Validation is leave-one-subject-out over the 15 subjects: the headline AUROC pools the
out-of-fold probabilities. The deployed model is `tabular.train` on all windows with its
person-level split (conformal threshold and operating point from its calibration subjects).
Age and sex come from each subject's `SX_readme.txt`.
"""

from __future__ import annotations

import os
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import brier_score_loss, roc_auc_score

from ahdt.models.ml import tabular
from ahdt.models.ml.artifacts import model_dir, write_result
from ahdt.models.ml.common import age_band
from ahdt.models.ml.slices import bands
from ahdt.models.ml.torchjob import log, smoke
from evaluation.models.ahdt.fairness import ece, slice_report

MODEL_ID = "ahdt.behavioural_cognitive.affect_and_stress"
VERSION = "1.0.0"
FS = 700
EDA_FS = 4
WINDOW_S, STEP_S = 60, 30
LABELS = {1: 0, 3: 0, 2: 1}
FEATURES = ("hr_mean", "hrv_rmssd", "hrv_sdnn", "hrv_pnn50", "eda_mean", "eda_std",
            "eda_slope", "scr_count", "skin_temp", "skin_temp_slope")
NOTE = ("Slices use the WESAD readme age and sex of 15 young adults (3 female), so the "
        "tables show the pipeline, not equity for the ATRA population.")


def wesad_root() -> Path:
    return Path(os.environ.get("ATRA", "/home/ubuntu/atra")) / "data" / "wesad" / "WESAD"


def readme(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    age = re.search(r"^Age:\s*(\d+)", text, re.M)
    sex = re.search(r"^Gender:\s*(\w+)", text, re.M)
    return {"sex": sex.group(1).lower() if sex else "unknown",
            "age_band": age_band(float(age.group(1)), bands()) if age else "unknown"}


def _runs(label: NDArray[Any], index: NDArray[Any]) -> list[tuple[int, int]]:
    """[start, end) of each stretch with one label and consecutive original samples."""
    cut = np.flatnonzero((np.diff(label) != 0) | (np.diff(index) != 1)) + 1
    edges = [0, *cut.tolist(), len(label)]
    return list(pairwise(edges))


def _slope(y: NDArray[Any], fs: float) -> float:
    t = np.arange(len(y)) / fs
    return float(np.polyfit(t, y, 1)[0]) if len(y) > 1 else 0.0


def windows(npz: Path) -> list[dict[str, Any]]:
    import neurokit2 as nk

    d = np.load(npz)
    label, index = d["label"], d["index"]
    rows = []
    for start, end in _runs(label, index):
        cond = int(label[start])
        if cond not in LABELS or end - start < WINDOW_S * FS:
            continue
        ecg = nk.ecg_clean(d["ecg"][start:end].astype(float), sampling_rate=FS)
        _, info = nk.ecg_peaks(ecg, sampling_rate=FS)
        peaks = np.asarray(info["ECG_R_Peaks"], dtype=np.int64)
        block = FS // EDA_FS
        n4 = (end - start) // block
        eda = d["eda"][start:start + n4 * block].astype(float).reshape(n4, block).mean(axis=1)
        phasic = nk.eda_phasic(eda, sampling_rate=EDA_FS, method="highpass")["EDA_Phasic"]
        _, scr = nk.eda_peaks(phasic.to_numpy(), sampling_rate=EDA_FS)
        scr_peaks = np.asarray(scr["SCR_Peaks"], dtype=np.int64)
        temp = d["temp"][start:end].astype(float)
        for w0 in range(0, end - start - WINDOW_S * FS + 1, STEP_S * FS):
            w1 = w0 + WINDOW_S * FS
            p = peaks[(peaks >= w0) & (peaks < w1)]
            rr = np.diff(p) / FS * 1000.0
            rr = rr[(rr > 300) & (rr < 2000)]
            if len(rr) < 20:
                continue
            e0, e1 = w0 // block, w1 // block
            e = eda[e0:e1]
            drr = np.diff(rr)
            rows.append({
                "hr_mean": float(60000.0 / rr.mean()),
                "hrv_rmssd": float(np.sqrt(np.mean(drr ** 2))),
                "hrv_sdnn": float(rr.std(ddof=1)),
                "hrv_pnn50": float(np.mean(np.abs(drr) > 50) * 100),
                "eda_mean": float(e.mean()), "eda_std": float(e.std()),
                "eda_slope": _slope(e, EDA_FS),
                "scr_count": float(((scr_peaks >= e0) & (scr_peaks < e1)).sum()),
                "skin_temp": float(temp[w0:w1].mean()),
                "skin_temp_slope": _slope(temp[w0:w1:FS], 1.0),
                "label": LABELS[cond], "condition": cond})
    return rows


def features(root: Path, cache: Path) -> pd.DataFrame:
    """Windows of every subject; one cached parquet per subject, so the job resumes."""
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    subjects = sorted(root.glob("S*/S*.npz"), key=lambda p: int(p.stem[1:]))
    if smoke():
        # One subject in each of the train, calibration and test parts of the person split.
        subjects = [p for p in subjects if p.stem in ("S2", "S3", "S15")]
    for npz in subjects:
        sid = npz.stem
        part = cache / f"{sid}.parquet"
        if not part.exists():
            df = pd.DataFrame(windows(npz))
            df["subject"] = sid
            for k, v in readme(npz.with_name(f"{sid}_readme.txt")).items():
                df[k] = v
            df.to_parquet(part.with_suffix(".tmp"))
            part.with_suffix(".tmp").replace(part)
            log(f"wesad {sid}: {len(df)} windows, stress share {df['label'].mean():.2f}")
        frames.append(pd.read_parquet(part))
    return pd.concat(frames, ignore_index=True)


def loso(df: pd.DataFrame) -> NDArray[np.float64]:
    """Out-of-fold stress probability of every window, one fold per subject."""
    import lightgbm as lgb

    p = np.zeros(len(df))
    x = df[list(FEATURES)].to_numpy(dtype=np.float32)
    y = df["label"].to_numpy(dtype=int)
    for sid in sorted(df["subject"].unique()):
        held = (df["subject"] == sid).to_numpy()
        model = lgb.LGBMClassifier(**tabular.DEFAULT_PARAMS)
        model.fit(x[~held], y[~held])
        p[held] = np.asarray(model.predict_proba(x[held]))[:, 1]
    return p


def train(out: Path) -> Any:
    df = features(wesad_root(), out / "ckpt" / "windows")
    log(f"wesad: {len(df)} windows of {df['subject'].nunique()} subjects")
    p = loso(df)
    y = df["label"].to_numpy(dtype=int)
    per_subject = [float(roc_auc_score(y[m], p[m])) for s in sorted(df["subject"].unique())
                   if len(set(y[m := (df["subject"] == s).to_numpy()])) == 2]
    task = tabular.TabularTask(MODEL_ID, VERSION, "wesad", FEATURES, group="subject",
                               notes=("Stress (protocol label 2) against baseline (1) and "
                                      "amusement (3); meditation (4) left out.",))
    result = tabular.train(task, df, out)
    holdout = {f"holdout_{k}": v for k, v in result.metrics.items()}
    result.metrics = {"loso_auroc": float(roc_auc_score(y, p)),
                      "loso_auroc_subject_mean": float(np.mean(per_subject)),
                      "loso_auroc_subject_min": float(np.min(per_subject)),
                      "loso_brier": float(brier_score_loss(y, p)), "loso_ece": ece(y, p),
                      "windows": float(len(df)), "stress_share": float(y.mean()), **holdout}
    result.metric, result.value = "loso_auroc", result.metrics["loso_auroc"]
    result.dataset = "wesad (leave-one-subject-out)"
    report = slice_report(MODEL_ID, "binary", y, p,
                          {"sex": df["sex"].to_numpy(), "age_band": df["age_band"].to_numpy()})
    report.note = NOTE
    result.fairness = report.to_dict()
    result.split = {**result.split, "subjects": int(df["subject"].nunique()),
                    "validation": "leave-one-subject-out (headline); person split (holdout_*)"}
    result.notes = [*result.notes, f"{WINDOW_S}-s windows, {STEP_S}-s step, chest RespiBAN at "
                    f"{FS} Hz; R-peaks with NeuroKit2, EDA at {EDA_FS} Hz."]
    write_result(result, out, fairness_md=report.markdown())
    return result


def main() -> int:
    atra = Path(os.environ.get("ATRA", "/home/ubuntu/atra"))
    r = train(model_dir(MODEL_ID, atra / ("out-smoke" if smoke() else "out")))
    log(f"{r.model_id}: {r.metric} = {r.value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
