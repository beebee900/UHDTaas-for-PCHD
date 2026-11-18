"""Report NLP with medspaCy (design 05, 5.5.1): radiology and lab narratives to findings.

A rule-based medspaCy pipeline (sentence splitter, target matcher, ConText) finds the kb
findings named in a narrative and marks each as present, negated or uncertain. Target rules
are the names of the kb findings; no clinical model is downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from apdt.models.context import Observations, kb


@dataclass(frozen=True)
class Mention:
    finding: str
    text: str
    present: bool
    uncertain: bool


@lru_cache(maxsize=1)
def pipeline() -> Any:
    import spacy
    from loguru import logger
    from medspacy.target_matcher import TargetRule

    logger.disable("PyRuSH")
    nlp = spacy.blank("en")
    nlp.add_pipe("medspacy_pyrush")
    matcher: Any = nlp.add_pipe("medspacy_target_matcher")
    rules = []
    for entry_id in kb().ids():
        if entry_id.startswith("find."):
            name = str(kb().entry(entry_id).content()["name"])
            rules.append(TargetRule(name.lower(), entry_id, pattern=None))
    matcher.add(rules)
    nlp.add_pipe("medspacy_context")
    return nlp


def read_report(text: str) -> list[Mention]:
    doc = pipeline()(text.lower())
    return [Mention(ent.label_, ent.text, not ent._.is_negated, bool(ent._.is_uncertain))
            for ent in doc.ents]


def apply_to(obs: Observations, text: str) -> list[Mention]:
    """Add the report's definite findings to the observations (uncertain ones are not)."""
    mentions = read_report(text)
    for m in mentions:
        if not m.uncertain:
            obs.findings.setdefault(m.finding, m.present)
    return mentions
