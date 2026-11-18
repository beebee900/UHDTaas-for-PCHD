from apdt.knowledge.clinical_graph import ClinicalGraph
from atra.backends.graph import NetworkXGraph

EP = "ep-2026-000001"


async def test_episode_graph_links_evidence_and_reaches_the_owning_twin():
    cg = ClinicalGraph(NetworkXGraph())
    await cg.finding(EP, "find.fever_history")
    await cg.differential(EP, "cond.malaria_falciparum", 0.6)
    await cg.differential(EP, "cond.enteric_fever", 0.2)
    await cg.finding(EP, "find.fever", present=True, source="exam")
    await cg.test(EP, "test.malaria_rdt_hrp2", for_conditions=["cond.malaria_falciparum"])
    await cg.result(EP, "test.malaria_rdt_hrp2", value="positive",
                    supports=["cond.malaria_falciparum"])
    await cg.diagnosis(EP, "cond.malaria_falciparum", confirmed_by=["test.malaria_rdt_hrp2"],
                       severity="uncomplicated")
    await cg.goal(EP, "work", "Back at work within a week")
    await cg.treatment(EP, "tx.malaria.uncomplicated.artemether_lumefantrine", goals=["work"])

    ev = await cg.evidence(EP, "cond.malaria_falciparum")
    assert set(ev["SUPPORTS"]) == {"find.fever_history", "find.fever", "test.malaria_rdt_hrp2"}
    assert await cg.owning_twins(EP, "Diagnosis", "cond.malaria_falciparum") == ["haematological"]
    assert await cg.owning_twins(EP, "Treatment",
                                 "tx.malaria.uncomplicated.artemether_lumefantrine") \
        == ["immune_lymphatic"]


async def test_absent_finding_refutes():
    cg = ClinicalGraph(NetworkXGraph())
    await cg.differential(EP, "cond.malaria_falciparum", 0.5)
    await cg.finding(EP, "find.fever_history", present=False)
    assert (await cg.evidence(EP, "cond.malaria_falciparum"))["REFUTES"] == ["find.fever_history"]
