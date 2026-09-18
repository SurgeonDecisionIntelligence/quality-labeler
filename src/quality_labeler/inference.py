"""Guess plane, region and weighting from DICOM header values.

These only pre-fill defaults; the labeler's choice is what gets recorded as the
label. Guesses are stored alongside so their error rate can be measured.
"""

import re
from dataclasses import dataclass

import numpy as np


@dataclass
class HeaderInfo:
    series_uid: str | None = None
    study_uid: str | None = None
    series_description: str = ""
    protocol_name: str = ""
    study_description: str = ""
    body_part: str = ""
    scanning_sequence: str = ""
    sequence_name: str = ""
    image_type: str = ""
    contrast_agent: str = ""
    echo_time: float | None = None
    repetition_time: float | None = None
    inversion_time: float | None = None
    flip_angle: float | None = None
    field_strength: float | None = None
    orientation: tuple[float, ...] | None = None  # ImageOrientationPatient


@dataclass
class Guess:
    value: str | None
    reason: str


def guess_plane(orientation) -> Guess:
    if orientation is None or len(orientation) != 6:
        return Guess(None, "no ImageOrientationPatient")
    normal = np.cross(orientation[:3], orientation[3:])
    axis = int(np.argmax(np.abs(normal)))
    return Guess(("sagittal", "coronal", "axial")[axis], "ImageOrientationPatient")


_REGION_PATTERNS = (
    ("cervical", re.compile(r"\bC[\s_-]?SPINE|CERVIC")),
    ("thoracic", re.compile(r"\bT[\s_-]?SPINE|THORACIC|DORSAL")),
    ("lumbar", re.compile(r"\bL[\s_-]?SPINE|LUMBAR|\bL[\s_-]?S[\s_-]?SPINE")),
)


def guess_region(info: HeaderInfo) -> Guess:
    for source, text in (
        ("BodyPartExamined", info.body_part),
        ("SeriesDescription", info.series_description),
        ("ProtocolName", info.protocol_name),
        ("StudyDescription", info.study_description),
    ):
        text = text.upper()
        for region, pattern in _REGION_PATTERNS:
            if pattern.search(text):
                return Guess(region, source)
    return Guess(None, "no region keyword")


_CONTRAST = re.compile(r"\+\s?C\b|\bC\+|\bPOST\b|POST[\s_-]?(GAD|GD|CON)|\bGAD|\bGD\b|CONTRAST")


def _weight_from_text(text: str) -> str | None:
    t = text.upper()
    if re.search(r"DWI|DIFF|\bADC\b|TRACE|\bB\d{3,4}\b", t):
        return "DWI"
    if re.search(r"STIR|\bTIRM\b", t):
        return "STIR"
    if re.search(r"T2\s?\*|T2[\s_-]?STAR|MEDIC|MERGE|HEMO", t):
        return "T2*"
    if "FLAIR" in t:
        return "T1" if "T1" in t else "FLAIR"
    if re.search(r"\bPD|PROTON", t):
        return "PD"
    if "T1" in t:
        return "T1"
    if "T2" in t:
        return "T2"
    return None


def _weight_from_physics(info: HeaderInfo) -> tuple[str | None, str]:
    te, tr, ti = info.echo_time, info.repetition_time, info.inversion_time
    if "DIFFUSION" in info.image_type.upper():
        return "DWI", "ImageType DIFFUSION"
    if ti:
        if ti < 300:
            return "STIR", f"TI {ti:g}"
        if ti > 1500:
            return "FLAIR", f"TI {ti:g}"
        return "T1", f"TI {ti:g}"
    if te is None or tr is None:
        return None, "no TE/TR"
    desc = f"TE {te:g}, TR {tr:g}"
    if "GR" in info.scanning_sequence.upper() and te >= 15 and tr < 1000:
        return "T2*", f"gradient echo, {desc}"
    if tr < 1000 and te < 30:
        return "T1", desc
    if tr >= 1500 and te >= 60:
        return "T2", desc
    if tr >= 1500 and te <= 40:
        return "PD", desc
    return None, f"ambiguous {desc}"


def guess_weight(info: HeaderInfo) -> Guess:
    text = " ".join((info.series_description, info.protocol_name, info.sequence_name))
    weight = _weight_from_text(text)
    reason = "description"
    if weight is None:
        weight, reason = _weight_from_physics(info)
    if weight == "T1" and (info.contrast_agent or _CONTRAST.search(text.upper())):
        weight, reason = "T1+C", reason + " + contrast"
    return Guess(weight, reason)
