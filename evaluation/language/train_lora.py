"""LoRA fine-tuning of Qwen2.5-0.5B-Instruct for one language (PEFT, CPU, one core).

    python -m evaluation.language.train_lora <lang> [--budget-s 4500] [--time-only]

The job measures the time of its first steps, sets the number of steps so that training fits
`--budget-s`, and trains with a warm-up and cosine schedule. The loss covers the assistant
turns only. State (adapter, optimiser, step, history) is saved every 10 steps and a restarted
job resumes from it. Output: `$ATRA/out/wp14d/lora-<lang>/` with `adapter/` (PEFT files) and
`metrics.json`. `--time-only` runs three steps, reports seconds per step and tokens per second,
and stops.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from typing import Any

from evaluation.language import common

IM_START, IM_END = "<|im_start|>", "<|im_end|>"
TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
SAVE_EVERY = 10


def render(messages: list[dict[str, str]]) -> list[tuple[str, bool]]:
    """Chat segments in the Qwen2.5 format as (text, trained) pairs."""
    segments: list[tuple[str, bool]] = []
    for m in messages:
        head = f"{IM_START}{m['role']}\n"
        if m["role"] == "assistant":
            segments += [(head, False), (m["content"] + IM_END, True), ("\n", False)]
        else:
            segments.append((f"{head}{m['content']}{IM_END}\n", False))
    return segments


def encode(tok: Any, messages: list[dict[str, str]], max_len: int) -> tuple[list[int], list[int]]:
    ids: list[int] = []
    labels: list[int] = []
    for text, trained in render(messages):
        part = tok(text, add_special_tokens=False)["input_ids"]
        ids += part
        labels += part if trained else [-100] * len(part)
    return ids[:max_len], labels[:max_len]


def collate(rows: list[tuple[list[int], list[int]]], pad: int) -> dict[str, Any]:
    import torch

    n = max(len(r[0]) for r in rows)
    ids = torch.full((len(rows), n), pad, dtype=torch.long)
    labels = torch.full((len(rows), n), -100, dtype=torch.long)
    mask = torch.zeros((len(rows), n), dtype=torch.long)
    for i, (x, y) in enumerate(rows):
        ids[i, :len(x)], labels[i, :len(y)], mask[i, :len(x)] = (
            torch.tensor(x), torch.tensor(y), 1)
    return {"input_ids": ids, "labels": labels, "attention_mask": mask}


def lr_at(step: int, total: int, peak: float, warmup: int) -> float:
    if step < warmup:
        return peak * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return peak * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))


def main(argv: list[str] | None = None) -> int:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("lang", choices=common.LANGS)
    parser.add_argument("--budget-s", type=float, default=4500)
    parser.add_argument("--time-only", action="store_true")
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--max-len", type=int, default=192)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    out = common.OUT / f"lora-{args.lang}"
    state_path = out / "state.pt"
    base = str(common.MODELS / "qwen")
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float32)
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, target_modules=list(TARGETS),
        task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)

    rows = [encode(tok, r["messages"], args.max_len)
            for r in common.read_jsonl(common.DATA / "sft" / f"sft_{args.lang}.jsonl")]
    rng = random.Random(args.seed)
    held = common.DATA / "sft" / f"eval_{args.lang}.json"
    dev = [encode(tok, [*c["context"], {"role": "assistant", "content": c["reference"]}],
                  args.max_len)
           for c in json.loads(held.read_text(encoding="utf-8"))["dialogue"][:16]]
    order: list[int] = []

    def next_batch() -> dict[str, Any]:
        nonlocal order
        if len(order) < args.batch:
            order = list(range(len(rows)))
            rng.shuffle(order)
        idx, order = order[:args.batch], order[args.batch:]
        return collate([rows[i] for i in idx], tok.pad_token_id)

    step, history, total, seconds = 0, [], 0, 0.0
    if state_path.exists() and not args.time_only:
        st = torch.load(state_path, weights_only=False)
        model.load_state_dict(st["lora"], strict=False)
        opt.load_state_dict(st["opt"])
        step, history, total, seconds = st["step"], st["history"], st["total"], st["seconds"]
        rng.setstate(st["rng"])
        order = st["order"]
        common.log(f"resumed at step {step} of {total}")

    tokens = 0
    t0 = time.time()
    probe = 3
    while True:
        if total and step >= total:
            break
        batch = next_batch()
        lr = lr_at(step, total or 10**9, args.lr, 3 if not total else max(2, total // 20))
        for g in opt.param_groups:
            g["lr"] = lr
        t_step = time.time()
        loss = model(**batch).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        n_tok = int(batch["attention_mask"].sum())
        tokens += n_tok
        history.append({"step": step, "loss": float(loss), "sec": time.time() - t_step,
                        "tokens": n_tok})
        common.log(f"step {step}/{total or '?'} loss {float(loss):.3f} "
                   f"{time.time() - t_step:.1f}s {n_tok} tok lr {lr:.2e}")
        if not total and step == probe:
            per_step = sum(h["sec"] for h in history[-probe:]) / probe
            total = max(probe + 1, int(args.budget_s / per_step))
            common.log(f"{per_step:.1f} s/step -> {total} steps in {args.budget_s:.0f} s")
            common.write_json(out / "timing.json", {
                "lang": args.lang, "sec_per_step": per_step, "batch": args.batch,
                "tokens_per_sec": tokens / sum(h["sec"] for h in history[-probe:]),
                "planned_steps": total, "budget_s": args.budget_s})
            if args.time_only:
                return 0
        if step % SAVE_EVERY == 0 and total:
            seconds_now = seconds + time.time() - t0
            lora = {k: v for k, v in model.state_dict().items() if "lora_" in k}
            torch.save({"lora": lora, "opt": opt.state_dict(), "step": step, "total": total,
                        "history": history, "seconds": seconds_now, "rng": rng.getstate(),
                        "order": order}, state_path.with_suffix(".tmp"))
            state_path.with_suffix(".tmp").replace(state_path)

    model.eval()
    dev_loss = []
    with torch.no_grad():
        for r in dev:
            dev_loss.append(float(model(**collate([r], tok.pad_token_id)).loss))
    adapter = out / "adapter"
    model.save_pretrained(str(adapter))
    seconds += time.time() - t0
    window = [h["loss"] for h in history[-10:]]
    metrics = {
        "lang": args.lang, "steps": step, "batch": args.batch, "rank": args.rank,
        "train_examples": len(rows), "seconds": seconds, "dev_loss": sum(dev_loss) / len(dev_loss),
        "train_loss_first10": sum(h["loss"] for h in history[:10]) / min(10, len(history)),
        "train_loss_last10": sum(window) / len(window),
        "base_model": "Qwen/Qwen2.5-0.5B-Instruct", "files": common.file_hashes(out, "adapter"),
        "history": history}
    common.write_json(out / "metrics.json", metrics)
    common.log(f"done: {step} steps in {seconds:.0f} s, dev loss {metrics['dev_loss']:.3f}")
    if state_path.exists():
        state_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
