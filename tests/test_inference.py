import pytest

from quality_labeler.inference import (
    HeaderInfo,
    effective_spacing,
    guess_plane,
    guess_region,
    guess_weight,
    is_interpolated,
    resolution_summary,
)


@pytest.mark.parametrize(
    "iop, plane",
    [
        ((0, 1, 0, 0, 0, -1), "sagittal"),
        ((1, 0, 0, 0, 0, -1), "coronal"),
        ((1, 0, 0, 0, 1, 0), "axial"),
        ((0.99, 0.1, 0, -0.1, 0.99, 0.05), "axial"),  # slightly oblique
    ],
)
def test_plane(iop, plane):
    assert guess_plane(iop).value == plane


def test_plane_missing():
    assert guess_plane(None).value is None


@pytest.mark.parametrize(
    "info, weight",
    [
        (HeaderInfo(series_description="SAG T2 TSE"), "T2"),
        (HeaderInfo(series_description="SAG T1 FLAIR"), "T1"),
        (HeaderInfo(series_description="AX T2 FLAIR"), "FLAIR"),
        (HeaderInfo(series_description="SAG STIR"), "STIR"),
        (HeaderInfo(series_description="SAG T1 POST GAD"), "T1+C"),
        (HeaderInfo(series_description="SAG T1", contrast_agent="Gadavist"), "T1+C"),
        (HeaderInfo(series_description="AX T2*"), "T2*"),
        (HeaderInfo(series_description="DWI b800"), "DWI"),
        (HeaderInfo(series_description="SAG PD FS"), "PD"),
        # No description: fall back to sequence timing.
        (HeaderInfo(echo_time=10, repetition_time=500), "T1"),
        (HeaderInfo(echo_time=110, repetition_time=4000), "T2"),
        (HeaderInfo(echo_time=30, repetition_time=3000), "PD"),
        (HeaderInfo(echo_time=40, repetition_time=4000, inversion_time=150), "STIR"),
        (HeaderInfo(echo_time=100, repetition_time=9000, inversion_time=2500), "FLAIR"),
        (HeaderInfo(), None),
    ],
)
def test_weight(info, weight):
    assert guess_weight(info).value == weight


@pytest.mark.parametrize(
    "info, region",
    [
        (HeaderInfo(body_part="CSPINE"), "cervical"),
        (HeaderInfo(series_description="T-SPINE SAG T2"), "thoracic"),
        (HeaderInfo(study_description="MRI LUMBAR SPINE"), "lumbar"),
        (HeaderInfo(series_description="SAG T2"), None),  # "T2" must not read as thoracic
        # Anything recognisably outside the spine defaults to "other".
        (HeaderInfo(body_part="BRAIN"), "other"),
        (HeaderInfo(body_part="HIP"), "other"),
        (HeaderInfo(body_part="PELVIS"), "other"),
        (HeaderInfo(body_part="KNEE"), "other"),
        (HeaderInfo(study_description="MRI ABDOMEN"), "other"),
        (HeaderInfo(body_part="SACRUM"), "other"),
        # A spine match in the same field still wins.
        (HeaderInfo(series_description="L-SPINE AND PELVIS"), "lumbar"),
        (HeaderInfo(body_part="CSPINE", series_description="NECK COIL"), "cervical"),
    ],
)
def test_region(info, region):
    assert guess_region(info).value == region


def test_non_spine_guess_says_why():
    assert guess_region(HeaderInfo(body_part="BRAIN")).reason == "BodyPartExamined, non-spine"


@pytest.mark.parametrize(
    "info, expected",
    [
        (
            HeaderInfo(rows=640, columns=640, acquired=(320, 256), pixel_spacing=(0.55, 0.55),
                       slice_thickness=4.0, slice_spacing=4.4),
            "1.4 × 1.1 mm effective (0.55 mm grid) · 4 mm thick, 0.4 gap"
            " · acquired 256×320 → 640×640 (interpolated)",
        ),
        (
            HeaderInfo(rows=512, columns=512, acquired=(512, 512), pixel_spacing=(0.5, 0.5),
                       slice_thickness=3.0, slice_spacing=3.0),
            "0.5 mm · 3 mm thick · matrix 512×512",
        ),
        (
            HeaderInfo(rows=256, columns=256, pixel_spacing=(0.9, 0.9),
                       slice_thickness=4.0, slice_spacing=3.6),
            "0.9 mm · 4 mm thick, 0.4 overlap · matrix 256×256",
        ),
        (HeaderInfo(), "no geometry in header"),
    ],
)
def test_resolution_summary(info, expected):
    assert resolution_summary(info) == expected


def test_interpolation_detected_from_image_type():
    assert is_interpolated(HeaderInfo(image_type="ORIGINAL\\PRIMARY\\M\\INTERPOLATED"))
    assert not is_interpolated(HeaderInfo(rows=256, columns=256, acquired=(256, 256)))


def test_effective_spacing_of_a_zero_filled_series():
    """416 read x 224 phase reconstructed onto a 512 grid: the grid overstates detail."""
    info = HeaderInfo(rows=512, columns=512, acquired=(224, 416), pixel_spacing=(0.4297, 0.4297))
    col_mm, row_mm = effective_spacing(info)
    assert col_mm == pytest.approx(0.529, abs=0.001)  # read direction
    assert row_mm == pytest.approx(0.982, abs=0.001)  # phase direction, ~2x coarser
    assert "0.53 × 0.98 mm effective (0.43 mm grid)" in resolution_summary(info)


def test_effective_spacing_needs_both_matrices():
    assert effective_spacing(HeaderInfo(rows=512, columns=512, pixel_spacing=(0.4, 0.4))) is None
