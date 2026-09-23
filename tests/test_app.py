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

    press(window, Qt.Key.Key_3)  # reject
    press(window, Qt.Key.Key_M)  # motion
    press(window, Qt.Key.Key_N)  # noise none -> some
    press(window, Qt.Key.Key_N)  # some -> noisy
    press(window, Qt.Key.Key_A)  # misc artifact
    press(window, Qt.Key.Key_W)  # T2 -> PD
    press(window, Qt.Key.Key_Return)
    wait_loaded(qapp, window)
    assert window.series.key == "patient1/sag_t2"

    saved = store.get_labels("patient1/ax_t1", "alice")
    assert (saved.quality, saved.motion, saved.weight) == ("reject", True, "PD")
    assert (saved.noise, saved.misc_artifact, saved.hardware) == ("noisy", True, False)

    # Fresh defaults on the next series, then go back and see the saved labels.
    assert (window.current_labels().quality, window.current_labels().noise) == ("accept", "none")
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
