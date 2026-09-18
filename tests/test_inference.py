import pytest

from quality_labeler.inference import HeaderInfo, guess_plane, guess_region, guess_weight


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
    ],
)
def test_region(info, region):
    assert guess_region(info).value == region
