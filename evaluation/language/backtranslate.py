"""Back-translation agreement for the dialogue outputs of yo, ha and ig.

    python -m evaluation.language.backtranslate

Each adapter reply is translated back to English with NLLB-200 and compared by chrF with the
English sentence it answers. The same is done for the reference reply, which gives the ceiling
that a perfect reply would reach through the same round trip. Pidgin has no NLLB code, so it is
not scored this way. Output: `$ATRA/out/wp14d/eval/backtranslation.json`.
"""

from __future__ import annotations

import json

from evaluation.language import common
from evaluation.language.metrics import chrf
from evaluation.language.translate import Translator


def main() -> int:
    translator = Translator()
    result: dict[str, dict[str, float | int]] = {}
    for lang in ("yo", "ha", "ig"):
        path = common.OUT / "eval" / f"{lang}.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text("utf-8"))["dialogue"]["items"]
        english = [i["english"] for i in items]
        back_model = translator([i["adapter"] for i in items], lang, "en")
        back_ref = translator([i["reference"] for i in items], lang, "en")
        result[lang] = {"n": len(items),
                        "chrf_adapter": chrf(back_model, english),
                        "chrf_reference": chrf(back_ref, english)}
        common.log(f"{lang}: adapter {result[lang]['chrf_adapter']:.1f} "
                   f"reference {result[lang]['chrf_reference']:.1f}")
    common.write_json(common.OUT / "eval" / "backtranslation.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
