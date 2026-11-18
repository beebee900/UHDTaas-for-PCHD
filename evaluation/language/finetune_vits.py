"""Fine-tune the Yoruba MMS voice on Igbo speech: the `finetune-hf-vits` recipe on one core.

    python -m evaluation.language.finetune_vits [--budget-s 10800] [--time-only] [--smoke]

Design 01, 1.3: no MMS-TTS Igbo voice exists, so `facebook/mms-tts-yor` is the starting point
and the Waxal `ibo_tts` speech (CC BY-SA 4.0, Media Trust) is the data. The recipe
(github.com/ylacombe/finetune-hf-vits, MIT) provides the training modules, the Cython
monotonic alignment search and the discriminator conversion; this script replaces its
Accelerate and `datasets` front end with a plain loop that reads the parquet files directly,
and sets the number of steps from the measured step time so that the run fits `--budget-s`.

Igbo text is mapped to the Yoruba character set (`tts.igbo_charset`). One speaker is kept: the
speaker with the most recordings. Output: `$ATRA/out/wp14d/mms-tts-ibo-ft/` (a `VitsModel`
folder) and `metrics.json`. State is saved every 20 steps and a restarted job resumes.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.language.tts import igbo_charset
from evaluation.language import common

REPO_ZIP = "finetune-hf-vits.zip"
SAVE_EVERY = 20
WEIGHTS = {"disc": 3.0, "fmaps": 1.0, "gen": 1.0, "kl": 1.5, "duration": 1.0, "mel": 35.0}
LR, BETAS, LR_DECAY = 2e-5, (0.8, 0.99), 0.999875
MAX_SECONDS, MIN_SECONDS, MAX_TOKENS = 12.0, 1.0, 400


def prepare_repo(data_dir: Path) -> Path:
    """Unpack the recipe and put it on the import path."""
    root = data_dir / "finetune-hf-vits-main"
    if not root.exists():
        with zipfile.ZipFile(data_dir / REPO_ZIP) as z:
            z.extractall(data_dir)
    sys.path.insert(0, str(root))
    return root


NEG = -1e9


def maximum_path(neg_cent: Any, mask: Any) -> Any:
    """Monotonic alignment search in NumPy, the algorithm of the recipe's `core.pyx`.

    `neg_cent` and `mask` are [batch, t_y, t_x]; the result has the same shape with 1 on the
    best monotonic path. The recipe compiles this loop with Cython, which needs the Python
    headers; the NumPy form vectorises over the token axis and is fast enough for batches of
    a few clips.
    """
    import torch

    values = neg_cent.detach().cpu().numpy().astype(np.float32)
    paths = np.zeros(values.shape, dtype=np.int32)
    t_ys = mask.sum(1)[:, 0].cpu().numpy().astype(int)
    t_xs = mask.sum(2)[:, 0].cpu().numpy().astype(int)
    for b in range(values.shape[0]):
        v, t_y, t_x = values[b], int(t_ys[b]), int(t_xs[b])
        for y in range(t_y):
            lo, hi = max(0, t_x + y - t_y), min(t_x, y + 1)
            xs = np.arange(lo, hi)
            if y == 0:
                v[0, xs] += np.maximum(0.0, NEG)
                continue
            cur = np.where(xs == y, NEG, v[y - 1, xs])
            prev = np.where(xs == 0, NEG, v[y - 1, np.maximum(xs - 1, 0)])
            v[y, xs] += np.maximum(prev, cur)
        index = t_x - 1
        for y in range(t_y - 1, -1, -1):
            paths[b, y, index] = 1
            if index != 0 and y != 0 and (index == y or v[y - 1, index] < v[y - 1, index - 1]):
                index -= 1
    return torch.from_numpy(paths).to(device=neg_cent.device, dtype=neg_cent.dtype)


def read_samples(files: list[Path], feature_extractor: Any, tokenizer: Any,
                 limit: int, speaker: str | None) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq
    import soundfile as sf

    from ahdt.models.language.audio import resample

    rows: list[dict[str, Any]] = []
    sr = feature_extractor.sampling_rate
    for f in files:
        table = pq.ParquetFile(f)
        for batch in table.iter_batches(batch_size=64, columns=["speaker_id", "text", "audio"]):
            for rec in batch.to_pylist():
                if speaker is not None and rec["speaker_id"] != speaker:
                    continue
                data, rate = sf.read(io.BytesIO(rec["audio"]["bytes"]), dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                data = resample(data, rate, sr)
                seconds = len(data) / sr
                text = igbo_charset(" ".join(rec["text"].split())).lower()
                ids = tokenizer(text, return_attention_mask=False)["input_ids"][:MAX_TOKENS + 1]
                if not (MIN_SECONDS < seconds < MAX_SECONDS) or len(ids) < 3:
                    continue
                feats = feature_extractor(data, sampling_rate=sr, return_attention_mask=False,
                                          do_normalize=False)
                rows.append({"input_ids": ids, "waveform": data, "speaker": rec["speaker_id"],
                             "labels": feats["input_features"][0],
                             "mel": feats["mel_scaled_input_features"][0], "text": text})
                if len(rows) >= limit:
                    return rows
    return rows


def speaker_counts(files: list[Path]) -> dict[str, int]:
    import pyarrow.parquet as pq

    counts: dict[str, int] = {}
    for f in files:
        for sid in pq.read_table(f, columns=["speaker_id"]).column("speaker_id").to_pylist():
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def collate(rows: list[dict[str, Any]], tokenizer: Any, fe: Any) -> dict[str, Any]:
    batch = tokenizer.pad([{"input_ids": r["input_ids"]} for r in rows], return_tensors="pt",
                          return_attention_mask=True)
    wav = fe.pad({"input_features": [np.asarray([r["waveform"]], dtype=np.float32).T
                                     for r in rows]}, padding=True, return_attention_mask=False,
                 return_tensors="pt")["input_features"]
    labels = fe.pad({"input_features": [np.asarray(r["labels"]).T for r in rows]},
                    return_tensors="pt", return_attention_mask=True)
    mel = fe.pad({"input_features": [np.asarray(r["mel"]).squeeze().T for r in rows]},
                 return_tensors="pt", return_attention_mask=True)["input_features"]
    batch["waveform"] = wav
    batch["labels"] = labels["input_features"].transpose(1, 2)
    batch["labels_attention_mask"] = labels["attention_mask"]
    batch["mel_scaled_input_features"] = mel.transpose(1, 2)
    batch["speaker_id"] = None
    return dict(batch)


def main(argv: list[str] | None = None) -> int:
    import torch

    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-s", type=float, default=10800)
    parser.add_argument("--time-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--samples", type=int, default=200)
    args = parser.parse_args(argv)
    smoke = args.smoke or common.smoke()

    torch.set_num_threads(1)
    torch.manual_seed(0)
    out = common.OUT / "mms-tts-ibo-ft"
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    prepare_repo(common.DATA)

    from convert_original_discriminator_checkpoint import convert_checkpoint
    from utils import (
        VitsConfig,
        VitsFeatureExtractor,
        VitsModelForPreTraining,
        slice_segments,
    )

    # transformers 5 configs lack the attribute that the recipe's embedding reads.
    VitsConfig.pad_token_id = None
    start_dir = work / "start"
    base = common.MODELS / "mms-tts-yor"
    if not (start_dir / "config.json").exists():
        convert_checkpoint(None, str(start_dir),
                           str(common.MODELS / "mms-tts-yor-disc" / "full_models" / "yor"
                               / "D_100000.pth"), str(base), None)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(start_dir), verbose=False)
    fe = VitsFeatureExtractor.from_pretrained(str(start_dir))
    files = sorted((common.DATA / "waxal-ibo" / "data" / "TTS" / "ibo").glob("ibo-train-*.parquet"))
    speaker = max((c := speaker_counts(files)).items(), key=lambda kv: kv[1])[0]
    common.log(f"speaker {speaker} of {len(c)}, {c[speaker]} recordings")
    limit = 12 if smoke else args.samples
    rows = read_samples(files, fe, tokenizer, limit, speaker)
    common.log(f"{len(rows)} training samples, "
               f"{sum(len(r['waveform']) for r in rows) / fe.sampling_rate:.0f} s of speech")

    model = VitsModelForPreTraining.from_pretrained(str(start_dir))
    model.decoder.apply_weight_norm()
    for flow in model.flow.flows:
        torch.nn.utils.weight_norm(flow.conv_pre)
        torch.nn.utils.weight_norm(flow.conv_post)
    disc = model.discriminator
    for d in disc.discriminators:
        d.apply_weight_norm()
    del model.discriminator
    model.train()
    disc.train()
    gen_opt = torch.optim.AdamW(model.parameters(), LR, betas=BETAS)
    disc_opt = torch.optim.AdamW(disc.parameters(), LR, betas=BETAS)
    gen_sched = torch.optim.lr_scheduler.ExponentialLR(gen_opt, gamma=LR_DECAY)
    disc_sched = torch.optim.lr_scheduler.ExponentialLR(disc_opt, gamma=LR_DECAY)
    seg, cfg_seg = model.segment_size, model.config.segment_size

    def forward(batch: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        o = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
                  labels=batch["labels"], labels_attention_mask=batch["labels_attention_mask"],
                  speaker_id=None, return_dict=True, monotonic_alignment_function=maximum_path)
        mel_t = slice_segments(batch["mel_scaled_input_features"], o.ids_slice, seg)
        mel_g = fe._torch_extract_fbank_features(o.waveform.squeeze(1))[1]
        target = slice_segments(batch["waveform"].transpose(1, 2),
                                o.ids_slice * fe.hop_length, cfg_seg)
        return o, mel_t, mel_g, target

    def d_loss(real: list[Any], fake: list[Any]) -> Any:
        return sum(torch.mean((1 - r) ** 2) + torch.mean(f ** 2) for r, f in zip(real, fake,
                                                                                  strict=True))

    def fmap_loss(real: list[Any], fake: list[Any]) -> Any:
        total = 0
        for rm, fm in zip(real, fake, strict=True):
            for r, f in zip(rm, fm, strict=True):
                total = total + torch.mean(torch.abs(r.detach() - f))
        return total * 2

    def kl(o: Any) -> Any:
        k = o.prior_log_variances - o.posterior_log_variances - 0.5
        k = k + 0.5 * ((o.prior_latents - o.prior_means) ** 2) * torch.exp(
            -2.0 * o.prior_log_variances)
        return torch.sum(k * o.labels_padding_mask) / torch.sum(o.labels_padding_mask)

    def train_step(batch: dict[str, Any]) -> dict[str, float]:
        o, mel_t, mel_g, target = forward(batch)
        real, _ = disc(target)
        fake, _ = disc(o.waveform.detach())
        loss_d = d_loss(real, fake)
        (loss_d * WEIGHTS["disc"]).backward()
        torch.nn.utils.clip_grad_norm_(disc.parameters(), 1.0)
        disc_opt.step()
        disc_opt.zero_grad()
        _, fm_t = disc(target)
        fake, fm_g = disc(o.waveform)
        l_dur = torch.sum(o.log_duration)
        l_mel = torch.nn.functional.l1_loss(mel_t, mel_g)
        l_kl = kl(o)
        l_fm = fmap_loss(fm_t, fm_g)
        l_gen = sum(torch.mean((1 - f) ** 2) for f in fake)
        total = (l_dur * WEIGHTS["duration"] + l_mel * WEIGHTS["mel"] + l_kl * WEIGHTS["kl"]
                 + l_fm * WEIGHTS["fmaps"] + l_gen * WEIGHTS["gen"])
        total.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        gen_opt.step()
        gen_opt.zero_grad()
        return {"mel": float(l_mel), "kl": float(l_kl), "duration": float(l_dur),
                "fmaps": float(l_fm), "gen": float(l_gen), "disc": float(loss_d)}

    state_path = work / "state.pt"
    step, total, history, seconds = 0, 0, [], 0.0
    order: list[int] = []
    gen = np.random.default_rng(0)
    if state_path.exists() and not args.time_only:
        st = torch.load(state_path, weights_only=False)
        model.load_state_dict(st["gen"])
        disc.load_state_dict(st["disc"])
        gen_opt.load_state_dict(st["gen_opt"])
        disc_opt.load_state_dict(st["disc_opt"])
        step, total, history, seconds = st["step"], st["total"], st["history"], st["seconds"]
        common.log(f"resumed at step {step} of {total}")

    probe = 2
    t0 = time.time()
    while not total or step < total:
        if len(order) < args.batch:
            order = list(gen.permutation(len(rows)))
        idx, order = order[:args.batch], order[args.batch:]
        batch = collate([rows[i] for i in idx], tokenizer, fe)
        t_step = time.time()
        loss = train_step(batch)
        step += 1
        if step % max(1, len(rows) // args.batch) == 0:
            gen_sched.step()
            disc_sched.step()
        history.append({"step": step, "sec": time.time() - t_step, **loss})
        common.log(f"step {step}/{total or '?'} mel {loss['mel']:.3f} kl {loss['kl']:.3f} "
                   f"{time.time() - t_step:.1f}s")
        if not total and step == probe:
            per_step = sum(h["sec"] for h in history[-probe:]) / probe
            total = probe if smoke else max(probe + 1, int(args.budget_s / per_step))
            common.write_json(out / "timing.json", {
                "sec_per_step": per_step, "batch": args.batch, "samples": len(rows),
                "planned_steps": total, "budget_s": args.budget_s})
            common.log(f"{per_step:.1f} s/step -> {total} steps")
            if args.time_only:
                return 0
        if step % SAVE_EVERY == 0 and total:
            torch.save({"gen": model.state_dict(), "disc": disc.state_dict(),
                        "gen_opt": gen_opt.state_dict(), "disc_opt": disc_opt.state_dict(),
                        "step": step, "total": total, "history": history,
                        "seconds": seconds + time.time() - t0}, work / "state.tmp")
            (work / "state.tmp").replace(state_path)

    model.eval()
    model.discriminator = disc
    for d in disc.discriminators:
        d.remove_weight_norm()
    model.decoder.remove_weight_norm()
    for flow in model.flow.flows:
        torch.nn.utils.remove_weight_norm(flow.conv_pre)
        torch.nn.utils.remove_weight_norm(flow.conv_post)
    model.save_pretrained(out / "model")
    tokenizer.save_pretrained(out / "model")
    from transformers import VitsModel

    VitsModel.from_pretrained(str(out / "model")).save_pretrained(out / "model")
    seconds += time.time() - t0
    head = history[: max(1, len(history) // 5)]
    tail = history[-max(1, len(history) // 5):]
    common.write_json(out / "metrics.json", {
        "steps": step, "batch": args.batch, "samples": len(rows), "speaker": speaker,
        "seconds": seconds, "mel_first_fifth": sum(h["mel"] for h in head) / len(head),
        "mel_last_fifth": sum(h["mel"] for h in tail) / len(tail),
        "base": "facebook/mms-tts-yor", "data": "google/WaxalNLP ibo_tts",
        "files": common.file_hashes(out, "model"), "history": history})
    common.log(f"done: {step} steps in {seconds:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
