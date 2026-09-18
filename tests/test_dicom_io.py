import numpy as np

from quality_labeler.dicom_io import discover_series, load_series


def test_discover_finds_every_folder_with_files(dataset):
    keys = [p.relative_to(dataset).as_posix() for p in discover_series(dataset)]
    assert keys == ["patient1/ax_t1", "patient1/sag_t2", "patient2/junk"]


def test_slices_sorted_by_position_not_filename(dataset):
    s = load_series(dataset / "patient1" / "sag_t2", dataset)
    assert s.error is None
    assert s.key == "patient1/sag_t2"
    assert s.volume.shape == (8, 32, 24)
    np.testing.assert_array_equal(s.volume[:, 0, 0], np.arange(8) * 10)
    assert s.info.series_description == "SAG T2 TSE"
    assert s.info.echo_time == 100.0


def test_non_dicom_folder_reports_error(dataset):
    s = load_series(dataset / "patient2" / "junk", dataset)
    assert len(s.volume) == 0
    assert "No readable DICOM" in s.error
