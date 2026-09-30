import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from quality_labeler.app import LabelerWindow
from quality_labeler.db import LabelStore
from quality_labeler.dicom_io import discover_series


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
    window = LabelerWindow(dataset, discover_series(dataset), store, "alice", expected_weight="T2")
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

    saved = store.get_labels("patient1/ax_t1", "alice")
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
    window = LabelerWindow(dataset, discover_series(dataset), store, "alice", expected_weight=None)
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
        dataset, discover_series(dataset), LabelStore(tmp_path / "l.db"), "bob", expected_weight=None
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
