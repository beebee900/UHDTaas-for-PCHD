"""Clinical device simulators: lab analyser (HL7 v2.5 ORU^R01), ECG machine (WFDB record),
imaging modality (DICOM over STOW-RS), sequencer (VCF 4.2) and the records export (an
OpenMRS-style FHIR R4 Bundle).

The ORU^R01 subset is the one `ahdt.ingest.batch.from_hl7v2` reads: MSH, PID-3 with the
assigning authority in component 4, OBR-7 observation time, and OBX-2 value type, OBX-3
coded as `code^text^LN`, OBX-5 value, OBX-6 unit, OBX-11 status and OBX-14 time.

Genotype sites (GRCh38, NCBI dbSNP refSNP API, read 2026-10-10): rs334 at chr11:5227002 T>A
(HBB, HbS) and rs4244285 at chr10:94781859 G>A (CYP2C19*2).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from edge.devices.decode import wfdb
from edge.devices.sim.base import Simulator, seed_of
from edge.devices.sim.mqtt import ecg_trace

HL7_TIME = "%Y%m%d%H%M"
SITES = {"HBB": ("11", 5227002, "rs334", "T", "A"),
         "CYP2C19": ("10", 94781859, "rs4244285", "G", "A")}
"""Gene -> (chromosome, position, id, ref, alt) of the genotyped site."""
OPENMRS_ID = "https://openmrs.org/identifier/openmrs-id"


def _hl7(t: datetime) -> str:
    return t.strftime(HL7_TIME)


@dataclass
class LabAnalyser(Simulator):
    """One ORU^R01 per panel in `documents["labs"]`: `{name, time_s, results: [{loinc,
    text, value, unit}]}`. `patient` replaces PID-3 (identifier, authority) for a patient the
    facility knows by another identifier."""

    patient: tuple[str, str] | None = None

    def messages(self) -> str:
        out = []
        pid = (f"{self.patient[0]}^^^{self.patient[1]}^PI" if self.patient
               else f"{self.hdt_id}^^^ATRA^PI")
        for n, panel in enumerate(self.stream.documents.get("labs", [])):
            when = _hl7(self.stream.when(panel["time_s"]))
            control = f"{self.device_id}-{seed_of(self.hdt_id, str(n)) % 10**8:08d}"
            seg = [f"MSH|^~\\&|{self.device_id}|LAB|ATRA|AHDT|{when}||ORU^R01|{control}|P|2.5",
                   f"PID|1||{pid}", f"OBR|1|||{panel['name']}|||{when}"]
            for i, r in enumerate(panel["results"], 1):
                value = round(r["value"] + float(self.rng.normal(0, self.noise.get(
                    r["loinc"], 0.0))), r.get("digits", 2))
                seg.append(f"OBX|{i}|NM|{r['loinc']}^{r['text']}^LN||{value}|{r['unit']}"
                           f"|||||F|||{when}")
            out.append("\r".join(seg))
        return "\r".join(out) + "\r"


@dataclass
class EcgMachine(Simulator):
    """A 10 s resting record with leads II and V5 in format 16 at the WFDB default gain."""

    fs: float = 500.0
    seconds: float = 10.0

    def record(self, t_s: float) -> tuple[str, bytes]:
        hr = self.stream.at("heart_rate", t_s)
        ii = ecg_trace(hr, self.seconds, self.fs)
        adc = np.round(np.stack([ii, 0.8 * ii], axis=1) * wfdb.DEFGAIN).astype(np.int16)
        name = f"{self.device_id}-{int(t_s)}"
        signals = tuple(
            wfdb.Signal(f"{name}.dat", 16, wfdb.DEFGAIN, 0, "mV", 16, 0, int(adc[0, i]),
                        wfdb.checksum(adc[:, i]), 0, lead)
            for i, lead in enumerate(("II", "V5")))
        start = self.stream.when(t_s).replace(tzinfo=None)
        header = wfdb.Header(name, self.fs, adc.shape[0], signals, start)
        return header.text(), wfdb.write_format16(adc)


@dataclass
class ImagingModality(Simulator):
    """Sends DICOM Part 10 instances as one STOW-RS request body."""

    def stow(self, instances: Sequence[bytes]) -> tuple[bytes, str]:
        boundary = uuid.UUID(int=seed_of(self.device_id, self.hdt_id) >> 64 << 64).hex
        body = b""
        for data in instances:
            body += (f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode()
                     + data + b"\r\n")
        body += f"--{boundary}--\r\n".encode()
        content_type = f'multipart/related; type="application/dicom"; boundary={boundary}'
        return body, content_type


@dataclass
class Sequencer(Simulator):
    """`documents["genotypes"]` maps a gene of `SITES` to its alt-allele count (0, 1, 2)."""

    def vcf(self, when: datetime) -> bytes:
        lines = ["##fileformat=VCFv4.2", f"##fileDate={when:%Y%m%d}",
                 f"##source={self.device_id}", "##reference=GRCh38",
                 '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                 f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{self.hdt_id}"]
        genotypes: Mapping[str, int] = self.stream.documents.get("genotypes", {})
        for gene, (chrom, pos, rsid, ref, alt) in SITES.items():
            gt = {0: "0/0", 1: "0/1", 2: "1/1"}[genotypes.get(gene, 0)]
            lines.append(f"chr{chrom}\t{pos}\t{rsid}\t{ref}\t{alt}\t.\tPASS\t.\tGT\t{gt}")
        return ("\n".join(lines) + "\n").encode()


@dataclass
class RecordsExport(Simulator):
    """An OpenMRS FHIR export: the Patient and the lab Observations of `documents["labs"]`."""

    def bundle(self) -> bytes:
        entries: list[dict[str, Any]] = [{"resource": {
            "resourceType": "Patient", "id": self.hdt_id,
            "identifier": [{"system": OPENMRS_ID, "value": self.hdt_id}]}}]
        for n, panel in enumerate(self.stream.documents.get("labs", [])):
            for i, r in enumerate(panel["results"]):
                entries.append({"resource": {
                    "resourceType": "Observation", "id": f"{self.device_id}-{n}-{i}",
                    "status": "final", "subject": {"reference": f"Patient/{self.hdt_id}"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": r["loinc"],
                                         "display": r["text"]}]},
                    "valueQuantity": {"value": r["value"], "unit": r["unit"],
                                      "system": "http://unitsofmeasure.org",
                                      "code": r["unit"]},
                    "effectiveDateTime": self.stream.when(panel["time_s"]).isoformat()}})
        return json.dumps({"resourceType": "Bundle", "type": "collection",
                           "entry": entries}).encode()
