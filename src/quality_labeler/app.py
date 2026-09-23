"""Main labeling window. Keyboard-first: a clean series is a single Enter press."""

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .db import LabelStore
from .dicom_io import Series, series_key
from .inference import guess_plane, guess_region, guess_weight
from .prefetch import Prefetcher
from .schema import FLAGS, NOISE, PLANES, QUALITY, REGIONS, WEIGHTS, Labels
from .viewer import ImageView

NO_FOCUS = Qt.FocusPolicy.NoFocus
K = Qt.Key

HELP = """<b>Enter/Space</b> save &amp; next<br>
<b>1 2 3</b> accept / partially accept / reject<br>
<b>N</b> cycle noise: none / some / noisy<br>
<b>M F C H A I</b> toggle findings<br>
<b>R P W</b> cycle region / plane / weight (Shift = back)<br>
<b>T</b> or <b>/</b> type notes (Esc leaves)<br>
<b>D</b> reset labels to defaults<br>
<b>← / Backspace</b> previous series<br>
<b>→ / S</b> skip without saving<br>
<b>Tab / G</b> grid ↔ single slice<br>
<b>↑ ↓</b> or wheel: change slice · click tile: open it<br>
<b>Right-drag</b> window/level · <b>L</b> reset window"""


class LabelerWindow(QMainWindow):
    def __init__(
        self,
        root: Path,
        paths: list[Path],
        store: LabelStore,
        labeler: str,
        expected_weight: str | None,
        relabel: bool = False,
    ):
        super().__init__()
        self.root, self.paths, self.store = root, paths, store
        self.labeler, self.expected_weight = labeler, expected_weight
        self.keys = [series_key(p, root) for p in paths]
        self.labeled = store.labeled_keys(labeler) & set(self.keys)
        self.relabel = relabel
        self.prefetcher = Prefetcher(paths, root)
        self.index = -1
        self.series: Series | None = None
        self.defaults = Labels()
        self.shown_at = 0.0
        self._pending = None
        self._poll = QTimer(self, interval=25, timeout=self._check_pending)

        self.setWindowTitle(f"Quality labeler — {root}  [{labeler}]")
        self._build_ui()
        QApplication.instance().installEventFilter(self)

        start = self._next_index(-1)
        if start is None:
            self.view.set_message("Every series under this root is already labeled by " + labeler)
        else:
            self.go_to(start)

    # --- layout ----------------------------------------------------------
    def _build_ui(self):
        self.view = ImageView()
        self.info = QLabel(wordWrap=True, textInteractionFlags=Qt.TextInteractionFlag.TextSelectableByMouse)
        self.view_status = QLabel()
        self.view.status_changed.connect(self.view_status.setText)
        left = QVBoxLayout()
        left.addWidget(self.info)
        left.addWidget(self.view, 1)
        left.addWidget(self.view_status)

        panel = QVBoxLayout()

        self.radios: dict[str, dict[str, QRadioButton]] = {}
        panel.addWidget(self._radio_row("Quality", "quality", QUALITY, per_option_keys=True))
        panel.addWidget(self._radio_row("Noise [N]", "noise", NOISE))

        flag_box = QGroupBox("Findings")
        flay = QVBoxLayout(flag_box)
        self.flag_boxes = {}
        for f in FLAGS:
            cb = QCheckBox(f"{f.label} [{f.key}]", focusPolicy=NO_FOCUS)
            self.flag_boxes[f.name] = cb
            flay.addWidget(cb)
        panel.addWidget(flag_box)

        form_box = QGroupBox("Series")
        form = QFormLayout(form_box)
        self.combos = {}
        for name, options, key in (
            ("region", REGIONS, "R"),
            ("plane", PLANES, "P"),
            ("weight", WEIGHTS, "W"),
        ):
            combo = QComboBox(focusPolicy=NO_FOCUS)
            combo.addItems(options)
            combo.currentTextChanged.connect(self._update_hints)
            self.combos[name] = combo
            form.addRow(f"{name.capitalize()} [{key}]", combo)
        self.notes = QLineEdit(placeholderText="Notes — press T to type, Esc to leave")
        self.notes.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        form.addRow("Notes [T]", self.notes)
        panel.addWidget(form_box)

        self.hints = QLabel(wordWrap=True, textFormat=Qt.TextFormat.RichText)
        panel.addWidget(self.hints)

        save = QPushButton("Save && next  [Enter]", focusPolicy=NO_FOCUS)
        save.clicked.connect(self.save_and_next)
        panel.addWidget(save)
        nav = QHBoxLayout()
        for text, slot in (("← Previous", self.go_previous), ("Skip →", self.skip)):
            b = QPushButton(text, focusPolicy=NO_FOCUS)
            b.clicked.connect(slot)
            nav.addWidget(b)
        panel.addLayout(nav)

        panel.addStretch(1)
        panel.addWidget(QLabel(HELP, wordWrap=True, textFormat=Qt.TextFormat.RichText))

        side = QWidget()
        side.setLayout(panel)
        side.setFixedWidth(340)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addLayout(left, 1)
        lay.addWidget(side)
        self.setCentralWidget(central)

    def _radio_row(self, title: str, name: str, options, per_option_keys: bool = False) -> QGroupBox:
        box = QGroupBox(title)
        lay = QHBoxLayout(box)
        group = QButtonGroup(box)
        self.radios[name] = {}
        for i, option in enumerate(options):
            text = f"{option} [{i + 1}]" if per_option_keys else option
            b = QRadioButton(text, focusPolicy=NO_FOCUS)
            group.addButton(b)
            self.radios[name][option] = b
            lay.addWidget(b)
        return box

    # --- labels <-> widgets ----------------------------------------------
    def set_labels(self, labels: Labels):
        for name, buttons in self.radios.items():
            buttons[getattr(labels, name)].setChecked(True)
        for name, cb in self.flag_boxes.items():
            cb.setChecked(getattr(labels, name))
        for name, combo in self.combos.items():
            combo.setCurrentText(getattr(labels, name))
        self.notes.setText(labels.notes)
        self._update_hints()

    def current_labels(self) -> Labels:
        return Labels(
            **{
                name: next(v for v, b in buttons.items() if b.isChecked())
                for name, buttons in self.radios.items()
            },
            **{name: cb.isChecked() for name, cb in self.flag_boxes.items()},
            **{name: combo.currentText() for name, combo in self.combos.items()},
            notes=self.notes.text().strip(),
        )

    def _cycle(self, name: str, step: int):
        if name in self.combos:
            combo = self.combos[name]
            combo.setCurrentIndex((combo.currentIndex() + step) % combo.count())
            return
        buttons = list(self.radios[name].values())
        current = next(i for i, b in enumerate(buttons) if b.isChecked())
        buttons[(current + step) % len(buttons)].setChecked(True)

    # --- navigation ------------------------------------------------------
    def _is_done(self, i: int) -> bool:
        return not self.relabel and self.keys[i] in self.labeled

    def _upcoming(self, i: int) -> list[int]:
        return [j for j in range(i + 1, min(len(self.paths), i + 50)) if not self._is_done(j)]

    def _next_index(self, i: int) -> int | None:
        for j in range(i + 1, len(self.paths)):
            if not self._is_done(j):
                return j
        return None

    def go_to(self, index: int):
        self.index = index
        self.series = None
        future = self.prefetcher.get(index)
        self.prefetcher.prime(index, self._upcoming(index))
        if future.done():
            self._display(future)
        else:
            self.view.set_message("Loading…")
            self._pending = future
            self._poll.start()

    def _check_pending(self):
        if self._pending is not None and self._pending.done():
            self._poll.stop()
            future, self._pending = self._pending, None
            self._display(future)

    def _display(self, future):
        try:
            series = future.result()
        except Exception as e:  # e.g. folder vanished or is unreadable
            path = self.paths[self.index]
            series = Series(self.keys[self.index], path, np.zeros((0, 1, 1), np.float32), 1.0, (0, 1))
            series.error = f"Failed to load: {e}"
        self.series = series
        self.view.set_series(series)

        info = series.info
        self.guesses = {
            "plane": guess_plane(info.orientation),
            "region": guess_region(info),
            "weight": guess_weight(info),
        }
        self.defaults = Labels(
            region=self.guesses["region"].value or "lumbar",
            plane=self.guesses["plane"].value or "sagittal",
            weight=self.expected_weight or self.guesses["weight"].value or "other",
        )
        saved = self.store.get_labels(series.key, self.labeler)
        self.set_labels(saved or self.defaults)

        shape = f"{series.volume.shape[2]}×{series.volume.shape[1]}" if len(series.volume) else "-"
        parts = [
            f"<b>[{self.index + 1}/{len(self.paths)}]</b> {series.key}",
            info.series_description or "<i>no description</i>",
            f"{len(series.volume)} slices · {shape}",
        ]
        if series.n_skipped:
            parts.append(f"<span style='color:#d80'>{series.n_skipped} files not used</span>")
        if saved:
            parts.append("<span style='color:#2a2'>✓ already labeled (editing)</span>")
        self.info.setText(" · ".join(parts))
        self._update_status()
        self.shown_at = time.monotonic()

    def _update_hints(self, *_):
        if self.series is None:
            self.hints.setText("")
            return
        info, g = self.series.info, self.guesses

        def fmt(v):
            return "–" if v is None else f"{v:g}"

        weight = self.combos["weight"].currentText()
        guess_w = g["weight"].value
        warn = guess_w is not None and guess_w != weight
        lines = [
            f"TE {fmt(info.echo_time)} · TR {fmt(info.repetition_time)} · "
            f"TI {fmt(info.inversion_time)} · FA {fmt(info.flip_angle)} · B0 {fmt(info.field_strength)}",
            f"Seq: {info.scanning_sequence or '–'} {info.sequence_name}",
            f"Protocol: {info.protocol_name or '–'}",
            ("<span style='color:#e70'><b>" if warn else "")
            + f"Header weight guess: {guess_w or '?'} ({g['weight'].reason})"
            + ("</b></span>" if warn else ""),
            f"Plane guess: {g['plane'].value or '?'} · Region guess: {g['region'].value or '?'}"
            f" ({g['region'].reason})",
        ]
        if self.expected_weight:
            lines.append(f"Expected weight (runtime): {self.expected_weight}")
        self.hints.setText("<br>".join(lines))

    def _update_status(self):
        self.statusBar().showMessage(
            f"{len(self.labeled)} / {len(self.paths)} series labeled by {self.labeler}"
        )

    def save_and_next(self):
        if self.series is None:
            self.statusBar().showMessage("Still loading — not saved", 2000)
            return
        s = self.series
        self.store.upsert_series(
            s.key,
            self.root,
            s.info,
            num_slices=len(s.volume),
            num_files=s.n_files,
            load_error=s.error,
            guesses={
                "guess_plane": self.guesses["plane"].value,
                "guess_region": self.guesses["region"].value,
                "guess_weight": self.guesses["weight"].value,
                "guess_weight_reason": self.guesses["weight"].reason,
            },
        )
        self.store.save_labels(
            s.key,
            self.labeler,
            self.current_labels(),
            expected_weight=self.expected_weight,
            seconds_spent=round(time.monotonic() - self.shown_at, 2),
        )
        self.labeled.add(s.key)
        self.notes.clearFocus()
        nxt = self._next_index(self.index)
        if nxt is None:
            nxt = self._next_index(-1)  # anything skipped earlier?
        if nxt is None:
            self.series = None
            self.view.set_message("All series labeled. 🎉")
            self._update_status()
        else:
            self.go_to(nxt)

    def skip(self):
        nxt = self._next_index(self.index)
        if nxt is None:
            self.statusBar().showMessage("No more unlabeled series after this one", 2000)
        else:
            self.go_to(nxt)

    def go_previous(self):
        if self.index > 0:
            self.go_to(self.index - 1)

    # --- keyboard --------------------------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or not self.isActiveWindow():
            return False
        if QApplication.activePopupWidget() is not None:
            return False
        return self.handle_key(event)

    def handle_key(self, e: QKeyEvent) -> bool:
        key, shift = e.key(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False

        if self.notes.hasFocus():
            if key in (K.Key_Return, K.Key_Enter):
                if not e.isAutoRepeat():
                    self.save_and_next()
                return True
            if key == K.Key_Escape:
                self.notes.clearFocus()
                return True
            return False

        # Navigation keys ignore auto-repeat so holding Enter can't blast through series.
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            if not e.isAutoRepeat():
                self.save_and_next()
        elif key in (K.Key_Left, K.Key_Backspace):
            if not e.isAutoRepeat():
                self.go_previous()
        elif key in (K.Key_Right, K.Key_S):
            if not e.isAutoRepeat():
                self.skip()
        elif K.Key_1 <= key < K.Key_1 + len(QUALITY):
            self.radios["quality"][QUALITY[key - K.Key_1]].setChecked(True)
        elif key == K.Key_N:
            self._cycle("noise", -1 if shift else 1)
        elif key == K.Key_R:
            self._cycle("region", -1 if shift else 1)
        elif key == K.Key_P:
            self._cycle("plane", -1 if shift else 1)
        elif key == K.Key_W:
            self._cycle("weight", -1 if shift else 1)
        elif key in (K.Key_T, K.Key_Slash):
            self.notes.setFocus()
        elif key == K.Key_D:
            self.set_labels(self.defaults)
        elif key in (K.Key_Tab, K.Key_G):
            self.view.toggle_mode()
        elif key == K.Key_Escape:
            self.view.show_grid()
        elif key in (K.Key_Up, K.Key_PageUp):
            self.view.step_slice(-1)
        elif key in (K.Key_Down, K.Key_PageDown):
            self.view.step_slice(1)
        elif key == K.Key_L:
            self.view.reset_window()
        else:
            for f in FLAGS:
                if key == getattr(K, f"Key_{f.key}"):
                    cb = self.flag_boxes[f.name]
                    cb.setChecked(not cb.isChecked())
                    return True
            return False
        return True

    def closeEvent(self, event):
        self.prefetcher.shutdown()
        self.store.close()
        super().closeEvent(event)
