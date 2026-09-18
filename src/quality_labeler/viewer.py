"""Image widget: all slices as a grid, or one slice at a time."""

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .dicom_io import Series

GAP = 2


def grid_layout(n: int, width: float, height: float, aspect: float) -> tuple[int, float, float]:
    """Choose the column count that makes n tiles (height/width = aspect) largest."""
    best = (1, 0.0, 0.0)
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        tile_w = min((width - GAP * (cols - 1)) / cols, (height - GAP * (rows - 1)) / rows / aspect)
        if tile_w > best[1]:
            best = (cols, tile_w, tile_w * aspect)
    return best


class ImageView(QWidget):
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.series: Series | None = None
        self.message = ""
        self.single = False
        self.slice = 0
        self.window = (0.0, 1.0)
        self._images: list[QImage] = []
        self._grid_cache: QPixmap | None = None
        self._tile_rects: list[QRectF] = []
        self._drag: tuple[QPointF, tuple[float, float]] | None = None

    # --- state -----------------------------------------------------------
    def set_message(self, message: str):
        self.series, self.message = None, message
        self._images, self._grid_cache = [], None
        self.update()

    def set_series(self, series: Series):
        self.series, self.message = series, series.error or ""
        self.single = False
        self.slice = len(series.volume) // 2
        self.window = series.window
        self._render_images()

    def toggle_mode(self):
        self.single = not self.single
        self._emit_status()
        self.update()

    def show_grid(self):
        if self.single:
            self.toggle_mode()

    def step_slice(self, delta: int):
        if not self._images:
            return
        self.single = True
        self.slice = max(0, min(len(self._images) - 1, self.slice + delta))
        self._emit_status()
        self.update()

    def reset_window(self):
        if self.series is not None:
            self.window = self.series.window
            self._render_images()

    # --- rendering -------------------------------------------------------
    def _render_images(self):
        vol = self.series.volume if self.series is not None else None
        self._images, self._grid_cache = [], None
        if vol is not None and len(vol):
            lo, hi = self.window
            u8 = np.clip((vol - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8)
            h, w = u8.shape[1:]
            self._images = [
                QImage(np.ascontiguousarray(s).data, w, h, w, QImage.Format.Format_Grayscale8).copy()
                for s in u8
            ]
        self._emit_status()
        self.update()

    def _emit_status(self):
        if not self._images:
            self.status_changed.emit("")
            return
        lo, hi = self.window
        where = f"slice {self.slice + 1}/{len(self._images)}" if self.single else "grid"
        self.status_changed.emit(f"{where} · W {hi - lo:.0f} L {(hi + lo) / 2:.0f}")

    def _aspect(self) -> float:
        img = self._images[0]
        return img.height() / img.width() * self.series.pixel_aspect

    def _build_grid(self):
        pix = QPixmap(self.size() * self.devicePixelRatioF())
        pix.setDevicePixelRatio(self.devicePixelRatioF())
        pix.fill(Qt.GlobalColor.black)
        n = len(self._images)
        cols, tw, th = grid_layout(n, self.width(), self.height(), self._aspect())
        rows = math.ceil(n / cols)
        x0 = (self.width() - (cols * tw + GAP * (cols - 1))) / 2
        y0 = (self.height() - (rows * th + GAP * (rows - 1))) / 2
        self._tile_rects = []
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(QColor(255, 220, 0))
        for i, img in enumerate(self._images):
            r, c = divmod(i, cols)
            rect = QRectF(x0 + c * (tw + GAP), y0 + r * (th + GAP), tw, th)
            self._tile_rects.append(rect)
            p.drawImage(rect, img)
            if tw > 40:
                p.drawText(rect.adjusted(3, 1, 0, 0), str(i + 1))
        p.end()
        self._grid_cache = pix

    def resizeEvent(self, event):
        self._grid_cache = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._images:
            p.setPen(QColor(220, 220, 220))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        if not self.single:
            if self._grid_cache is None:
                self._build_grid()
            p.drawPixmap(0, 0, self._grid_cache)
            return
        img = self._images[self.slice]
        aspect = self._aspect()
        w = min(self.width(), self.height() / aspect)
        h = w * aspect
        rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(rect, img)
        p.setPen(QColor(255, 220, 0))
        p.drawText(rect.adjusted(6, 4, 0, 0), f"{self.slice + 1}/{len(self._images)}")

    # --- mouse -----------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = (event.position(), self.window)
        elif event.button() == Qt.MouseButton.LeftButton and self._images:
            if self.single:
                self.toggle_mode()
                return
            for i, rect in enumerate(self._tile_rects):
                if rect.contains(event.position()):
                    self.slice = i
                    self.toggle_mode()
                    return

    def mouseMoveEvent(self, event):
        if self._drag is None or not self._images:
            return
        start, (lo, hi) = self._drag
        d = event.position() - start
        width = max((hi - lo) * math.exp(d.x() / 200), 1e-3)
        level = (hi + lo) / 2 - d.y() * (hi - lo) / 300
        self.window = (level - width / 2, level + width / 2)
        self._render_images()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y() // 120
        if steps:
            self.step_slice(-steps)
