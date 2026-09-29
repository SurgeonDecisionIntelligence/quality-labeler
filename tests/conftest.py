import random
from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

SAGITTAL = [0, 1, 0, 0, 0, -1]
AXIAL = [1, 0, 0, 0, 1, 0]


def write_series(
    folder: Path,
    n: int = 8,
    rows: int = 32,
    cols: int = 24,
    orientation=SAGITTAL,
    description: str = "SAG T2 TSE",
    te: float = 100.0,
    tr: float = 3500.0,
    thickness: float = 4.0,
    slice_gap: float = 0.0,
    acquired=None,
    shuffle: bool = True,
) -> list[float]:
    """Write n slices whose pixel value encodes the slice's spatial order; return positions."""
    folder.mkdir(parents=True, exist_ok=True)
    series_uid, study_uid = generate_uid(), generate_uid()
    normal = np.cross(orientation[:3], orientation[3:])
    order = list(range(n))
    if shuffle:
        random.Random(0).shuffle(order)  # instance numbers / filenames disagree with position
    for file_idx, pos in enumerate(order):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID = MRImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.SeriesInstanceUID, ds.StudyInstanceUID = series_uid, study_uid
        ds.Modality = "MR"
        ds.SeriesDescription = description
        ds.BodyPartExamined = "LSPINE"
        ds.EchoTime, ds.RepetitionTime = te, tr
        ds.InstanceNumber = file_idx + 1
        ds.ImageOrientationPatient = orientation
        ds.ImagePositionPatient = [float(v) for v in normal * pos * (thickness + slice_gap)]
        ds.PixelSpacing = [0.5, 0.5]
        ds.SliceThickness = thickness
        ds.SpacingBetweenSlices = thickness + slice_gap
        if acquired:
            ds.AcquisitionMatrix = [acquired[0], 0, 0, acquired[1]]
        ds.Rows, ds.Columns = rows, cols
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.PixelRepresentation = 0
        ds.PixelData = np.full((rows, cols), pos * 10, np.uint16).tobytes()
        ds.save_as(folder / f"IM{file_idx:04d}.dcm", enforce_file_format=True)
    spacing = thickness + slice_gap
    return sorted(float(np.dot(normal, normal * p * spacing)) for p in range(n))


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "root"
    write_series(root / "patient1" / "sag_t2")
    write_series(root / "patient1" / "ax_t1", orientation=AXIAL, description="AX T1", te=10, tr=500)
    (root / "patient2" / "junk").mkdir(parents=True)
    (root / "patient2" / "junk" / "notes.txt").write_text("not dicom")
    return root
