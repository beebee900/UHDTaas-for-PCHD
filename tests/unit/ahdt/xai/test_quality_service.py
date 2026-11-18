import numpy as np
import pytest

from ahdt.xai import attribution as A
from ahdt.xai import quality
from ahdt.xai.localise import Localiser
from ahdt.xai.service import OutputRecord, XaiService
from ahdt.xai.subjects import reference_set
from atra import contracts as c
from atra.contracts import ExplainArgs
from atra.provenance import ProvenanceStore
from tests.unit.ahdt.xai.examples import subject_for

HDT = "hdt-0123456789ab"
MODEL = "ahdt.respiratory.exacerbation_risk"


def test_quality_metrics_on_a_sample():
    pytest.importorskip("quantus")
    s = subject_for(MODEL)
    rows = reference_set(s.x, n=12, seed=4)

    def attribute(x):
        out = []
        for r in x:
            sub = type(s)(s.model_id, s.version, s.features, r, s.background, s.predict,
                          booster=s.booster)
            out.append([d.contribution for d in A.shap_tree(sub).drivers])
        return np.array(out)

    q = quality.evaluate(s.predict, rows, attribute, runs=8, samples=3)
    assert q.samples == 12 and -1.0 <= q.faithfulness <= 1.0
    assert q.robustness >= 0 and q.complexity > 0
    assert q.contract().faithfulness == q.faithfulness


def test_quality_goes_on_the_model_card(tmp_path):
    card = tmp_path / "card.md"
    card.write_text("# model\n\n## Validation\n\nx\n", encoding="utf-8")
    q = quality.Quality(0.5, 0.1, 1.2, 200)
    for _ in range(2):
        quality.write_to_card(card, quality.card_section(MODEL, "1.0.0", q, "shap.tree"))
    text = card.read_text(encoding="utf-8")
    assert text.count(quality.SECTION) == 1 and "Faithfulness correlation | 0.500" in text
    assert "## Validation" in text


async def test_explain_and_graph_tools_return_contract_data():
    subject = subject_for(MODEL)
    record = OutputRecord("out-1", MODEL, "1.0.0", HDT)

    async def outputs(output_id):
        return record if output_id == "out-1" else None

    async def subjects(rec):
        return subject

    store = ProvenanceStore("ahdt")
    from ahdt.xai.causal import ProvenanceRecorder

    rec = ProvenanceRecorder(store)
    obs = rec.observation("obs-1", hdt_id=HDT, field_name="pef", twin="respiratory")
    rec.model_run("out-1", MODEL, "1.0.0", hdt_id=HDT, used=[obs])
    service = XaiService(outputs, subjects, store, localiser=Localiser())
    handlers = service.handlers()
    ident = None
    body = await handlers["ahdt.xai.explain"](ExplainArgs(hdt_id=HDT, output_id="out-1",
                                                           audience="patient"), ident)
    c.AHDTExplanation.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert body["_meta"]["models"][0]["model_id"] == MODEL
    graph = await handlers["ahdt.xai.causal_graph"](
        c.CausalGraphArgs(hdt_id=HDT, output_id="out-1"), ident)
    c.CausalGraphData.model_validate(graph)
    assert len(graph["nodes"]) == 2 and graph["edges"][0]["weight"] == 1.0
    with pytest.raises(LookupError):
        await handlers["ahdt.xai.explain"](ExplainArgs(hdt_id=HDT, output_id="nope"), ident)
