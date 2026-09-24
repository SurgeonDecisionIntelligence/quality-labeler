"""Image widget: a grid overview of all slices, or one slice at full resolution.

Quality judgements (noise, fine motion) need real pixels, so the single-slice view
never draws an image below 1:1 — it pans instead — and magnifies with nearest
neighbour so pixel texture stays honest. The grid is an overview: it does scale
tiles down, using area averaging rather than the bilinear sampling a painter
transform would apply, and reports its scale in the status line.
"""

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .dicom_io import Series

GAP = 2
ZOOMS = ("auto", 1.0, 2.0, 4.0)


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
        self.default_single = False  # which view each new series opens in
        self.slice = 0
        self.window = (0.0, 1.0)
        self.zoom_index = 0  # index into ZOOMS
        self.pan = QPointF(0, 0)
        self._images: list[QImage] = []
        self._grid_cache: QPixmap | None = None
        self._tile_rects: list[QRectF] = []
        self._tile_scale = 1.0
        self._window_drag: tuple[QPointF, tuple[float, float]] | None = None
        self._pan_drag: tuple[QPointF, QPointF] | None = None
        self._moved = False
        self.status_text = ""

    # --- state -----------------------------------------------------------
    def set_message(self, message: str):
        self.series, self.message = None, message
        self._images, self._grid_cache = [], None
        self.update()

    def set_series(self, series: Series):
        self.series, self.message = series, series.error or ""
        self.single = self.default_single
        self.slice = len(series.volume) // 2
        self.window = series.window
        self.zoom_index = 0
        self.pan = QPointF(0, 0)
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

    def cycle_zoom(self, step: int = 1):
        self.single = True
        self.zoom_index = (self.zoom_index + step) % len(ZOOMS)
        self._emit_status()
        self.update()

    def reset_window(self):
        if self.series is not None:
            self.window = self.series.window
            self._render_images()

    # --- geometry --------------------------------------------------------
    def _aspect(self) -> float:
        """Displayed height / width of one image pixel."""
        return self.series.pixel_aspect if self.series is not None else 1.0

    def _fit_scale(self) -> float:
        img = self._images[0]
        aspect = self._aspect()
        return min(self.width() / img.width(), self.height() / (img.height() * aspect))

    def _scale(self) -> float:
        """Horizontal pixels per image pixel in the single-slice view."""
        zoom = ZOOMS[self.zoom_index]
        # Never drop below 1:1 on either axis: at that point we pan instead of shrink.
        lossless = max(1.0, 1.0 / self._aspect())
        return max(self._fit_scale(), lossless) if zoom == "auto" else zoom * lossless

    def _single_rect(self) -> QRectF:
        img = self._images[self.slice]
        scale = self._scale()
        w, h = img.width() * scale, img.height() * scale * self._aspect()
        rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        if w > self.width():  # clamp the pan so the image can't be dragged off screen
            self.pan.setX(max(min(self.pan.x(), (w - self.width()) / 2), -(w - self.width()) / 2))
        else:
            self.pan.setX(0)
        if h > self.height():
            self.pan.setY(max(min(self.pan.y(), (h - self.height()) / 2), -(h - self.height()) / 2))
        else:
            self.pan.setY(0)
        return rect.translated(self.pan)

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
            self.status_text = ""
            self.status_changed.emit("")
            return
        lo, hi = self.window
        window = f"W {hi - lo:.0f} L {(hi + lo) / 2:.0f}"
        if self.single:
            scale = self._scale() * min(1.0, self._aspect())
            note = "full resolution" if scale >= 1.0 else "reduced"
            zoom = ZOOMS[self.zoom_index]
            label = "auto" if zoom == "auto" else f"{zoom:g}×"
            where = (
                f"slice {self.slice + 1}/{len(self._images)} · "
                f"{scale * 100:.0f}% ({note}, zoom {label})"
            )
        else:
            pct = self._tile_scale * 100
            where = f"grid of {len(self._images)} slices · tiles at {pct:.0f}% — Tab for full resolution"
        self.status_text = f"{where} · {window}"
        self.status_changed.emit(self.status_text)

    def _build_grid(self):
        dpr = self.devicePixelRatioF()
        pix = QPixmap(self.size() * dpr)
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.black)
        n = len(self._images)
        src = self._images[0]
        aspect = self._aspect()
        cols, tw, th = grid_layout(n, self.width(), self.height(), src.height() / src.width() * aspect)
        rows = math.ceil(n / cols)
        x0 = (self.width() - (cols * tw + GAP * (cols - 1))) / 2
        y0 = (self.height() - (rows * th + GAP * (rows - 1))) / 2
        self._tile_scale = tw / src.width()
        self._tile_rects = []

        p = QPainter(pix)
        p.setPen(QColor(255, 220, 0))
        for i, img in enumerate(self._images):
            r, c = divmod(i, cols)
            rect = QRectF(x0 + c * (tw + GAP), y0 + r * (th + GAP), tw, th)
            self._tile_rects.append(rect)
            # Pre-scale with Qt's smooth filter (area averaging when shrinking) rather
            # than letting the painter point-sample the transform.
            scaled = img.scaled(
                max(1, round(tw * dpr)),
                max(1, round(th * dpr)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
                if self._tile_scale < 1
                else Qt.TransformationMode.FastTransformation,
            )
            p.drawImage(rect, scaled)
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
                self._emit_status()  # tile scale is only known once laid out
            p.drawPixmap(0, 0, self._grid_cache)
            return
        rect = self._single_rect()
        # Magnifying: nearest neighbour, so noise and edges are not smoothed away.
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._scale() < 1)
        p.drawImage(rect, self._images[self.slice])
        p.setPen(QColor(255, 220, 0))
        p.drawText(self.rect().adjusted(6, 4, 0, 0), f"{self.slice + 1}/{len(self._images)}")

    # --- mouse -----------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._window_drag = (event.position(), self.window)
        elif event.button() == Qt.MouseButton.LeftButton and self._images:
            self._moved = False
            if self.single:
                self._pan_drag = (event.position(), QPointF(self.pan))
                return
            for i, rect in enumerate(self._tile_rects):
                if rect.contains(event.position()):
                    self.slice = i
                    self.pan = QPointF(0, 0)
                    self.toggle_mode()
                    return

    def mouseMoveEvent(self, event):
        if not self._images:
            return
        if self._window_drag is not None:
            start, (lo, hi) = self._window_drag
            d = event.position() - start
            width = max((hi - lo) * math.exp(d.x() / 200), 1e-3)
            level = (hi + lo) / 2 - d.y() * (hi - lo) / 300
            self.window = (level - width / 2, level + width / 2)
            self._render_images()
        elif self._pan_drag is not None:
            start, origin = self._pan_drag
            d = event.position() - start
            if d.manhattanLength() > 3:
                self._moved = True
            self.pan = origin + d
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._window_drag = None
        elif event.button() == Qt.MouseButton.LeftButton:
            # A click (rather than a pan) in the single view goes back to the grid.
            if self._pan_drag is not None and not self._moved:
                self.toggle_mode()
            self._pan_drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y() // 120
        if steps:
            self.step_slice(-steps)
