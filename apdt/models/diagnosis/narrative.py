"""LLM narrative and missed-candidate check (design 05, 5.5.1).

The model writes a short narrative of the differential from fact lines that carry kb ids, and
proposes conditions the list may have missed. Every kept sentence cites a fact id that was
given to it, and every proposed condition cites a kb entry. A proposal appears only as
"suggested for consideration (not scored)" with the citations of its kb entry. The text never
changes a probability. When the model is offline or its output has no valid citation, the
narrative is the plain fact lines.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ahdt.models.language.client import BackendUnavailable
from ahdt.models.language.converse import Converser
from apdt.models.context import kb
from apdt.models.diagnosis.symbolic import Listing
from atra.kb import Citation

CITE = re.compile(r"\[([a-z]+\.[A-Za-z0-9_.]+)\]")
SUGGEST = "SUGGEST:"
LABEL = "suggested for consideration (not scored)"

SYSTEM = ("You write decision-support notes for a clinician. Use only the facts given. "
          "You do not set probabilities and you do not prescribe.")
INSTRUCTION = (
    "Write at most four sentences that summarise the differential for the clinician. Use only "
    "the facts. End every sentence with the id of the fact it uses in square brackets. Then add "
    f"one final line that starts with {SUGGEST} followed by a JSON list of other conditions to "
    "consider, each as {\"condition\": <id from the candidate list>, \"why\": <short reason>, "
    "\"cite\": <fact id>}. Use an empty list when there are none.")


@dataclass(frozen=True)
class Suggestion:
    condition: str
    name: str
    why: str
    label: str
    citations: tuple[Citation, ...]


@dataclass
class Narrative:
    text: str
    sentences: list[tuple[str, str]]
    suggestions: list[Suggestion] = field(default_factory=list)
    backend: str = "facts"
    dropped: int = 0


def fact_lines(listing: Listing, present: Sequence[str], tests: dict[str, bool]) -> dict[str, str]:
    """Fact id → text for the listed candidates and the evidence."""
    facts: dict[str, str] = {}
    for cand in listing.listed:
        support = ", ".join(str(kb().entry(i.node_id).content()["name"]).lower()
                            for i in cand.for_)
        flag = " (must rule out: red flag present)" if any(
            m.condition == cand.condition for m in listing.must_rule_out) else ""
        facts[cand.condition] = (f"{cand.name}: probability {cand.probability:.2f}, "
                                 f"prior {cand.prior:.3f}; supported by {support}{flag}")
    for f in present:
        facts[f] = f"{kb().entry(f).content()['name']} is present"
    for t, positive in tests.items():
        facts[t] = f"{kb().entry(t).content()['name']} is {'positive' if positive else 'negative'}"
    return facts


def _citations(entry_id: str) -> tuple[Citation, ...]:
    return tuple(kb().entry(entry_id).provenance.citations())


def _parse(reply: str, allowed: set[str], listed: set[str], excluded: set[str]
           ) -> tuple[list[tuple[str, str]], list[Suggestion], int]:
    sentences: list[tuple[str, str]] = []
    suggestions: list[Suggestion] = []
    dropped = 0
    body, _, tail = reply.partition(SUGGEST)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        ids = CITE.findall(sentence)
        if ids and all(i in allowed for i in ids):
            sentences.append((CITE.sub("", sentence).strip(), ids[-1]))
        else:
            dropped += 1
    try:
        proposals = json.loads(tail.strip()) if tail.strip() else []
    except json.JSONDecodeError:
        proposals = []
        dropped += 1
    conditions = {i for i in kb().ids() if i.startswith("cond.")}
    for p in proposals if isinstance(proposals, list) else []:
        cond, cite = str(p.get("condition")), str(p.get("cite"))
        if cond not in conditions or cond in listed or cond in excluded \
                or (cite not in allowed and cite not in kb()):
            dropped += 1
            continue
        cites = _citations(cond)
        if not cites:
            dropped += 1
            continue
        suggestions.append(Suggestion(cond, str(kb().entry(cond).content()["name"]),
                                      str(p.get("why", "")), LABEL, cites))
    return sentences, suggestions, dropped


async def narrate(converser: Converser, listing: Listing, present: Sequence[str],
                  tests: dict[str, bool], *, locale: str = "en") -> Narrative:
    facts = fact_lines(listing, present, tests)
    plain = [(text, fid) for fid, text in facts.items() if fid.startswith("cond.")]
    candidate_ids = sorted(i for i in kb().ids() if i.startswith("cond."))
    lines = [f"[{fid}] {text}" for fid, text in facts.items()]
    lines.append("Candidate condition ids: " + ", ".join(candidate_ids))
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Facts:\n" + "\n".join(lines) + "\n\n"
                 + INSTRUCTION}]
    try:
        reply, _ = await converser.chain.chat(messages, max_tokens=400, locale=locale)
    except BackendUnavailable:
        return Narrative(" ".join(f"{t}." for t, _ in plain), plain)
    listed = {c.condition for c in listing.listed}
    excluded = {e.condition for e in listing.excluded}
    sentences, suggestions, dropped = _parse(reply.text, set(facts), listed, excluded)
    if not sentences:
        return Narrative(" ".join(f"{t}." for t, _ in plain), plain, suggestions, "facts",
                         dropped)
    return Narrative(" ".join(s for s, _ in sentences), sentences, suggestions, reply.backend,
                     dropped)
