"""AHDT Layer 3.1 ingestion (design 04, 4.3): the pipeline and its REST import route."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request

from ahdt.ingest.batch import BatchImporter
from ahdt.ingest.pipeline import IngestPipeline
from ahdt.stores.lake import Lake
from ahdt.stores.waveforms import WaveformStore
from atra.backends import Backends
from atra.consent import ConsentRegistry
from atra.gateway import Role
from atra.personas import DEMO_HDT_KEY
from atra.provenance import AuditLog
from atra.security import InvalidToken, bearer
from atra.service import Problem, authenticate, verifier_of

IMPORT_ROLES = frozenset({Role.MEDICAL_OFFICER, Role.NURSE, Role.LAB_SCIENTIST,
                          Role.RADIOLOGIST, Role.PHARMACIST})
OBSERVATION_FORMATS = ("fhir", "hl7v2", "csv")


async def build_pipeline(backends: Backends, consents: ConsentRegistry,
                         audit: AuditLog) -> IngestPipeline:
    if backends.ephemeral:
        lake_dir = Path(tempfile.mkdtemp(prefix="atra-ahdt-lake-"))
    else:
        lake_dir = backends.data_dir / "lake"
    objects: Any = backends.objects
    root = Path(getattr(objects, "root", backends.data_dir / "objects"))
    secret = await backends.secrets.get_secret("hdt_id_key")
    key = secret.encode() if secret else DEMO_HDT_KEY
    pipeline = IngestPipeline(backends, consents, audit, lake=Lake(lake_dir),
                              waveforms=WaveformStore(root), hdt_key=key)
    await pipeline.start()
    return pipeline


async def pipeline_of(app: FastAPI) -> IngestPipeline:
    """The service's pipeline, built on first use and subscribed to `ingest.*`."""
    if getattr(app.state, "ingest", None) is None:
        pipeline = await build_pipeline(app.state.backends, app.state.consents, app.state.audit)
        pipeline.subscribe()
        app.state.ingest = pipeline
    ingest: IngestPipeline = app.state.ingest
    return ingest


def mount_import(app: FastAPI) -> None:
    @app.post("/v1/import", tags=["ingestion"],
              summary="Import a batch: FHIR Bundle, HL7 v2, CSV, DICOM or VCF")
    async def import_batch(request: Request,
                           format: str = Query(pattern="^(fhir|hl7v2|csv|dicom|vcf)$"),
                           hdt_id: str | None = None) -> dict[str, Any]:
        verifier = await verifier_of(app)
        try:
            claims = verifier.verify(bearer(request.headers.get("authorization")))
        except InvalidToken as exc:
            raise Problem(401, "unauthenticated", str(exc)) from exc
        if not claims.is_service:
            ident = await authenticate(request.headers, verifier)
            if ident.ctx.actor_role not in IMPORT_ROLES:
                raise Problem(403, "forbidden", "this role may not import records")
        importer = BatchImporter(await pipeline_of(app))
        body = await request.body()
        try:
            if format in OBSERVATION_FORMATS:
                result = await importer.observations(format, body)
                return {**result.counts(),
                        "rejected_records": [{"record_id": r.record_id, "reason": r.reason}
                                             for r in result.rejected]}
            stored = (await importer.dicom(body) if format == "dicom"
                      else await importer.vcf(body, hdt_id=hdt_id))
        except ValueError as exc:
            raise Problem(422, "invalid-request", str(exc)) from exc
        return {"hdt_id": stored.hdt_id, "key": stored.key, **stored.detail}
