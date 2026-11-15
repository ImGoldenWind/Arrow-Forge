"""Two supplied angles on the same scale; no camera/gameplay semantics."""
import math
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget
from core.design_tokens import ColorRole, Size, TypeSize, color, ui_font


class AngleComparison(QWidget):
    def __init__(self, original_label, current_label, empty_label, parent=None):
        super().__init__(parent)
        self.labels = original_label, current_label
        self.empty_label = empty_label
        self.angles = (None, None)
        self.setMinimumHeight(Size.TABLE_ROW * 6)
        self.setMinimumWidth(0)

    def set_angles(self, original, current):
        self.angles = original, current
        self.setAccessibleDescription('; '.join(f'{name}: {value}' for name, value in zip(self.labels, self.angles)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(ui_font(TypeSize.BODY))
        bounds = QRectF(self.rect()).adjusted(Size.GRID_GAP, Size.GAP, -Size.GRID_GAP, -Size.GAP)
        centre = QPointF(bounds.center().x(), bounds.bottom() - Size.CONTROL)
        radius = max(1, min(bounds.width() / 2, bounds.height() - Size.CONTROL * 3))
        roles = ColorRole.MUTED_TEXT, ColorRole.ACCENT
        for index, (label, angle, role) in enumerate(zip(self.labels, self.angles, roles)):
            painter.setPen(QPen(QColor(color(role))))
            text = label + (f': {angle:.6g}\u00b0' if angle is not None and math.isfinite(angle) else '')
            painter.drawText(QRectF(bounds.left(), bounds.top() + index * Size.CONTROL,
                                   bounds.width(), Size.CONTROL), Qt.AlignmentFlag.AlignLeft, text)
            if angle is None or not math.isfinite(angle) or not 0 < angle < 180:
                continue
            pen = QPen(QColor(color(role)), Size.ACCENT_LINE)
            if index == 0:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            path = QPainterPath(centre)
            half = math.radians(angle / 2)
            left = centre + QPointF(-math.sin(half), -math.cos(half)) * radius
            right = centre + QPointF(math.sin(half), -math.cos(half)) * radius
            path.lineTo(left)
            painter.drawPath(path)
            painter.drawLine(centre, right)
            arc = QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2)
            painter.drawArc(arc, round((90 - angle / 2) * 16), round(angle * 16))
        if any(a is None or not math.isfinite(a) or not 0 < a < 180 for a in self.angles):
            painter.setPen(QPen(QColor(color(ColorRole.SECONDARY_TEXT))))
            painter.drawText(QRectF(bounds.left(), bounds.bottom() - Size.CONTROL,
                                   bounds.width(), Size.CONTROL), Qt.AlignmentFlag.AlignCenter, self.empty_label)
