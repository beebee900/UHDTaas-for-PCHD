import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ahdt.ingest import build_pipeline
from ahdt.ingest.batch import BatchImporter, from_csv, from_fhir_bundle, from_hl7v2
from ahdt.ingest.fields import field_index
from ahdt.ingest.harmonise import RawObservation
from ahdt.ingest.validate import twin_schema
from ahdt.stores import tables
from atra.backends import Backends
from atra.config import Settings
from atra.connectors import DTKind
from atra.consent import demo_registry
from atra.contracts import Code, Waveform
from atra.personas import BY_KEY
from atra.provenance import AuditLog

HDT = BY_KEY["ao"].hdt_id
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
LOINC = "http://loinc.org"


def obs(rid, code, value, unit, t=T0, **kw):
    kw.setdefault("hdt_id", HDT)
    return RawObservation(record_id=rid, code=Code(system=LOINC, code=code), value=value,
                          unit=unit, effective_time=t, **kw)


@pytest.fixture
async def pipe(tmp_path):
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    yield pipeline
    await backends.close()


async def rejected_rows(pipe):
    async with pipe.backends.relational.engine().begin() as conn:
        return {r.record_id: r.reason for r in await conn.execute(select(tables.rejected))}


def test_schema_is_generated_per_twin():
    schema = twin_schema(DTKind.CARDIOVASCULAR, field_index())
    assert schema.name == "ahdt.cardiovascular"
    assert "sbp" in schema.columns["field"].checks[0].statistics["allowed_values"]


async def test_accepted_record_is_harmonised_and_routed(pipe):
    result = await pipe.process([obs("g1", "15074-8", 90.0, "mg/dL", source="manual"),
                                 obs("t1", "8310-5", 38.4, "Cel")])
    assert result.counts() == {"accepted": 2, "duplicates": 0, "rejected": 0, "dropped": 0}
    glucose = result.accepted[0]
    assert glucose.dt is DTKind.ENDOCRINE and glucose.unit == "mmol/L"
    assert glucose.value == pytest.approx(90.0 / 18.0156, rel=1e-3)
    assert glucose.consent_tag == "care+public_health+self_management"
    point = await pipe.backends.timeseries.latest(HDT, "15074-8")
    assert point.v == pytest.approx(glucose.value)
    fhir = await pipe.backends.fhir.search("Observation", {"code": "8310-5"}, partition="ahdt")
    assert fhir[0]["subject"]["reference"] == f"Patient/{HDT}"
    assert not await pipe.backends.fhir.search("Observation", {"code": "15074-8"},
                                               partition="ahdt")
    events = [e for e in pipe.backends.events.published
              if e.event_type == "observation.ingested"]
    assert {e.payload["record_id"] for e in events} == {"g1", "t1"}
    assert len(pipe.lake.arrow("observations")) == 2


async def test_rejected_records_are_kept_with_reasons(pipe):
    result = await pipe.process([
        obs("bad-range", "8310-5", 55.0, "Cel"),
        obs("bad-unit", "8310-5", 38.0, "mm[Hg]"),
        obs("bad-code", "0000-0", 1.0, "1"),
        obs("s1", "8480-6", 70.0, "mm[Hg]"), obs("d1", "8462-4", 90.0, "mm[Hg]"),
        obs("ok", "8310-5", 37.0, "Cel")])
    assert [a.record_id for a in result.accepted] == ["ok"]
    reasons = await rejected_rows(pipe)
    assert "plausibility" in reasons["bad-range"]
    assert "does not convert" in reasons["bad-unit"]
    assert "no twin field" in reasons["bad-code"]
    assert reasons["s1"] == reasons["d1"] == "fails consistency rule sbp_above_dbp"


async def test_rate_rule_rejects_sensor_jumps(pipe):
    await pipe.process([obs("w1", "29463-7", 70.0, "kg")])
    result = await pipe.process([obs("w2", "29463-7", 80.0, "kg", t=T0 + timedelta(hours=2)),
                                 obs("w3", "29463-7", 80.0, "kg", t=T0 + timedelta(days=3))])
    assert [a.record_id for a in result.accepted] == ["w3"]
    assert (await rejected_rows(pipe))["w2"] == "fails rate rule max_rate_of_change_weight"


async def test_records_without_consent_are_dropped_and_audited(pipe):
    result = await pipe.process([obs("x", "8310-5", 37.0, "Cel", hdt_id="hdt-000000000000")])
    assert result.dropped == ["x"] and not result.accepted
    audit = pipe.audit.query(action="ingest.drop")
    assert audit[0].reason == "no consent for care" and audit[0].outcome == "denied"
    assert await pipe.backends.timeseries.latest("hdt-000000000000", "8310-5") is None


async def test_direct_identifiers_are_pseudonymised(pipe):
    pipe.consents.set(await pipe.pseudonyms.hdt_id("NIN", "12345678901"),
                      pipe.consents.get(HDT))
    result = await pipe.process([obs("p1", "8310-5", 37.2, "Cel", hdt_id=None,
                                     identifier=("NIN", "12345678901"))])
    record = result.accepted[0]
    assert record.hdt_id.startswith("hdt-") and "12345678901" not in record.model_dump_json()
    assert record.hdt_id == await pipe.pseudonyms.hdt_id("NIN", "12345678901")


async def test_duplicates_are_skipped_and_new_versions_kept(pipe):
    await pipe.process([obs("v", "8310-5", 37.0, "Cel")])
    again = await pipe.process([obs("v", "8310-5", 37.0, "Cel"),
                                obs("v", "8310-5", 37.4, "Cel", version=2)])
    assert again.duplicates == ["v"] and len(again.accepted) == 1
    assert (await pipe.backends.timeseries.latest(HDT, "8310-5")).v == 37.4


async def test_replay_rebuilds_state_from_the_lake(pipe):
    await pipe.process([obs("a", "8310-5", 37.0, "Cel"), obs("b", "8867-4", 80, "/min")])
    cut = datetime.now(UTC)
    await pipe.process([obs("a", "8310-5", 39.0, "Cel", version=2),
                        obs("c", "8867-4", 95, "/min", t=T0 + timedelta(minutes=5))])
    for as_of in (cut, datetime.now(UTC)):
        lake = pipe.lake.state_at(HDT, as_of)
        for code in ("8310-5", "8867-4"):
            recorded = (await pipe.backends.timeseries.query(HDT, code, as_of=as_of))[-1]
            assert lake[code]["value_num"] == pytest.approx(float(recorded.v))
            assert lake[code]["version"] == recorded.version
    assert pipe.lake.state_at(HDT, cut)["8310-5"]["value_num"] == 37.0


async def test_waveforms_go_to_zarr(pipe):
    raw = RawObservation(record_id="ecg", hdt_id=HDT,
                         code=Code(system="urn:iso:std:iso:11073:10101",
                                   code="MDC_ECG_ELEC_POTL_II"),
                         value=Waveform(array=[0.1, 0.4, 1.2, 0.3], period_ms=4.0), unit="mV",
                         effective_time=T0)
    result = await pipe.process([raw])
    assert result.accepted[0].dt is DTKind.CARDIOVASCULAR
    segments = pipe.waveforms.read(HDT, "MDC_ECG_ELEC_POTL_II", T0)
    assert segments[0].start == T0 and list(segments[0].samples) == [0.1, 0.4, 1.2, 0.3]


async def test_bus_topics_feed_the_pipeline(pipe):
    from atra.contracts import EventEnvelope

    pipe.subscribe()
    await pipe.backends.events.publish(EventEnvelope(
        event_id="e1", event_type="ingest.immune_lymphatic", source="edge", hdt_id=HDT,
        wall_time=T0, trace_id="t", payload={"observations": [{
            "record_id": "bus-1", "hdt_id": HDT, "code": {"system": LOINC, "code": "8310-5"},
            "value": 37.8, "unit": "Cel", "effective_time": T0.isoformat()}]}))
    await pipe.backends.events.drain()
    assert (await pipe.backends.timeseries.latest(HDT, "8310-5")).v == 37.8


HL7 = ("MSH|^~\\&|LAB|LUTH|ATRA|AHDT|202610010800||ORU^R01|MSG1|P|2.5\r"
       "PID|1||NIN-555^^^NIMC^NI||Doe^Jane\r"
       "OBR|1|||24323-8^CMP^LN|||202610010755\r"
       "OBX|1|NM|2823-3^Potassium^LN||4.1|mmol/L|3.5-5.1|N|||F|||202610010750\r"
       "OBX|2|NM|14682-9^Creatinine^LN||1.1|mg/dL|||||F")


def test_hl7v2_batch_maps_obx_results():
    raws = from_hl7v2(HL7)
    assert [r.code.code for r in raws] == ["2823-3", "14682-9"]
    assert raws[0].identifier == ("NIMC", "NIN-555")
    assert raws[1].effective_time == datetime(2026, 10, 1, 7, 55, tzinfo=UTC)


def test_fhir_bundle_and_csv_map_to_raw_observations():
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"resource": {"resourceType": "Patient", "id": "p1",
                      "identifier": [{"system": "urn:openmrs", "value": "OM-1"}]}},
        {"resource": {"resourceType": "Observation", "id": "o1", "status": "final",
                      "subject": {"reference": "Patient/p1"},
                      "code": {"coding": [{"system": LOINC, "code": "8310-5"}]},
                      "effectiveDateTime": "2026-10-01T08:00:00+00:00",
                      "valueQuantity": {"value": 37.5, "code": "Cel"}}}]}
    raw = from_fhir_bundle(bundle)[0]
    assert raw.identifier == ("urn:openmrs", "OM-1") and raw.value == 37.5
    csv_raw = from_csv("record_id,hdt_id,code_system,code,value,unit,effective_time\n"
                       f"c1,{HDT},loinc,8310-5,37.1,Cel,2026-10-01T08:00:00\n")[0]
    assert csv_raw.code.system == LOINC and csv_raw.effective_time.tzinfo is not None


async def test_batch_import_runs_the_pipeline_and_stores_files(pipe):
    importer = BatchImporter(pipe)
    nin = await pipe.pseudonyms.hdt_id("NIMC", "NIN-555")
    pipe.consents.set(nin, pipe.consents.get(HDT))
    result = await importer.observations("hl7v2", HL7.encode())
    assert len(result.accepted) == 2
    assert result.accepted[1].value == pytest.approx(97.24, rel=1e-3)
    vcf = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    stored = await importer.vcf(vcf, hdt_id=HDT)
    assert stored.key.startswith(f"ahdt-genomics/{HDT}/")
    assert gzip.decompress(await pipe.backends.objects.get(stored.key)) == vcf
    with pytest.raises(ValueError):
        await importer.vcf(b"not a vcf", hdt_id=HDT)
    assert json.dumps(result.counts())
