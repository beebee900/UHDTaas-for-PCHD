"""Knowledge extraction from clinical notes (design 04, 4.4.3).

medspaCy splits a note into sections and marks each mention negated, uncertain or
historical (ConText). Mentions are matched against the kb: finding names
(`kb/findings.yaml`), condition names (`kb/conditions.yaml`) and medicine names
(`kb/terminology/atc.csv`). The result is typed with Pydantic. scispaCy entity linking
(HPO, GO) runs in its own environment on the VM, and LLM extraction plugs into the same
schema through the cognitive services.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from functools import cached_property
from typing import Any, Literal

from pydantic import BaseModel

from ahdt.knowledge.phkg import PHKG
from atra.config import ROOT
from atra.connectors import DTKind
from atra.kb import KnowledgeBase

type Kind = Literal["finding", "condition", "medication"]


class Mention(BaseModel):
    kind: Kind
    ref: str
    text: str
    section: str | None
    negated: bool
    uncertain: bool
    historical: bool


class Extraction(BaseModel):
    findings: list[Mention]
    conditions: list[Mention]
    medications: list[Mention]


class NoteExtractor:
    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or KnowledgeBase(ROOT / "kb")

    @cached_property
    def terms(self) -> Mapping[str, tuple[Kind, str]]:
        """Lower-case phrase → (kind, kb id or ATC code)."""
        out: dict[str, tuple[Kind, str]] = {}
        for eid in self.kb.ids():
            content = self.kb.entry(eid).content()
            if eid.startswith("find.") and content.get("name"):
                out.setdefault(str(content["name"]).lower(), ("finding", eid))
            elif eid.startswith("cond.") and content.get("name"):
                name = str(content["name"]).lower()
                out.setdefault(name.split(" (")[0], ("condition", eid))
        with (ROOT / "kb" / "terminology" / "atc.csv").open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if len(row["code"]) == 7:
                    out.setdefault(row["display"].lower(), ("medication", row["code"]))
        return out

    @cached_property
    def nlp(self) -> Any:
        import medspacy
        from loguru import logger
        from medspacy.ner import TargetRule

        logger.disable("PyRuSH")
        nlp = medspacy.load(medspacy_enable=["medspacy_pyrush", "medspacy_target_matcher",
                                             "medspacy_context", "medspacy_sectionizer"])
        nlp.get_pipe("medspacy_target_matcher").add(
            [TargetRule(phrase, kind.upper()) for phrase, (kind, _) in self.terms.items()])
        return nlp

    def extract(self, text: str) -> Extraction:
        doc = self.nlp(text)
        found: dict[Kind, list[Mention]] = {"finding": [], "condition": [], "medication": []}
        for ent in doc.ents:
            kind, ref = self.terms[ent.text.lower()]
            found[kind].append(Mention(
                kind=kind, ref=ref, text=ent.text, section=ent._.section_category,
                negated=bool(ent._.is_negated), uncertain=bool(ent._.is_uncertain),
                historical=bool(ent._.is_historical)))
        return Extraction(findings=found["finding"], conditions=found["condition"],
                          medications=found["medication"])


async def apply(phkg: PHKG, hdt_id: str, extraction: Extraction, *,
                twin_of_medication: Mapping[str, DTKind] | None = None) -> list[str]:
    """Add the affirmed mentions to the person's PHKG. Returns the node ids written.

    A negated mention is not added. An uncertain condition is added with status
    `suspected`. A finding becomes a phenotype when it has an HPO code.
    """
    written = []
    for m in extraction.conditions:
        if not m.negated:
            status = "suspected" if m.uncertain else "active"
            written.append(await phkg.condition(hdt_id, m.ref, status=status))
    for m in extraction.findings:
        content = phkg.kb.entry(m.ref).content()
        if m.negated or not content.get("hpo"):
            continue
        kind = DTKind(content.get("twin", DTKind.WHOLE_BODY.value))
        written.append(await phkg.phenotype(hdt_id, str(content["hpo"]),
                                            str(content["name"]), kind))
    for m in extraction.medications:
        if m.negated:
            continue
        kind = (twin_of_medication or {}).get(m.ref, DTKind.WHOLE_BODY)
        written.append(await phkg.medication(hdt_id, m.ref, m.text.lower(), kind))
    return written
