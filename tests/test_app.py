import os
import shutil
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from quality_labeler.app import LabelerWindow
from quality_labeler.db import LabelStore
from quality_labeler.dicom_io import discover_series, scan_identities


def scan(root):
    """The folders under root, each resolved to its SeriesInstanceUID."""
    entries, _ = scan_identities(discover_series(root), root)
    return entries


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def press(window, key, text=""):
    window.handle_key(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))


def wait_loaded(qapp, window):
    for _ in range(400):
        if window.series is not None:
            return
        window._pending.result(timeout=5)
        qapp.processEvents()
        window._check_pending()
    raise AssertionError("series never loaded")


def test_keyboard_labeling_flow(qapp, dataset, tmp_path):
    store = LabelStore(tmp_path / "labels.db")
    window = LabelerWindow(dataset, scan(dataset), store, "alice", expected_weight="T2")
    wait_loaded(qapp, window)
    assert window.series.key == "patient1/ax_t1"
    # Header-derived defaults: axial plane, lumbar from BodyPartExamined; weight from --weight.
    assert window.current_labels().plane == "axial"
    assert window.current_labels().weight == "T2"
    assert "Header weight guess: T1" in window.hints.text()

    press(window, Qt.Key.Key_4)  # quality 4
    press(window, Qt.Key.Key_M)  # motion 1 -> 2
    press(window, Qt.Key.Key_N)  # noise 1 -> 2
    press(window, Qt.Key.Key_N)  # noise 2 -> 3
    press(window, Qt.Key.Key_A)  # misc artifact 1 -> 2
    press(window, Qt.Key.Key_S)  # fat suppression on
    press(window, Qt.Key.Key_W)  # T2 -> PD
    press(window, Qt.Key.Key_Return)
    wait_loaded(qapp, window)
    assert window.series.key == "patient1/sag_t2"

    ax_uid = next(e.uid for e in scan(dataset) if e.key == "patient1/ax_t1")
    saved = store.get_labels(ax_uid, "alice")
    assert (saved.quality, saved.motion, saved.weight) == (4, 2, "PD")
    assert (saved.noise, saved.misc_artifact, saved.hardware) == (3, 2, 1)
    assert saved.fat_suppression is True and saved.improper_acquisition is False

    # Fresh defaults on the next series, then go back and see the saved labels.
    fresh = window.current_labels()
    assert (fresh.quality, fresh.noise, fresh.fat_suppression) == (1, 1, False)
    press(window, Qt.Key.Key_Left)
    wait_loaded(qapp, window)
    assert window.current_labels() == saved

    # Reopening skips what alice already labeled.
    window.close()
    store = LabelStore(tmp_path / "labels.db")
    window = LabelerWindow(dataset, scan(dataset), store, "alice", expected_weight=None)
    wait_loaded(qapp, window)
    assert window.series.key == "patient1/sag_t2"
    window.close()


def test_single_view_never_downsamples(qapp, tmp_path):
    """A slice larger than the viewport is shown 1:1 and panned, not shrunk."""
    import sys

    import numpy as np

    sys.path.insert(0, "tests")
    from conftest import write_series

    from quality_labeler.dicom_io import load_series
    from quality_labeler.viewer import ImageView

    folder = tmp_path / "big"
    write_series(folder, n=4, rows=1024, cols=1024)
    view = ImageView()
    view.resize(500, 400)
    view.set_series(load_series(folder, tmp_path))

    view.step_slice(0)  # switch to the single-slice view
    assert view._fit_scale() < 1.0  # fitting would shrink it to ~39%
    assert view._scale() == 1.0  # ...so we show real pixels instead
    assert "full resolution" in view.status_text

    # A small slice may be magnified to use the screen.
    small = tmp_path / "small"
    write_series(small, n=4, rows=64, cols=64)
    view.set_series(load_series(small, tmp_path))
    view.step_slice(0)
    assert view._scale() > 1.0


def test_grade_cycling_wraps_and_reverses(qapp, dataset, tmp_path):
    window = LabelerWindow(
        dataset, scan(dataset), LabelStore(tmp_path / "l.db"), "bob", expected_weight=None
    )
    wait_loaded(qapp, window)
    for expected in (2, 3, 1, 2):  # 1 -> 2 -> 3 -> wraps to 1
        press(window, Qt.Key.Key_C)
        if expected != window.current_labels().clipping:
            raise AssertionError(f"expected clipping {expected}")
    shift = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
    window.handle_key(shift)
    assert window.current_labels().clipping == 1
    window.close()


def test_identity_survives_the_folder_being_renamed(qapp, dataset, tmp_path):
    """Labels follow the SeriesInstanceUID, not the path."""
    store = LabelStore(tmp_path / "labels.db")
    window = LabelerWindow(dataset, scan(dataset), store, "alice", expected_weight=None)
    wait_loaded(qapp, window)
    first = window.series.key
    window.save_and_next()
    window.close()

    # The data is reorganised on disk: same series, new folder name.
    (dataset / first).rename(dataset / first.split("/")[0] / "renamed")

    store = LabelStore(tmp_path / "labels.db")
    window = LabelerWindow(dataset, scan(dataset), store, "alice", expected_weight=None)
    wait_loaded(qapp, window)
    assert "renamed" not in window.series.key   # the renamed folder is recognised, not re-offered
    assert len(window.labeled) == 1
    window.close()


def test_two_folders_holding_the_same_series_count_once(tmp_path):
    from quality_labeler.dicom_io import deduplicate

    root = tmp_path / "root"
    sys.path.insert(0, "tests")
    from conftest import write_series

    write_series(root / "original" / "s1", n=3)
    shutil.copytree(root / "original" / "s1", root / "a_second_export" / "s1")
    entries, _ = scan_identities(discover_series(root), root)
    unique, duplicates = deduplicate(entries)
    assert len(unique) == 1 and len(duplicates) == 1
    assert unique[0].uid == duplicates[0].uid


def test_folder_without_dicom_falls_back_to_its_path(dataset, tmp_path):
    entries = scan(dataset)
    junk = next(e for e in entries if e.key == "patient2/junk")
    assert junk.uid == "nouid:patient2/junk"
    assert junk.has_uid is False
