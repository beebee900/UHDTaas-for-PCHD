import asyncio
import io
from datetime import UTC, datetime, timedelta

import pytest

from atra.backends import Backends, BackendUnavailable
from atra.backends.base import TSPoint
from atra.backends.graph import UnsupportedQuery
from atra.backends.memory import MemoryWorkflows, SqliteRelational
from atra.config import Settings
from atra.contracts import EventEnvelope, ModelRegistryEntry

HDT = "hdt-0123456789ab"
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@pytest.fixture
def backends(tmp_path):
    return Backends(Settings(var_dir=tmp_path), "test", ephemeral=True)


async def test_timeseries_versions_replay_and_aggregates(backends):
    ts = backends.timeseries
    await ts.write(HDT, "8867-4", [TSPoint(T0 + timedelta(seconds=30 * i), 60 + i, "/min")
                                   for i in range(10)])
    first_write = datetime.now(UTC)
    await asyncio.sleep(0.01)
    await ts.write(HDT, "8867-4", [TSPoint(T0, 99, "/min", version=2)])
    raw = await ts.query(HDT, "8867-4")
    assert len(raw) == 10 and raw[0].v == 99
    replay = await ts.query(HDT, "8867-4", as_of=first_write)
    assert replay[0].v == 60
    per_minute = await ts.query(HDT, "8867-4", aggregate="1m")
    assert len(per_minute) == 5
    assert (await ts.latest(HDT, "8867-4")).v == 69
    assert await ts.codes(HDT) == ["8867-4"]


async def test_fhir_search_versions_and_partitions(backends):
    fhir = backends.fhir
    obs = {"resourceType": "Observation", "status": "final",
           "subject": {"reference": f"Patient/{HDT}"},
           "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5"}]},
           "effectiveDateTime": "2026-10-01T08:00:00+00:00", "valueQuantity": {"value": 38.9}}
    created = await fhir.create(obs, partition="fac-a")
    assert created["meta"]["versionId"] == "1"
    await fhir.update({**created, "status": "amended"}, partition="fac-a")
    hits = await fhir.search("Observation", {"subject": HDT, "code": "http://loinc.org|8310-5",
                                             "date": "ge2026-10-01T00:00:00Z"}, partition="fac-a")
    assert [h["status"] for h in hits] == ["amended"]
    assert await fhir.search("Observation", {"subject": HDT}, partition="fac-b") == []
    assert len(await fhir.history("Observation", created["id"], partition="fac-a")) == 2
    await fhir.delete("Observation", created["id"], partition="fac-a")
    with pytest.raises(KeyError):
        await fhir.read("Observation", created["id"], partition="fac-a")
    with pytest.raises(ValueError):
        await fhir.search("Observation", {"unknown": "x"})


async def test_graph_subset(backends):
    g = backends.graph
    await g.run("MERGE (a:Person {id: $id}) SET a += $props", {"id": HDT, "props": {"sex": "F"}})
    await g.run("MERGE (c:Condition {id: $id}) SET c += $p",
                {"id": "61462000", "p": {"name": "Malaria"}})
    await g.run("MATCH (a:Person {id: $a}), (b:Condition {id: $b}) MERGE (a)-[:HAS]->(b)",
                {"a": HDT, "b": "61462000"})
    rows = await g.run("MATCH (a)-[r:HAS]->(b) WHERE a.id = $id RETURN type(r), b.name AS name",
                       {"id": HDT})
    assert rows == [{"type(r)": "HAS", "name": "Malaria"}]
    with pytest.raises(UnsupportedQuery):
        await g.run("MATCH (a) DETACH DELETE a")


async def test_vector_objects_cache(backends):
    v = backends.vector
    await v.ensure_collection("kb", 3)
    await v.upsert("kb", [("doc-1", [1, 0, 0], {"lang": "en"}),
                          ("doc-2", [0, 1, 0], {"lang": "yo"})])
    hits = await v.search("kb", [0.9, 0.1, 0], top_k=1)
    assert hits[0].id == "doc-1"
    assert (await v.search("kb", [0.9, 0.1, 0], where={"lang": "yo"}))[0].id == "doc-2"
    o = backends.objects
    await o.put("notes/a.txt", b"hello")
    assert await o.get("notes/a.txt") == b"hello" and await o.list("notes/") == ["notes/a.txt"]
    with pytest.raises(ValueError):
        await o.put("../escape", b"x")
    c = backends.cache
    await c.set("gw:hdt-1:a", 1, ttl_s=0.01)
    await c.set("gw:hdt-1:b", 2)
    await asyncio.sleep(0.02)
    assert await c.get("gw:hdt-1:a") is None
    assert await c.delete_prefix("gw:hdt-1:") == 1


async def test_events_with_patterns(backends):
    bus, got = backends.events, []

    async def handler(ev):
        got.append(ev.event_type)

    bus.subscribe("alert.*", handler)
    bus.subscribe("episode.opened", handler)
    for t in ("alert.raised", "episode.opened", "task.created"):
        await bus.publish(EventEnvelope(event_id="e", event_type=t, source="apdt",
                                        wall_time=T0, trace_id="t", payload={}))
    await bus.drain()
    assert sorted(got) == ["alert.raised", "episode.opened"]


async def test_workflow_signals_and_replay(tmp_path):
    calls = []

    async def approve(ctx, *, order):
        await ctx.activity(_record, calls, f"prepared {order}")
        decision = await ctx.wait_signal("decision", timeout_s=2)
        await ctx.sleep(0.01)
        return {"order": order, "decision": decision}

    wf = MemoryWorkflows(tmp_path / "wf.sqlite")
    wf.register("approve", approve)
    rid = await wf.start("approve", {"order": "insulin"})
    await asyncio.sleep(0.05)
    assert (await wf.status(rid)).status == "waiting"
    await wf.signal(rid, "decision", "approved")
    assert await wf.result(rid, timeout_s=10) == {"order": "insulin", "decision": "approved"}
    assert calls == ["prepared insulin"]

    crashed = MemoryWorkflows(tmp_path / "wf2.sqlite")
    crashed.register("approve", approve)
    rid2 = await crashed.start("approve", {"order": "cpap"})
    await asyncio.sleep(0.05)
    await crashed.close()
    restarted = MemoryWorkflows(tmp_path / "wf2.sqlite")
    restarted.register("approve", approve)
    assert await restarted.recover() == [rid2]
    await restarted.signal(rid2, "decision", "declined")
    assert (await restarted.result(rid2, timeout_s=10))["decision"] == "declined"
    assert calls.count("prepared cpap") == 1


async def _record(calls, text):
    calls.append(text)
    return text


async def test_memory_database_survives_a_cancelled_statement():
    from sqlalchemy import text

    db = SqliteRelational()
    async with db.engine().begin() as conn:
        await conn.execute(text("CREATE TABLE t (k INTEGER)"))
        await conn.execute(text("INSERT INTO t VALUES (1)"))
    started = asyncio.Event()

    async def writer():
        async with db.engine().begin() as conn:
            for i in range(10**6):
                await conn.execute(text("INSERT INTO t VALUES (:k)"), {"k": i})
                started.set()

    task = asyncio.create_task(writer())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with db.engine().begin() as conn:
        assert (await conn.execute(text("SELECT COUNT(*) FROM t"))).scalar() == 1
    await db.close()


async def test_model_registry_stages(backends):
    reg = backends.models
    entry = ModelRegistryEntry(model_id="ahdt.endocrine.glucose_insulin_minimal", version="1.0.0",
                               twin="endocrine", family="simulation", tier="T2",
                               anatomy="UBERON:0001264", inputs=[], outputs=[],
                               intended_use="research", source="Bergman et al. 1979")
    await reg.register(entry)
    await reg.register(entry.model_copy(update={"version": "1.1.0"}))
    assert (await reg.get(entry.model_id)).version == "1.1.0"
    await reg.transition(entry.model_id, "1.0.0", "Production", by="cso-1")
    assert (await reg.get(entry.model_id)).version == "1.0.0"
    assert len(await reg.list(twin="endocrine", tier="T2")) == 2


async def test_dicom_store(backends):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientID, ds.Modality, ds.StudyDate, ds.StudyTime = HDT, "DX", "20261001", "081500"
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.StudyDescription = "Chest X-ray"
    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds, enforce_file_format=True)
    uids = await backends.imaging.store(buf.getvalue())
    studies = await backends.imaging.search_studies(patient_id=HDT, modality="DX")
    assert studies[0]["study_uid"] == uids["study_uid"] and studies[0]["series_count"] == 1
    assert len(await backends.imaging.retrieve(**uids)) > 0


def test_unavailable_container_backend(tmp_path):
    settings = Settings(var_dir=tmp_path)
    settings.backend.fhir = "hapi"
    with pytest.raises(BackendUnavailable):
        _ = Backends(settings, "test", ephemeral=True).fhir
