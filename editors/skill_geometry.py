"""A proportion diagram for verified box half extents, independent of game state."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget
from core.translations import ui_text


class SkillBoxDiagram(QWidget):
    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.values = values
        self.setMinimumHeight(142)
        self.setMinimumWidth(0)
        self.setToolTip(ui_text('skill_box_hint'))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#17202b'))
        x, z, y = self.values()
        painter.setPen(QColor('#cbd5e1'))
        painter.drawText(QRectF(10, 5, self.width() - 20, 24), ui_text('skill_box_title'))
        # Fixed reference labels plus uniform scaling: never imply a world pose.
        maximum = max(abs(x), abs(y), abs(z), 1)
        scale = min((self.width() - 70) / 4, 37) / maximum
        cx, cy = self.width() / 2, 78
        painter.setPen(QPen(QColor('#526171'), 1))
        painter.drawLine(20, int(cy), self.width() - 20, int(cy))
        painter.drawLine(int(cx), 34, int(cx), 117)
        painter.setPen(QPen(QColor('#5bbef5'), 2))
        painter.setBrush(QColor(91, 190, 245, 35))
        painter.drawRect(QRectF(cx - abs(x) * scale, cy - abs(y) * scale,
                                abs(x) * scale * 2, abs(y) * scale * 2))
        painter.setPen(QColor('#cbd5e1'))
        painter.drawText(QRectF(10, 116, self.width() - 20, 23),
                         Qt.AlignmentFlag.AlignCenter,
                         ui_text('skill_box_dimensions', x=x * 2, y=y * 2, z=z * 2))
