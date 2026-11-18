"""Valid arguments for every AHDT tool, for persona A.O., and the records they read."""

from datetime import UTC, datetime, timedelta

from ahdt.ingest.batch import BatchImporter
from ahdt.ingest.harmonise import RawObservation
from atra.contracts import Code, StateArgs
from atra.personas import BY_KEY

HDT = BY_KEY["ao"].hdt_id
PERIOD = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-03T00:00:00Z"}
SCENARIO = {"kind": "drug", "drug": {"atc": "P01BF01", "dose_mg": 80, "route": "oral",
                                     "schedule_h": [0, 8, 24, 36, 48, 60]},
            "dts": ["renal_urinary", "hepatobiliary", "whole_body"]}

TOOL_ARGS = {
    "ahdt.data.observations": {"codes": ["8310-5", "8867-4"], "period": PERIOD},
    "ahdt.data.imaging": {"modality": "DX"},
    "ahdt.data.medications": {"active_only": True},
    "ahdt.data.genome": {"genes": ["CYP2B6"]},
    "ahdt.data.graph_query": {"question": "Which conditions are recorded?"},
    "ahdt.data.timeseries": {"code": "8310-5", "period": PERIOD, "max_points": 50},
    "ahdt.data.documents": {"query": "previous malaria treatment"},
    "ahdt.data.knowledge": {"query_id": "person.conditions", "params": {}},
    "ahdt.data.cohort_extract": {"cohort_def": {"condition": "61462000"}, "fields": ["age_band"],
                                 "privacy": {"k": 5}},
    "ahdt.model.state": {"dt": "cardiovascular"},
    "ahdt.model.forecast": {"dt": "immune_lymphatic", "variable": "temperature", "horizon_h": 24},
    "ahdt.model.simulate": {"dt": "renal_urinary", "scenario": SCENARIO},
    "ahdt.model.facet": {"anatomy": "UBERON:0001264", "facet": "endocrine"},
    "ahdt.model.cosimulate": {"scenario": SCENARIO, "dts": ["renal_urinary", "hepatobiliary"],
                              "horizon_h": 72, "step_s": 600},
    "ahdt.model.calibrate": {"dt": "endocrine",
                             "model_id": "ahdt.endocrine.glucose_insulin_and_metabolic_regulation"},
    "ahdt.xai.explain": {"output_id": "@state"},
    "ahdt.xai.causal_graph": {"output_id": "@state"},
    "ahdt.cognitive.converse": {"utterance": "Báwo ni ara mi?", "language": "yo"},
    "ahdt.cognitive.perceive": {"modality": "text", "text": "fever for two days"},
    "ahdt.cognitive.reason": {"kind": "ontology",
                              "query": "Is fever a phenotypic abnormality?"},
    "ahdt.cognitive.request_data": {"what": ["8310-5"], "from": "person"},
}

# A role that may call each tool (design 03, 3.6.3).
CALLER = {name: "medical_officer" for name in TOOL_ARGS}
CALLER["ahdt.data.cohort_extract"] = "public_health_official"
CALLER["ahdt.model.calibrate"] = "administrator"


T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
VCF = (b"##fileformat=VCFv4.2\n"
       b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tAO\n"
       b"19\t41515263\trs3745274\tG\tT\t.\tPASS\tGENE=CYP2B6;STAR=*1/*6;"
       b"PHENOTYPE=intermediate_metaboliser\tGT\t0/1\n")


def _obs(i, code, value, unit, when):
    return RawObservation(record_id=f"seed-{code}-{i}", code=Code(system=LOINC, code=code),
                          value=value, unit=unit, effective_time=when, hdt_id=HDT)


async def seed(app):
    """Observations, a medication, a condition and a VCF for A.O."""
    runtime = app.state.runtime
    pipe = await runtime.pipeline()
    raws = []
    for i in range(36):
        when = T0 + timedelta(hours=i)
        raws.append(_obs(i, "8310-5", 38.6 - 0.03 * i + 0.2 * (i % 3), "Cel", when))
        raws.append(_obs(i, "8867-4", 104.0 - 0.3 * i + (i % 4), "/min", when))
        if i % 4 == 0:
            raws.append(_obs(i, "15074-8", 100.0 + (i % 8) * 3, "mg/dL", when))
        if i % 6 == 0:
            raws.append(_obs(i, "8480-6", 118.0 - (i % 12), "mm[Hg]", when))
            raws.append(_obs(i, "8462-4", 76.0 - (i % 12) / 2, "mm[Hg]", when))
    result = await pipe.process(raws)
    assert result.counts()["rejected"] == 0, result.rejected
    fhir = pipe.backends.fhir
    await fhir.create({
        "resourceType": "MedicationStatement", "id": "ms-al", "status": "active",
        "subject": {"reference": f"Patient/{HDT}"},
        "medicationCodeableConcept": {"coding": [{"system": ATC, "code": "P01BF01",
                                                  "display": "artemether and lumefantrine"}]},
        "effectivePeriod": {"start": (T0 + timedelta(hours=2)).isoformat()},
        "dosage": [{"text": "80/480 mg", "route": {"coding": [{"display": "oral"}]},
                    "timing": {"code": {"text": "twice daily"}}}]}, partition="ahdt")
    await fhir.create({
        "resourceType": "Condition", "id": "cond-malaria",
        "subject": {"reference": f"Patient/{HDT}"},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "61462000",
                             "display": "Malaria"}]},
        "onsetDateTime": T0.isoformat()}, partition="ahdt")
    await BatchImporter(pipe).vcf(VCF, hdt_id=HDT)


async def output_id(app):
    """The id of a cardiovascular state estimate of A.O., computed once per app."""
    if not hasattr(app.state, "output_id"):
        out = await app.state.services.model.state(StateArgs(hdt_id=HDT, dt="cardiovascular"),
                                                   None)
        app.state.output_id = out["output_id"]
    return app.state.output_id


async def bound(app, tool):
    """The arguments of `tool` with the `@state` placeholder replaced by a real output id."""
    return {k: (await output_id(app) if v == "@state" else v)
            for k, v in TOOL_ARGS[tool].items()}
