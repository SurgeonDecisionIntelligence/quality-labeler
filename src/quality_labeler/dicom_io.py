"""Discover series folders and load them into a sorted volume."""

import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset

from .inference import HeaderInfo


@dataclass
class Series:
    key: str  # path relative to the root; identifies the series in the database
    path: Path
    volume: np.ndarray  # float32, (slices, rows, cols)
    pixel_aspect: float  # displayed height / width of one pixel
    window: tuple[float, float]  # auto window (lo, hi)
    info: HeaderInfo = field(default_factory=HeaderInfo)
    n_files: int = 0
    n_skipped: int = 0
    error: str | None = None


def series_key(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if path != root else "."


def discover_series(root: Path) -> list[Path]:
    """Every directory under root that directly contains files is one series."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if any(not f.startswith(".") for f in filenames):
            found.append(Path(dirpath))
    return sorted(found)


def _str(ds: Dataset, name: str) -> str:
    value = ds.get(name)
    if value is None:
        return ""
    if isinstance(value, pydicom.multival.MultiValue):
        return "\\".join(str(v) for v in value)
    return str(value)


def _float(ds: Dataset, name: str) -> float | None:
    try:
        value = ds.get(name)
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def header_info(ds: Dataset) -> HeaderInfo:
    iop = ds.get("ImageOrientationPatient")
    return HeaderInfo(
        series_uid=_str(ds, "SeriesInstanceUID") or None,
        study_uid=_str(ds, "StudyInstanceUID") or None,
        series_description=_str(ds, "SeriesDescription"),
        protocol_name=_str(ds, "ProtocolName"),
        study_description=_str(ds, "StudyDescription"),
        body_part=_str(ds, "BodyPartExamined"),
        scanning_sequence=_str(ds, "ScanningSequence"),
        sequence_name=_str(ds, "SequenceName"),
        image_type=_str(ds, "ImageType"),
        contrast_agent=_str(ds, "ContrastBolusAgent"),
        echo_time=_float(ds, "EchoTime"),
        repetition_time=_float(ds, "RepetitionTime"),
        inversion_time=_float(ds, "InversionTime"),
        flip_angle=_float(ds, "FlipAngle"),
        field_strength=_float(ds, "MagneticFieldStrength"),
        orientation=tuple(float(v) for v in iop) if iop and len(iop) == 6 else None,
    )


def _sort_key(ds: Dataset, filename: str):
    iop, ipp = ds.get("ImageOrientationPatient"), ds.get("ImagePositionPatient")
    if iop and ipp and len(iop) == 6 and len(ipp) == 3:
        normal = np.cross([float(v) for v in iop[:3]], [float(v) for v in iop[3:]])
        return (0, float(np.dot(normal, [float(v) for v in ipp])), filename)
    instance = ds.get("InstanceNumber")
    if instance is not None:
        return (1, float(instance), filename)
    return (2, 0.0, filename)


def _frames(ds: Dataset) -> np.ndarray:
    arr = ds.pixel_array
    if ds.get("SamplesPerPixel", 1) > 1:  # colour -> grey
        arr = arr.mean(axis=-1)
    if arr.ndim == 2:
        arr = arr[None]
    arr = arr.astype(np.float32)
    slope, intercept = _float(ds, "RescaleSlope"), _float(ds, "RescaleIntercept")
    if slope not in (None, 1.0) or intercept not in (None, 0.0):
        arr = arr * (slope or 1.0) + (intercept or 0.0)
    return arr


def auto_window(volume: np.ndarray) -> tuple[float, float]:
    sample = volume[:, ::4, ::4] if volume.size > 4_000_000 else volume
    lo, hi = np.percentile(sample, (0.5, 99.5))
    if hi <= lo:
        lo, hi = float(volume.min()), float(volume.max()) + 1.0
    return float(lo), float(hi)


def load_series(path: Path, root: Path) -> Series:
    key = series_key(path, root)
    empty = Series(key, path, np.zeros((0, 1, 1), np.float32), 1.0, (0.0, 1.0))
    files = sorted(f for f in path.iterdir() if f.is_file() and not f.name.startswith("."))
    empty.n_files = len(files)

    items = []
    for f in files:
        try:
            ds = pydicom.dcmread(f, force=True)
            if "PixelData" not in ds:
                continue
            items.append((_sort_key(ds, f.name), ds, _frames(ds)))
        except Exception:
            continue
    if not items:
        empty.n_skipped = len(files)
        empty.error = f"No readable DICOM images in {len(files)} files"
        return empty

    # A series should share one image size; drop odd ones out (e.g. a stray localizer).
    shape = Counter(frames.shape[1:] for _, _, frames in items).most_common(1)[0][0]
    kept = sorted((i for i in items if i[2].shape[1:] == shape), key=lambda i: i[0])
    volume = np.concatenate([frames for _, _, frames in kept])

    ds0 = kept[len(kept) // 2][1]
    spacing = ds0.get("PixelSpacing")
    aspect = float(spacing[0]) / float(spacing[1]) if spacing and float(spacing[1]) else 1.0

    return Series(
        key=key,
        path=path,
        volume=volume,
        pixel_aspect=aspect,
        window=auto_window(volume),
        info=header_info(ds0),
        n_files=len(files),
        n_skipped=len(files) - len(kept),
    )
