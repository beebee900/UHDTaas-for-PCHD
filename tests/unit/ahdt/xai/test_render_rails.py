import pytest

from ahdt.xai.localise import Localiser
from ahdt.xai.rails import WITHHELD, Facts, NemoOutputRail, check, guard
from ahdt.xai.render import flesch_reading_ease, readability, render
from atra import contracts as c


def explanation() -> c.AHDTExplanation:
    return c.AHDTExplanation(
        explanation_id="exp-1", output_id="out-1", model_id="ahdt.respiratory.exacerbation_risk",
        version="1.0.0", explainer="shap.tree@0.52.0", method_family="attribution",
        drivers=[c.Driver(feature="viral_illness", value=1, contribution=1.58, direction="up"),
                 c.Driver(feature="adherence", value=0.6, contribution=-0.4, direction="down"),
                 c.Driver(feature="pm25", value=40, contribution=0.2, direction="up")],
        uncertainty={"lower": 0.1, "upper": 0.45, "level": 0.9},
        counterfactuals=[c.Counterfactual(changes={"adherence": 0.9}, outcome=0.2)],
        text="")


def with_text(audience: str) -> c.AHDTExplanation:
    e = explanation()
    return e.model_copy(update={"text": render(e, audience, output=0.35)})


def test_audiences_differ_as_the_design_says():
    clinician, patient = with_text("clinician").text, with_text("patient").text
    assert clinician.count("raises") + clinician.count("lowers") == 3
    assert "viral illness" in patient and "pm25" not in patient
    assert "1.58" in clinician and "1.58" not in patient
    assert "If you changed adherence to 0.9" in patient


def test_patient_text_is_plain():
    assert readability(with_text("patient").text)["ok"]
    assert flesch_reading_ease("The quick brown fox jumps over the lazy dog.") > 80


def test_signal_model_gives_the_patient_a_summary_only():
    text = render(explanation(), "patient", kind="signal", label="af")
    assert text == "A computer program checked your exacerbation risk. It found af most likely."


def test_supported_text_passes_the_rail():
    e = with_text("clinician")
    assert check(e.text, Facts.of(e, output=0.35)).ok


def test_rail_rejects_an_injected_number():
    e = with_text("clinician")
    facts = Facts.of(e, output=0.35)
    bad = e.text + " The risk will rise by 47 percent next week."
    verdict = check(bad, facts)
    assert not verdict.ok and "47" in verdict.unsupported
    shown, _ = guard(bad, facts)
    assert shown == WITHHELD


def test_rail_rejects_a_dose_nobody_stated():
    e = with_text("clinician")
    assert not check(e.text + " Take a tablet each day.", Facts.of(e, output=0.35)).ok


def test_percent_form_of_a_supported_number_passes():
    e = with_text("clinician")
    assert check("The range is from 10% to 45%.", Facts.of(e, output=0.35)).ok


def test_localiser_uses_the_model_text_after_the_rail():
    e = with_text("patient")
    ok = Localiser(lambda prompt: "Ewu kekere. 2 idi.").render(e, "patient", "yo", output=0.35)
    assert not ok.fell_back and ok.language == "yo"
    bad = Localiser(lambda prompt: "Ewu jẹ 91 ogorun.").render(e, "patient", "yo", output=0.35)
    assert bad.fell_back and bad.language == "en" and bad.text == e.text
    assert "91" in bad.verdict.unsupported


def test_localiser_without_a_model_gives_english():
    e = with_text("patient")
    out = Localiser().render(e, "patient", "ha", output=0.35)
    assert out.fell_back and out.text == e.text


def test_nemo_output_rail_blocks_and_passes():
    nemo = NemoOutputRail()
    e = with_text("clinician")
    facts = Facts.of(e, output=0.35)
    shown, verdict = nemo.apply(e.text, facts)
    assert verdict.ok and shown == e.text
    shown, verdict = nemo.apply(e.text + " Risk is 83 percent.", facts)
    assert not verdict.ok and shown == WITHHELD


@pytest.mark.parametrize("language", ["yo", "ha", "ig", "pcm"])
def test_sentence_cap_for_other_languages(language):
    assert readability("Short one. Another short one.", language)["ok"]
    assert not readability(" ".join(["word"] * 30) + ".", language)["ok"]
