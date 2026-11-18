"""The narrative keeps only cited sentences and labels unscored suggestions."""

from __future__ import annotations

import json

from ahdt.models.language.converse import build_converser
from apdt.models.diagnosis import narrative, symbolic
from apdt.models.diagnosis.bn import DifferentialModel
from apdt.models.reasoning import ClinicalReasoner
from evaluation.models.apdt.scenarios import BY_SCENARIO

MODEL = DifferentialModel()


def setup(key: str = "ao") -> tuple[symbolic.Listing, list[str], dict[str, bool]]:
    s = BY_SCENARIO[key]
    patient, obs = ClinicalReasoner(MODEL).prepare(s.patient, s.observations)
    diff = MODEL.differential(patient, obs)
    listing = symbolic.apply(diff, patient, obs)
    present = [f for f, v in obs.findings.items() if v]
    return listing, present, dict(obs.tests)


async def run(reply: str, key: str = "ao") -> narrative.Narrative:
    listing, present, tests = setup(key)
    converser = build_converser(local=False, responder=lambda _prompt: reply)
    return await narrative.narrate(converser, listing, present, tests)


async def test_cited_sentences_are_kept_and_uncited_are_dropped() -> None:
    reply = ("Malaria is the leading diagnosis [cond.malaria_falciparum]. "
             "The patient is very ill. "
             "A positive rapid test supports it [test.malaria_rdt_hrp2].")
    out = await run(reply)
    assert [cite for _, cite in out.sentences] == ["cond.malaria_falciparum",
                                                   "test.malaria_rdt_hrp2"]
    assert out.dropped == 1 and "very ill" not in out.text and "[" not in out.text


async def test_invented_citation_is_rejected() -> None:
    out = await run("Malaria is likely [cond.invented].")
    assert out.dropped == 1 and out.backend == "facts"
    assert "Plasmodium falciparum malaria" in out.text


async def test_missed_candidate_is_labelled_and_cited() -> None:
    proposal = [{"condition": "cond.enteric_fever", "why": "fever with headache",
                 "cite": "find.fever"},
                {"condition": "cond.not_in_kb", "why": "x", "cite": "find.fever"},
                {"condition": "cond.malaria_falciparum", "why": "already listed",
                 "cite": "find.fever"}]
    reply = ("Malaria leads [cond.malaria_falciparum].\n"
             + narrative.SUGGEST + " " + json.dumps(proposal))
    out = await run(reply)
    assert [s.condition for s in out.suggestions] == ["cond.enteric_fever"]
    assert out.suggestions[0].label == "suggested for consideration (not scored)"
    assert out.suggestions[0].citations
    assert out.dropped == 2


async def test_probabilities_are_untouched() -> None:
    listing, present, tests = setup()
    before = [c.probability for c in listing.listed]
    converser = build_converser(local=False, responder=lambda _p: "X [cond.malaria_falciparum].")
    await narrative.narrate(converser, listing, present, tests)
    assert [c.probability for c in listing.listed] == before


async def test_default_offline_backend_gives_the_fact_lines() -> None:
    listing, present, tests = setup()
    out = await narrative.narrate(build_converser(local=False), listing, present, tests)
    assert out.text and out.suggestions == []
