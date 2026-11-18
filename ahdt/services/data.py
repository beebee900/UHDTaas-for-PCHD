"""Layer 6.1 data tools (design 04, 4.7.2): observations, time series, imaging, medications,
genome.

Each handler reads the stores of Layer 3.1: the data lake and time-series store for
measurements, the imaging store for DICOM studies, the FHIR store for medication statements
and the object store for genomic files. `as_of` limits every read to what was ingested by
that time.
"""

from __future__ import annotations

import gzip
import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from ahdt.ingest.batch import GENOMICS_BUCKET
from ahdt.knowledge.documents import PARTITION as FHIR_PARTITION
from ahdt.services.observations import Reading
from ahdt.services.runtime import Runtime
from atra.codes import SYSTEMS
from atra.service import Identity, ToolHandler, meta

AGGREGATE_S = {"1m": 60, "5m": 300, "1h": 3600}
GENOME_SOURCE = "VCF"


def _point(r: Reading) -> dict[str, Any]:
    return {"t": r.effective_time.isoformat(), "v": r.value, "unit": r.unit,
            "quality": r.quality}


def _bucketed(readings: Sequence[Reading], width_s: int) -> list[dict[str, Any]]:
    groups: dict[int, list[Reading]] = defaultdict(list)
    for r in readings:
        if isinstance(r.value, float):
            groups[int(r.effective_time.timestamp()) // width_s].append(r)
    out = []
    for bucket in sorted(groups):
        rows = groups[bucket]
        values = [r.value for r in rows if isinstance(r.value, float)]
        worst = "ok" if all(r.quality == "ok" for r in rows) else "suspect"
        out.append({"t": datetime.fromtimestamp(bucket * width_s, UTC).isoformat(),
                    "v": sum(values) / len(values), "unit": rows[0].unit, "quality": worst})
    return out


def _thin(items: Sequence[Any], limit: int | None) -> list[Any]:
    """At most `limit` evenly spaced items, keeping the first and the last."""
    if limit is None or len(items) <= limit:
        return list(items)
    step = (len(items) - 1) / (limit - 1)
    return [items[round(i * step)] for i in range(limit)]


class DataService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    async def observations(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        reader = await self.rt.reader()
        period = a.period
        rows = reader.read(a.hdt_id, a.codes, start=period.start if period else None,
                           end=period.end if period else None, as_of=a.as_of)
        by_code: dict[str, list[Reading]] = defaultdict(list)
        for r in rows:
            by_code[r.code].append(r)
        series = {}
        for requested in a.codes:
            found = by_code.get(reader.canonical(requested), [])
            if a.aggregate == "raw":
                series[requested] = [_point(r) for r in found if r.value is not None]
            else:
                series[requested] = _bucketed(found, AGGREGATE_S[a.aggregate])
        return {"series": series, "_meta": meta(**({"as_of": a.as_of} if a.as_of else {}))}

    async def timeseries(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        reader = await self.rt.reader()
        rows = [r for r in reader.read(a.hdt_id, [a.code], start=a.period.start,
                                       end=a.period.end, as_of=a.as_of)
                if isinstance(r.value, float)]
        rows = _thin(rows, a.max_points)
        unit = rows[0].unit if rows else (_unit_of(reader.field_name(a.code), self.rt) or "1")
        return {"t": [r.effective_time.isoformat() for r in rows],
                "v": [r.value for r in rows], "unit": unit,
                "_meta": meta(**({"as_of": a.as_of} if a.as_of else {}))}

    async def imaging(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        pipe = await self.rt.pipeline()
        since = a.period.start if a.period else None
        studies = []
        for s in await pipe.backends.imaging.search_studies(
                patient_id=a.hdt_id, modality=a.modality, since=since):
            if not s.get("started"):
                continue
            started = datetime.fromisoformat(s["started"])
            if a.period and started > a.period.end:
                continue
            studies.append({**{k: v for k, v in s.items() if k != "started"},
                            "started": started.isoformat()})
        return {"studies": studies}

    async def medications(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        pipe = await self.rt.pipeline()
        resources = await pipe.backends.fhir.search(
            "MedicationStatement", {"subject": f"Patient/{a.hdt_id}"}, partition=FHIR_PARTITION)
        entries = []
        for resource in resources:
            entry = medication_entry(resource)
            if entry is None or (a.active_only and not _active(resource, a.as_of)):
                continue
            entries.append(entry)
        entries.sort(key=lambda e: e["start"])
        return {"medications": entries}

    async def genome(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        pipe = await self.rt.pipeline()
        wanted = {g.upper() for g in a.genes}
        found: dict[str, dict[str, Any]] = {}
        for key in await pipe.backends.objects.list(f"{GENOMICS_BUCKET}/{a.hdt_id}/"):
            text = gzip.decompress(await pipe.backends.objects.get(key)).decode("utf-8")
            for variant in parse_vcf(text, wanted):
                found.setdefault(f"{variant['gene']}|{variant.get('rsid')}", variant)
        return {"variants": list(found.values())}

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.data.observations": self.observations,
                "ahdt.data.timeseries": self.timeseries, "ahdt.data.imaging": self.imaging,
                "ahdt.data.medications": self.medications, "ahdt.data.genome": self.genome}


def _unit_of(field_name: str | None, rt: Runtime) -> str | None:
    return next((f.ucum for t in rt.registry.twins.values() for f in t.fields
                 if f.name == field_name), None)


def _coding(concept: Mapping[str, Any] | None, system: str) -> str | None:
    for coding in (concept or {}).get("coding", []):
        if coding.get("system") == system:
            return str(coding.get("code")) or None
    return None


def _first_display(concept: Mapping[str, Any] | None) -> str | None:
    if not concept:
        return None
    if concept.get("text"):
        return str(concept["text"])
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return str(coding["display"])
    return None


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _active(resource: Mapping[str, Any], as_of: datetime | None) -> bool:
    if resource.get("status") not in ("active", "intended", "on-hold"):
        return False
    end = _when((resource.get("effectivePeriod") or {}).get("end"))
    return end is None or end > (as_of or datetime.now(UTC))


def medication_entry(resource: Mapping[str, Any]) -> dict[str, Any] | None:
    """A FHIR R4 MedicationStatement as a `MedicationEntry`; None without an ATC code, a
    start time or a dosage text."""
    concept = resource.get("medicationCodeableConcept")
    atc = _coding(concept, SYSTEMS["atc"])
    period = resource.get("effectivePeriod") or {}
    start = _when(period.get("start") or resource.get("effectiveDateTime"))
    dosage = (resource.get("dosage") or [{}])[0]
    if atc is None or start is None or not dosage.get("text"):
        return None
    timing = (dosage.get("timing") or {}).get("code")
    end = _when(period.get("end"))
    return {"atc": atc, "rxnorm": _coding(concept, SYSTEMS["rxnorm"]),
            "display": _first_display(concept) or atc, "dose": str(dosage["text"]),
            "route": _first_display(dosage.get("route")) or "unspecified",
            "frequency": _first_display(timing) or "unspecified",
            "start": start.isoformat(), "end": end.isoformat() if end else None}


def parse_vcf(text: str, genes: set[str]) -> list[dict[str, Any]]:
    """Variants of `genes` in a VCF whose caller wrote `GENE` (HGNC symbol) and, where a
    star-allele call exists, `STAR` (diplotype) and `PHENOTYPE` into INFO."""
    out = []
    samples_at = 9
    for line in io.StringIO(text):
        if line.startswith("#") or not line.strip():
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) <= samples_at:
            continue
        info = dict(kv.split("=", 1) for kv in cols[7].split(";") if "=" in kv)
        gene = info.get("GENE", "").upper()
        if gene not in genes:
            continue
        alleles = [cols[3], *cols[4].split(",")]
        gt = cols[samples_at].split(":")[cols[8].split(":").index("GT")]
        genotype = "/".join(alleles[int(i)] if i.isdigit() else "." for i in
                            gt.replace("|", "/").split("/"))
        out.append({
            "gene": gene, "star_allele": info.get("STAR"),
            "rsid": cols[2] if cols[2].startswith("rs") else None, "genotype": genotype,
            "phenotype": info.get("PHENOTYPE", "not called").replace("_", " "),
            "source": GENOME_SOURCE})
    return out
