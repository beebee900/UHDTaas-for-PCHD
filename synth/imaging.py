"""Imaging studies: a public image wrapped as DICOM for a person (design 06, 6.4.1).

The pixel data comes from the approved chest X-ray sample set (`evaluation/datasets`);
until it is downloaded no imaging study is generated. The wrapper sets the person's
`hdt_id` as PatientID and carries the source image's label in the study description.
"""

from __future__ import annotations

import io
from datetime import datetime

import numpy as np
import numpy.typing as npt
import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

CR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1"


def wrap(pixels: npt.NDArray[np.uint8], *, hdt_id: str, label: str, when: datetime,
         source: str) -> bytes:
    """An 8-bit greyscale image as a Computed Radiography DICOM instance."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CR_SOP_CLASS
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = pydicom.Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = CR_SOP_CLASS, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.PatientID = ds.PatientName = hdt_id
    ds.Modality, ds.BodyPartExamined = "CR", "CHEST"
    ds.StudyDate = when.strftime("%Y%m%d")
    ds.StudyDescription = f"Synthetic study ({label})"
    ds.ImageComments = f"source image: {source}"
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit, ds.PixelRepresentation = 7, 0
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()
