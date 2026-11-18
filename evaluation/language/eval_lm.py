"""Evaluate the base model and the LoRA adapter of one language on held-out text.

    python -m evaluation.language.eval_lm <lang> [--n-mt 40] [--n-dialogue 30]

Two tests, both on text the adapter never saw:
- translation: English to the language on human-translated sentences (MENYO-20k test for
  Yoruba, MAFAND-MT test for the others), scored with chrF against the human reference;
- dialogue: the assistant reply for held-out template slots, scored with chrF against the
  reference reply (NLLB translation, or the Pidgin template). A reference made by a model
  makes this number a measure of agreement with that model, not of quality.

The base model (adapter disabled) runs on a smaller subset. Outputs and scores go to
`$ATRA/out/wp14d/eval/<lang>.json`.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from ahdt.models.language.prompts import TRANSLATE
from evaluation.language import common
from evaluation.language.metrics import chrf
from evaluation.language.train_lora import IM_END

MAX_NEW = 80
BASE_SHARE = 0.4


def generate(model: Any, tok: Any, messages: list[dict[str, str]], max_new: int) -> str:
    import torch

    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tok(prompt, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tok.pad_token_id, eos_token_id=tok.convert_tokens_to_ids(
                                 IM_END))
    return str(tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)).strip()


def score(items: list[dict[str, Any]], key: str) -> float | None:
    rows = [i for i in items if key in i]
    return chrf([i[key] for i in rows], [i["reference"] for i in rows]) if rows else None


def main(argv: list[str] | None = None) -> int:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("lang", choices=common.LANGS)
    parser.add_argument("--n-mt", type=int, default=40)
    parser.add_argument("--n-dialogue", type=int, default=30)
    args = parser.parse_args(argv)
    if common.smoke():
        args.n_mt, args.n_dialogue = 2, 2
    torch.set_num_threads(1)
    name = common.NAMES[args.lang]
    held = json.loads((common.DATA / "sft" / f"eval_{args.lang}.json").read_text("utf-8"))
    base = str(common.MODELS / "qwen")
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float32)
    model = PeftModel.from_pretrained(model, str(common.OUT / f"lora-{args.lang}" / "adapter"))
    model.eval()
    system = {"role": "system", "content": held["dialogue"][0]["context"][0]["content"]}

    mt = [dict(i) for i in held["mt"][:args.n_mt]]
    dialogue = [dict(i) for i in held["dialogue"][:args.n_dialogue]]
    n_base = max(1, int(BASE_SHARE * args.n_mt))
    t0 = time.time()
    for k, item in enumerate(mt):
        msgs = [system, {"role": "user",
                         "content": TRANSLATE.format(lang=name, text=item["english"])}]
        item["adapter"] = generate(model, tok, msgs, MAX_NEW)
        if k < n_base:
            with model.disable_adapter():
                item["base"] = generate(model, tok, msgs, MAX_NEW)
    common.log(f"translation done in {time.time() - t0:.0f} s")
    for k, item in enumerate(dialogue):
        item["adapter"] = generate(model, tok, item["context"], MAX_NEW)
        if k < max(1, int(BASE_SHARE * args.n_dialogue)):
            with model.disable_adapter():
                item["base"] = generate(model, tok, item["context"], MAX_NEW)
    common.log(f"dialogue done in {time.time() - t0:.0f} s")
    result = {
        "lang": args.lang,
        "translation": {"n": len(mt), "n_base": n_base, "chrf_adapter": score(mt, "adapter"),
                        "chrf_base": score(mt, "base"),
                        "reference_source": "MENYO-20k test" if args.lang == "yo"
                        else "MAFAND-MT test", "items": mt},
        "dialogue": {"n": len(dialogue), "chrf_adapter": score(dialogue, "adapter"),
                     "chrf_base": score(dialogue, "base"), "items": [
                         {k: v for k, v in d.items() if k != "context"} for d in dialogue]},
    }
    common.write_json(common.OUT / "eval" / f"{args.lang}.json", result)
    common.log(f"chrF translation adapter {result['translation']['chrf_adapter']:.1f} "
               f"base {result['translation']['chrf_base']}; dialogue adapter "
               f"{result['dialogue']['chrf_adapter']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
