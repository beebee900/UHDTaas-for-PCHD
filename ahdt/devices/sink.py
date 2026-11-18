"""The AHDT side of the edge gateway's document uploads (`edge.devices.gateway.Sink`)."""

from __future__ import annotations

import hashlib

from ahdt.ingest.batch import BatchImporter, StoredObject
from ahdt.ingest.pipeline import IngestPipeline, IngestResult

MEDIA_BUCKET = "ahdt-media"
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "audio/wav": ".wav"}


class EdgeSink:
    def __init__(self, pipeline: IngestPipeline) -> None:
        self.importer = BatchImporter(pipeline)

    async def observations(self, fmt: str, body: bytes) -> IngestResult:
        return await self.importer.observations(fmt, body)

    async def dicom(self, body: bytes) -> StoredObject:
        return await self.importer.dicom(body)

    async def vcf(self, body: bytes, *, hdt_id: str) -> StoredObject:
        return await self.importer.vcf(body, hdt_id=hdt_id)

    async def media(self, body: bytes, *, hdt_id: str, content_type: str) -> StoredObject:
        """Phone photos and audio clips, kept for the 6.4 perceive service."""
        ext = EXTENSIONS.get(content_type, ".bin")
        digest = hashlib.sha256(body).hexdigest()[:16]
        key = f"{MEDIA_BUCKET}/{hdt_id}/{digest}{ext}"
        await self.importer.pipeline.backends.objects.put(key, body, content_type=content_type)
        return StoredObject(hdt_id, key, {"content_type": content_type})
