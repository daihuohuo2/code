from PyQt5.QtCore import QObject, QEvent, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget


class ScaleBarOverlay(QWidget):
    NICE_LENGTHS_MM = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(parent_widget.rect())
        self._pixels_per_mm = 100.0
        self._img_width = 0
        self._bar_visible = False
        self.raise_()

    def set_pixels_per_mm(self, value):
        self._pixels_per_mm = max(float(value), 0.001)
        self.update()

    def set_img_width(self, width):
        self._img_width = int(width)
        self.update()

    def set_visible(self, visible):
        self._bar_visible = bool(visible)
        self.update()

    def update_size(self):
        self.setGeometry(self.parentWidget().rect())
        self.update()

    def paintEvent(self, event):
        if not self._bar_visible or self._pixels_per_mm <= 0:
            return
        display_w = self.width()
        display_h = self.height()
        if display_w <= 0 or display_h <= 0:
            return

        scale_factor = display_w / self._img_width if self._img_width > 0 else 1.0
        display_ppmm = self._pixels_per_mm * scale_factor
        target_px = display_w * 0.20
        bar_len_mm = self.NICE_LENGTHS_MM[0]
        bar_len_px = bar_len_mm * display_ppmm
        for length in self.NICE_LENGTHS_MM:
            px = length * display_ppmm
            if px > target_px:
                break
            bar_len_mm = length
            bar_len_px = px
        bar_len_px = max(bar_len_px, 4)

        label = "{:.0f} mm".format(bar_len_mm) if bar_len_mm >= 1.0 and bar_len_mm == int(bar_len_mm) else (
            "{} mm".format(bar_len_mm) if bar_len_mm >= 1.0 else "{:.0f} µm".format(bar_len_mm * 1000)
        )

        margin = 16
        bar_h = 8
        x0 = margin
        y0 = display_h - margin - bar_h - 18
        x1 = x0 + int(bar_len_px)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shadow_pen = QPen(QColor(0, 0, 0, 180))
        shadow_pen.setWidth(3)
        painter.setPen(shadow_pen)
        painter.drawLine(x0, y0 + bar_h, x1, y0 + bar_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRect(x0 - 2, y0 - 2, int(bar_len_px) + 4, bar_h + 4)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRect(x0, y0, int(bar_len_px), bar_h)
        tick_pen = QPen(QColor(255, 255, 255, 230), 2)
        painter.setPen(tick_pen)
        tick_h = bar_h + 4
        painter.drawLine(x0, y0 - 2, x0, y0 + tick_h)
        painter.drawLine(x1, y0 - 2, x1, y0 + tick_h)
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(x0 + 1, y0 - 3, label)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(x0, y0 - 4, label)
        painter.end()


class ResizeFilter(QObject):
    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._overlay.update_size()
        return False
