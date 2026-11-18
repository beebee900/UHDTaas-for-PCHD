"""Ambient scribing (design 05, 5.2.1): speech-to-text → LLM SOAP sections → medspaCy
negation check → draft `Composition` that the clinician must sign.

- Speech-to-text is any object with Dyon's `VoiceProvider.transcribe(audio, content_type)`
  (faster-whisper for English, MMS for Yoruba, Hausa and Igbo in deployment).
- The LLM is a LangChain chat model; Dyon's `OfflineChatModel` serves tests and
  strict-residency runs.
- The check runs `ahdt.knowledge.extraction.NoteExtractor` (medspaCy ConText) on the
  transcript and on each section. A finding, condition or medicine whose negation differs,
  or that the note states but the transcript never mentions, becomes an issue for the
  clinician. medspaCy rules are English, so other languages are not checked.

Recording needs the patient's consent; without it the pipeline refuses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import Any, Protocol

from fhir.resources.R4B.composition import Composition
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ahdt.knowledge.extraction import Extraction, Mention, NoteExtractor
from apdt.records.episodes import EPISODE_EXT, PATIENT_SYSTEM
from atra.ids import new_record_id

LOINC = "http://loinc.org"
CONSULT_NOTE = {"system": LOINC, "code": "11488-4", "display": "Consult note"}
SECTIONS = {
    "subjective": {"system": LOINC, "code": "61150-9", "display": "Subjective Narrative"},
    "objective": {"system": LOINC, "code": "61149-1", "display": "Objective Narrative"},
    "assessment": {"system": LOINC, "code": "51848-0", "display": "Evaluation note"},
    "plan": {"system": LOINC, "code": "18776-5", "display": "Plan of care note"},
}
PROMPT = (
    "You turn a consultation transcript into a clinical note. Answer with one JSON object "
    "with the keys subjective, objective, assessment and plan, each a string. Use only what "
    "the transcript says. Keep negations (for example 'no cough'). Leave a key empty when "
    "the transcript says nothing for it.")
XHTML = "http://www.w3.org/1999/xhtml"


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, content_type: str) -> str: ...


class ScribeRefused(PermissionError):
    pass


@dataclass(frozen=True)
class Issue:
    kind: str
    ref: str
    text: str
    section: str
    detail: str


@dataclass
class ScribeDraft:
    composition: dict[str, Any]
    transcript: str
    sections: dict[str, str]
    issues: list[Issue] = field(default_factory=list)
    checked: bool = True


def _sections(reply: str) -> dict[str, str]:
    m = re.search(r"\{.*\}", reply, flags=re.S)
    data: Any = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: str(data.get(k) or "").strip() for k in SECTIONS}


def _index(extraction: Extraction) -> dict[str, list[Mention]]:
    out: dict[str, list[Mention]] = {}
    for m in (*extraction.findings, *extraction.conditions, *extraction.medications):
        out.setdefault(m.ref, []).append(m)
    return out


class ScribePipeline:
    def __init__(self, transcriber: Transcriber, llm: BaseChatModel, *,
                 extractor: NoteExtractor | None = None) -> None:
        self.transcriber = transcriber
        self.llm = llm
        self.extractor = extractor or NoteExtractor()

    async def soap(self, transcript: str) -> dict[str, str]:
        reply = await self.llm.ainvoke([SystemMessage(content=PROMPT),
                                        HumanMessage(content=transcript)])
        return _sections(str(reply.content))

    def check(self, transcript: str, sections: Mapping[str, str]) -> list[Issue]:
        heard = _index(self.extractor.extract(transcript))
        issues = []
        for name, text in sections.items():
            if not text:
                continue
            for ref, mentions in _index(self.extractor.extract(text)).items():
                for m in mentions:
                    said = heard.get(ref)
                    if not said:
                        issues.append(Issue("not_in_transcript", ref, m.text, name,
                                            "the note states it but the transcript does not "
                                            "mention it"))
                    elif all(s.negated != m.negated for s in said):
                        issues.append(Issue(
                            "negation_mismatch", ref, m.text, name,
                            "the note negates it but the transcript affirms it" if m.negated
                            else "the note affirms it but the transcript negates it"))
        return issues

    async def draft(self, audio: bytes, content_type: str, *, hdt_id: str, episode_id: str,
                    author: str, language: str = "en", recording_consented: bool,
                    at: datetime | None = None) -> ScribeDraft:
        if not recording_consented:
            raise ScribeRefused("the patient has not consented to recording the consultation")
        transcript = await self.transcriber.transcribe(audio, content_type)
        sections = await self.soap(transcript)
        checked = language == "en"
        issues = self.check(transcript, sections) if checked else []
        composition = draft_composition(sections, hdt_id=hdt_id, episode_id=episode_id,
                                        author=author, language=language,
                                        at=at or datetime.now(UTC))
        return ScribeDraft(composition, transcript, sections, issues, checked)


def draft_composition(sections: Mapping[str, str], *, hdt_id: str, episode_id: str,
                      author: str, language: str, at: datetime) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Composition", "id": new_record_id(), "status": "preliminary",
        "language": language, "type": {"coding": [CONSULT_NOTE]},
        "subject": {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}},
        "date": at.isoformat(), "author": [{"identifier": {"value": author}}],
        "title": "Consultation note (draft from scribing)",
        "extension": [{"url": EPISODE_EXT,
                       "valueReference": {"reference": f"EpisodeOfCare/{episode_id}"}}],
    }
    sections_out = [{"title": name.capitalize(), "code": {"coding": [SECTIONS[name]]},
                     "text": {"status": "generated",
                              "div": f'<div xmlns="{XHTML}">{escape(text)}</div>'}}
                    for name, text in sections.items() if text]
    if sections_out:
        body["section"] = sections_out
    return dict(Composition.model_validate(body).model_dump(mode="json", exclude_none=True))


def sign(composition: Mapping[str, Any], *, clinician: str, at: datetime,
         issues_reviewed: bool) -> dict[str, Any]:
    """The clinician's signature: the note becomes final with a legal attester."""
    if not issues_reviewed:
        raise ScribeRefused("review the scribing issues before signing")
    body = {**composition, "status": "final",
            "attester": [{"mode": "legal", "time": at.isoformat(),
                          "party": {"identifier": {"value": clinician}}}]}
    return dict(Composition.model_validate(body).model_dump(mode="json", exclude_none=True))
