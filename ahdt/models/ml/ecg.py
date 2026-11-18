"""ECG training jobs on the VM: the MIT-BIH beat classifier and the PTB-XL rhythm ensemble.

    python -m ahdt.models.ml.ecg mitdb     AAMI beat classes, inter-patient split
    python -m ahdt.models.ml.ecg ptbxl     sinus / af / other rhythm, 5-member ensemble + ONNX

Both work on lead II at 250 Hz, band-passed 0.5 to 40 Hz like the edge pre-processing.

MIT-BIH (Moody and Mark 2001): beats map to the AAMI classes as in Guo et al. 2019
(arXiv 1810.04121, Table 1): N = N L R e j, S = A a J S, V = V E, F = F, Q = / f Q. Training
records are DS1 and test records DS2 of the same paper (it names the test set DST1). Paced
records 102, 104, 107 and 217 are in neither. A few DS1 records chosen by hash hold out
the model selection and the conformal calibration. Age and sex come from the first comment
line of each record header.

PTB-XL 1.0.3 (Wagner et al. 2020): the rhythm codes are the `rhythm == 1` rows of the
dataset's `scp_statements.csv`. A record is `af` when it has AFIB, else `other` when it has
any rhythm code outside the sinus codes SR, STACH, SARRH and SBRAD, else `sinus`; records
without a rhythm code are left out. Folds 1 to 8 train, fold 9 validates and calibrates,
fold 10 tests (the split the PhysioNet page recommends). Lead II is read by its signal name
from the 500 Hz records. Sex 0 is male; ages above 89 are stored as 300 (PhysioNet page).
"""

from __future__ import annotations

import argparse
import ast
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from scipy.signal import butter, resample_poly, sosfiltfilt
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from torch import nn

from ahdt.models.ml import conformal, torchjob
from ahdt.models.ml.artifacts import Result, model_dir, write_result
from ahdt.models.ml.common import (
    age_band,
    operating_point,
    sensitivity_specificity,
    split_of,
)
from ahdt.models.ml.slices import bands
from ahdt.models.ml.torchjob import GlobalPool, Standardize, block, log, smoke
from evaluation.models.ahdt.fairness import ece, multiclass_ece, slice_report

FS = 250
BAND_HZ = (0.5, 40.0)
LEVEL = 0.9
VERSION = "1.0.0"
REAL_DATA_NOTE = ("Slices use the dataset's own age and sex. Rows are beats or recordings of "
                  "few persons, and the cohorts are not African, so these numbers do not show "
                  "equity for the ATRA population.")

BEAT_ID = "ahdt.cardiovascular.arrhythmia_beat_classification"
AAMI = {"N": "NLRej", "S": "AaJS", "V": "VE", "F": "F", "Q": "/fQ"}
BEAT_CLASSES = tuple(AAMI)
SYMBOL_CLASS = {s: i for i, c in enumerate(BEAT_CLASSES) for s in AAMI[c]}
DS1 = (101, 106, 108, 109, 112, 114, 115, 116, 118, 119, 122, 124, 201, 203, 205, 207, 208,
       209, 215, 220, 223, 230)
DS2 = (100, 103, 105, 111, 113, 117, 121, 123, 200, 202, 210, 212, 213, 214, 219, 221, 222,
       228, 231, 232, 233, 234)
MITDB_FS = 360
BEFORE, AFTER = 96, 160
RR_FEATURES = ("pre_rr_s", "post_rr_s", "pre_over_local", "post_over_local", "pre_over_record")
LOCAL_BEATS = 10

RHYTHM_ID = "ahdt.cardiovascular.arrhythmia_detection"
RHYTHM_CLASSES = ("sinus", "af", "other")
SINUS = ("SR", "STACH", "SARRH", "SBRAD")
AF = "AFIB"
SAMPLES = 2500
MEMBERS = 5
EDGE_NAME = "arrhythmia"


def data_root(dataset: str) -> Path:
    return Path(os.environ.get("ATRA", "/home/ubuntu/atra")) / "data" / dataset


def out_root() -> Path:
    atra = Path(os.environ.get("ATRA", "/home/ubuntu/atra"))
    return atra / ("out-smoke" if smoke() else "out")


def bandpass(x: NDArray[Any], fs: float) -> NDArray[np.float32]:
    sos = butter(3, BAND_HZ, btype="bandpass", fs=fs, output="sos")
    out: NDArray[np.float32] = sosfiltfilt(sos, x).astype(np.float32)
    return out


def demographics(comment: str) -> dict[str, str]:
    """`age sex ...` of a MIT-BIH header comment; anything unreadable is `unknown`."""
    parts = comment.split()
    sex = {"M": "male", "F": "female"}.get(parts[1] if len(parts) > 1 else "", "unknown")
    try:
        band = age_band(float(parts[0]), bands())
    except (ValueError, IndexError):
        band = "unknown"
    return {"sex": sex, "age_band": band}


# -- MIT-BIH beats ---------------------------------------------------------------------


def mitdb_record(root: Path, record: int) -> dict[str, Any]:
    import wfdb

    path = str(root / str(record))
    rec = wfdb.rdrecord(path, channel_names=["MLII"])
    if rec.p_signal is None or rec.p_signal.shape[1] != 1:
        raise ValueError(f"mitdb {record}: no MLII signal")
    ann = wfdb.rdann(path, "atr")
    sig = bandpass(resample_poly(rec.p_signal[:, 0], 25, 36), FS)
    keep = [i for i, s in enumerate(ann.symbol) if s in SYMBOL_CLASS]
    pos = np.round(np.asarray(ann.sample)[keep] * FS / MITDB_FS).astype(np.int64)
    y = np.asarray([SYMBOL_CLASS[ann.symbol[i]] for i in keep], dtype=np.int64)
    t = pos / FS
    pre = np.diff(t, prepend=np.nan)
    post = np.diff(t, append=np.nan)
    local = np.asarray([np.nanmean(pre[max(0, i - LOCAL_BEATS + 1):i + 1]) if i else np.nan
                        for i in range(len(pre))])
    record_mean = np.nanmean(pre)
    rr = np.column_stack([pre, post, pre / local, post / local, pre / record_mean])
    ok = (np.isfinite(rr).all(axis=1) & (pos - BEFORE >= 0) & (pos + AFTER <= len(sig)))
    windows = np.stack([sig[p - BEFORE:p + AFTER] for p in pos[ok]]) if ok.any() else \
        np.zeros((0, BEFORE + AFTER), np.float32)
    # Amplitude relative to the record (robust scale) keeps the morphology cue of V beats.
    scale = 1.4826 * np.median(np.abs(sig - np.median(sig))) + 1e-6
    windows = (windows - np.median(windows, axis=1, keepdims=True)) / scale
    return {"x": windows.astype(np.float32), "rr": rr[ok].astype(np.float32), "y": y[ok],
            **demographics(rec.comments[0] if rec.comments else "")}


class BeatNet(nn.Module):
    """1D-CNN on a 1.02-s beat window (record-scaled) plus the five RR-interval features."""

    def __init__(self, k: int = len(BEAT_CLASSES)) -> None:
        super().__init__()
        self.conv = nn.Sequential(block(1, 16, 7, 1), nn.MaxPool1d(2), block(16, 32, 5, 1),
                                  nn.MaxPool1d(2), block(32, 64, 5, 1), nn.MaxPool1d(2),
                                  block(64, 64, 3, 1), GlobalPool())
        self.head = nn.Sequential(nn.Linear(128 + len(RR_FEATURES), 64), nn.ReLU(),
                                  nn.Dropout(0.3), nn.Linear(64, k))

    def forward(self, x: torch.Tensor, rr: torch.Tensor) -> torch.Tensor:
        z = self.conv(x.unsqueeze(1))
        return self.head(torch.cat([z, torch.log(rr.clamp(min=1e-3))], dim=1))


def _stack(recs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"x": np.concatenate([r["x"] for r in recs]),
            "rr": np.concatenate([r["rr"] for r in recs]),
            "y": np.concatenate([r["y"] for r in recs]),
            "sex": np.concatenate([[r["sex"]] * len(r["y"]) for r in recs]),
            "age_band": np.concatenate([[r["age_band"]] * len(r["y"]) for r in recs])}


def train_mitdb(root: Path, out: Path) -> Result:
    torchjob.setup(0)
    train_ids = [r for r in DS1 if split_of(f"mitdb:{r}") != "test"]
    val_ids = [r for r in DS1 if split_of(f"mitdb:{r}") == "test"]
    test_ids = list(DS2)
    epochs = 30
    if smoke():
        train_ids, val_ids, test_ids, epochs = train_ids[:3], val_ids[:1], test_ids[:2], 1
    log(f"mitdb: train {train_ids}, validation {val_ids}, test {len(test_ids)} records")
    tr, va, te = (_stack([mitdb_record(root, r) for r in ids])
                  for ids in (train_ids, val_ids, test_ids))
    log(f"mitdb: beats train {len(tr['y'])}, validation {len(va['y'])}, test {len(te['y'])}")
    model = BeatNet()
    present = tuple(sorted(set(va["y"].tolist()) & {0, 1, 2, 3}))
    cfg = torchjob.Fit(epochs=epochs, batch=256, lr=1e-3, patience=5, score_labels=present)
    torchjob.fit(model, [tr["x"], tr["rr"]], tr["y"], [va["x"], va["rr"]], va["y"], cfg,
                 out / "ckpt" / "fit.pt", weights=torchjob.class_weights(tr["y"], 5, power=1.0))
    p_cal = torchjob.predict_proba(model, [va["x"], va["rr"]])
    p_test = torchjob.predict_proba(model, [te["x"], te["rr"]])
    y_cal, y_test = va["y"], te["y"]
    q = conformal.classification_threshold(y_cal, p_cal, LEVEL)
    sets = conformal.prediction_sets(p_test, q)
    covered = conformal.set_covers(sets, y_test)
    pred = p_test.argmax(axis=1)
    metrics = {"macro_f1_nsvf": float(f1_score(y_test, pred, labels=[0, 1, 2, 3],
                                               average="macro", zero_division=0)),
               "accuracy": float(accuracy_score(y_test, pred)),
               "ece": multiclass_ece(y_test, p_test), "coverage_90": float(covered.mean()),
               "mean_set_size": float(sets.sum(axis=1).mean())}
    for k, c in enumerate(BEAT_CLASSES):
        truth, hit = y_test == k, pred == k
        if truth.any():
            metrics[f"sensitivity_{c}"] = float(hit[truth].mean())
        if hit.any():
            metrics[f"ppv_{c}"] = float(truth[hit].mean())
        metrics[f"n_test_{c}"] = float(truth.sum())
    report = slice_report(BEAT_ID, "multiclass", y_test, p_test,
                          {"sex": te["sex"], "age_band": te["age_band"]}, covered=covered)
    report.note = REAL_DATA_NOTE
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    torchjob.write_json(out / "model.json", {
        "classes": list(BEAT_CLASSES), "aami_symbols": AAMI, "fs": FS, "band_hz": BAND_HZ,
        "window": [BEFORE, AFTER], "rr_features": list(RR_FEATURES),
        "conformal_threshold": q, "level": LEVEL, "history": cfg.history})
    result = Result(BEAT_ID, VERSION, "mitdb 1.0.0 (DS2 inter-patient test records)",
                    "macro_f1_nsvf", metrics["macro_f1_nsvf"], metrics, report.to_dict(),
                    split={"train_records": len(train_ids), "validation_records": len(val_ids),
                           "test_records": len(test_ids), "train_beats": len(tr["y"]),
                           "test_beats": len(y_test), "unit": "record"},
                    notes=["AAMI mapping and DS1/DS2 from Guo et al. 2019 (arXiv 1810.04121), "
                           "Table 1 and Section IV.A.",
                           "Headline macro-F1 is over N, S, V and F; Q has almost no beats.",
                           f"Validation and calibration records (from DS1): {val_ids}."])
    write_result(result, out, fairness_md=report.markdown())
    return result


# -- PTB-XL rhythm ---------------------------------------------------------------------


def rhythm_labels(root: Path) -> Any:
    import pandas as pd

    statements = pd.read_csv(root / "scp_statements.csv", index_col=0)
    rhythm = set(statements.index[statements["rhythm"] == 1])
    missing = [c for c in (*SINUS, AF) if c not in rhythm]
    if missing:
        raise ValueError(f"not rhythm codes in scp_statements.csv: {missing}")
    db = pd.read_csv(root / "ptbxl_database.csv", index_col="ecg_id")
    codes = db["scp_codes"].map(lambda s: set(ast.literal_eval(s)) & rhythm)

    def label(c: set[str]) -> int:
        if AF in c:
            return 1
        return 2 if c - set(SINUS) else 0

    db = db[codes.map(bool)].copy()
    db["label"] = codes[db.index].map(label)
    return db


def lead_ii(root: Path, filename_hr: str) -> NDArray[np.float32]:
    import wfdb

    rec = wfdb.rdrecord(str(root / filename_hr), channel_names=["II"])
    if rec.p_signal is None or rec.p_signal.shape[1] != 1 or rec.fs != 500:
        raise ValueError(f"{filename_hr}: no lead II at 500 Hz")
    x = bandpass(resample_poly(np.nan_to_num(rec.p_signal[:, 0]), 1, 2), FS)
    return np.resize(x, SAMPLES).astype(np.float32) if len(x) != SAMPLES else x


def waveform_cache(root: Path, files: Sequence[str], ckpt: Path) -> NDArray[np.float32]:
    """Lead II of every record as one (n, 2500) float32 array, built resumably."""
    path, done_path = ckpt / "lead_ii.npy", ckpt / "lead_ii.done"
    ckpt.mkdir(parents=True, exist_ok=True)
    done = int(done_path.read_text()) if done_path.exists() and path.exists() else 0
    mode = "r+" if done else "w+"
    x: np.memmap[Any, np.dtype[np.float32]]
    x = np.lib.format.open_memmap(path, mode=mode, dtype=np.float32,  # type: ignore[no-untyped-call]
                                  shape=(len(files), SAMPLES))
    if x.shape != (len(files), SAMPLES):
        raise ValueError(f"{path} has shape {x.shape}; delete it to rebuild")
    for i in range(done, len(files)):
        x[i] = lead_ii(root, files[i])
        if (i + 1) % 1000 == 0 or i + 1 == len(files):
            x.flush()
            done_path.write_text(str(i + 1))
            log(f"ptbxl: lead II cache {i + 1}/{len(files)}")
    return np.asarray(np.load(path, mmap_mode="r"))


class RhythmNet(nn.Module):
    """1D-CNN on a 10-s lead II strip at 250 Hz, input [N, 2500], logits [N, 3]."""

    def __init__(self, k: int = len(RHYTHM_CLASSES)) -> None:
        super().__init__()
        self.norm = Standardize()
        self.conv = nn.Sequential(block(1, 16, 7, 2), block(16, 32, 7, 2), block(32, 32, 5, 2),
                                  block(32, 64, 5, 2), block(64, 64, 5, 2), block(64, 64, 3, 2),
                                  GlobalPool())
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(128, k))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.conv(self.norm(x).unsqueeze(1)))


class Ensemble(nn.Module):
    """Mean class probability of the members: input `x` [N, 2500], output `p` [N, 3]."""

    def __init__(self, members: Sequence[nn.Module]) -> None:
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.stack([torch.softmax(m(x), dim=1) for m in self.members]).mean(dim=0)


def export_onnx(ensemble: Ensemble, out: Path, probe: NDArray[np.float32],
                threshold: float) -> dict[str, Any]:
    import onnxruntime as ort

    ensemble.eval()
    path = out / f"{EDGE_NAME}.onnx"
    torch.onnx.export(ensemble, (torch.from_numpy(probe[:2]),), str(path), input_names=["x"],
                      output_names=["p"], dynamic_axes={"x": {0: "n"}, "p": {0: "n"}},
                      opset_version=17, dynamo=False)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    (got,) = sess.run(["p"], {"x": probe})
    with torch.no_grad():
        want = ensemble(torch.from_numpy(probe)).numpy()
    if not np.allclose(got, want, atol=1e-4):
        raise RuntimeError(f"ONNX output differs from torch by {np.abs(got - want).max()}")
    spec = {"model_id": RHYTHM_ID, "version": VERSION, "file": path.name,
            "input": {"name": "x", "kind": "waveform", "field": "ecg_lead_ii", "fs": FS,
                      "samples": SAMPLES},
            "output": {"name": "p", "labels": list(RHYTHM_CLASSES)},
            "alert": {"label": "af", "min_probability": round(threshold, 6),
                      "urgency": "urgent"}}
    torchjob.write_json(out / f"{EDGE_NAME}.json", spec)
    return spec


def train_ptbxl(root: Path, out: Path) -> Result:
    torchjob.setup(0)
    db = rhythm_labels(root)
    members, epochs = MEMBERS, 25
    if smoke():
        db = db[db["strat_fold"].isin([1, 9, 10])].groupby("strat_fold").head(150)
        members, epochs = 2, 1
    ckpt = out / "ckpt"
    x = waveform_cache(root, list(db["filename_hr"]), ckpt)
    y = db["label"].to_numpy(dtype=np.int64)
    fold = db["strat_fold"].to_numpy()
    tr, va, te = fold <= 8, fold == 9, fold == 10
    log(f"ptbxl: records train {tr.sum()}, validation {va.sum()}, test {te.sum()}; "
        f"labels {np.bincount(y, minlength=3).tolist()}")
    nets, member_scores = [], []
    for k in range(members):
        final = ckpt / f"member{k}.final.pt"
        torchjob.setup(k)
        net = RhythmNet()
        if final.exists():
            net.load_state_dict(torch.load(final))
        else:
            cfg = torchjob.Fit(epochs=epochs, batch=64, lr=1e-3, patience=5, seed=k)
            torchjob.fit(net, [x[tr]], y[tr], [x[va]], y[va], cfg, ckpt / f"member{k}.pt",
                         weights=torchjob.class_weights(y[tr], 3))
            torchjob.save_atomic(net.state_dict(), final)
        nets.append(net)
        member_scores.append(torchjob.macro_f1(y[va], torchjob.predict_proba(net, [x[va]]),
                                               range(3)))
        log(f"ptbxl: member {k} validation macro-F1 {member_scores[-1]:.4f}")
    ensemble = Ensemble(nets).eval()

    def proba(mask: NDArray[np.bool_]) -> NDArray[np.float64]:
        p: NDArray[np.float64] = np.mean([torchjob.predict_proba(n, [x[mask]]) for n in nets],
                                         axis=0)
        return p

    p_cal, p_test = proba(va), proba(te)
    y_cal, y_test = y[va], y[te]
    q = conformal.classification_threshold(y_cal, p_cal, LEVEL)
    sets = conformal.prediction_sets(p_test, q)
    covered = conformal.set_covers(sets, y_test)
    threshold = operating_point(y_cal == 1, p_cal[:, 1], min_sensitivity=0.9)
    sens, spec = sensitivity_specificity(y_test == 1, p_test[:, 1], threshold)
    pred = p_test.argmax(axis=1)
    metrics = {"macro_f1": float(f1_score(y_test, pred, labels=[0, 1, 2], average="macro",
                                          zero_division=0)),
               "accuracy": float(accuracy_score(y_test, pred)),
               "af_auroc": float(roc_auc_score(y_test == 1, p_test[:, 1])),
               "af_ece": ece(y_test == 1, p_test[:, 1]), "ece": multiclass_ece(y_test, p_test),
               "af_operating_threshold": threshold, "af_sensitivity": sens,
               "af_specificity": spec, "coverage_90": float(covered.mean()),
               "mean_set_size": float(sets.sum(axis=1).mean())}
    for k, c in enumerate(RHYTHM_CLASSES):
        metrics[f"f1_{c}"] = float(f1_score(y_test == k, pred == k, zero_division=0))
        metrics[f"n_test_{c}"] = float((y_test == k).sum())
    for k, s in enumerate(member_scores):
        metrics[f"member{k}_val_macro_f1"] = s
    test = db[te]
    sex = test["sex"].map({0: "male", 1: "female"}).fillna("unknown").to_numpy()
    ages = test["age"].clip(upper=90).map(lambda a: age_band(float(a), bands())
                                          if a == a else "unknown").to_numpy()
    report = slice_report(RHYTHM_ID, "multiclass", y_test, p_test,
                          {"sex": sex, "age_band": ages}, covered=covered)
    report.note = REAL_DATA_NOTE
    out.mkdir(parents=True, exist_ok=True)
    torch.save(ensemble.state_dict(), out / "model.pt")
    edge = export_onnx(ensemble, out, np.ascontiguousarray(x[te][:8]), threshold)
    torchjob.write_json(out / "model.json", {
        "classes": list(RHYTHM_CLASSES), "sinus_codes": list(SINUS), "af_code": AF,
        "fs": FS, "samples": SAMPLES, "band_hz": BAND_HZ, "members": members,
        "conformal_threshold": q, "level": LEVEL})
    result = Result(RHYTHM_ID, VERSION, "ptb-xl 1.0.3 (strat_fold 10)", "macro_f1",
                    metrics["macro_f1"], metrics, report.to_dict(),
                    split={"train": int(tr.sum()), "validation": int(va.sum()),
                           "test": int(te.sum()), "unit": "record (patient-wise folds)"},
                    notes=["Folds 1-8 train, 9 validation and calibration, 10 test, as the "
                           "PhysioNet PTB-XL page recommends.",
                           f"Rhythm classes from scp_statements.csv: sinus = {', '.join(SINUS)}; "
                           f"af = {AF}; other = any other rhythm code.",
                           f"{members}-member ensemble (mean probability), exported to "
                           f"{EDGE_NAME}.onnx and checked against torch with onnxruntime."],
                    edge=[edge])
    write_result(result, out, fairness_md=report.markdown())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ahdt.models.ml.ecg")
    parser.add_argument("job", choices=("mitdb", "ptbxl"))
    args = parser.parse_args(argv)
    if args.job == "mitdb":
        r = train_mitdb(data_root("mitdb"), model_dir(BEAT_ID, out_root()))
    else:
        r = train_ptbxl(data_root("ptb-xl"), model_dir(RHYTHM_ID, out_root()))
    log(f"{r.model_id}: {r.metric} = {r.value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
