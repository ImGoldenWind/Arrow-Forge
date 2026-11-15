"""Value diagrams for Stage Info; these do not simulate the game's renderer."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QSizePolicy

from core.design_tokens import TypeSize, ui_font
from core.themes import P
from core.translations import ui_text


class ScalarBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setMinimumWidth(0)
        self.value = self.original = 0.0
        self.setToolTip(ui_text('stage_bar_hint'))
        self.setAccessibleName(ui_text('stage_value_diagram'))

    def set_values(self, value, original):
        self.value, self.original = value, original
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1, self.width() - 2)
        p.fillRect(QRectF(1, 6, width, 6), QColor(P['bg_card']))
        if self.value is None or not math.isfinite(self.original):
            return
        scale = max(1., abs(self.value), abs(self.original))
        center = self.width() / 2
        x = center + self.value / scale * (width / 2 - 2)
        p.fillRect(QRectF(min(center, x), 6, max(2, abs(x - center)), 6), QColor(P['accent']))
        p.setPen(QPen(QColor(P['text_dim']), 1))
        p.drawLine(QPointF(center, 4), QPointF(center, 14))
        x = center + self.original / scale * (width / 2 - 2)
        p.setPen(QPen(QColor(P['text_main']), 2))
        p.drawLine(QPointF(x, 3), QPointF(x, 15))


class VectorPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setFixedHeight(156)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.values = (0., 0., 0.)
        self.setAccessibleName(ui_text('stage_vector_diagram'))

    def set_values(self, values):
        self.values = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(ui_font(TypeSize.BODY))
        origin = QPointF(self.width() / 2, 88)
        axes = ((1., .3), (0., -1.), (-.65, .45))
        length = min(64, self.width() / 4)
        p.setPen(QPen(QColor(P['border']), 1))
        for (dx, dy), label in zip(axes, 'XYZ'):
            end = origin + QPointF(dx * length, dy * length)
            p.drawLine(origin - QPointF(dx * length, dy * length), end)
            p.setPen(QColor(P['text_sec']))
            p.drawText(end + QPointF(4, 0), label)
            p.setPen(QPen(QColor(P['border']), 1))
        if all(v is not None for v in self.values):
            scale = max(1., *(abs(v) for v in self.values))
            x = sum(v / scale * a[0] for v, a in zip(self.values, axes))
            y = sum(v / scale * a[1] for v, a in zip(self.values, axes))
            end = origin + QPointF(x * length * .65, y * length * .65)
            p.setPen(QPen(QColor(P['accent']), 3))
            p.drawLine(origin, end)
            p.setBrush(QColor(P['accent']))
            p.drawEllipse(end, 4, 4)
        p.setPen(QColor(P['text_dim']))
        p.drawText(QRectF(0, 132, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   ui_text('stage_vector_diagram'))
