"""Two-vector comparison on shared, automatically fitted axes.

This widget plots supplied values only; it owns no game or simulation rules.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from core.design_tokens import ColorRole, Size, TypeSize, color, ui_font


class VectorComparison(QWidget):
    def __init__(self, horizontal, vertical, saved_label, current_label, empty_label, parent=None):
        super().__init__(parent)
        self.horizontal, self.vertical = horizontal, vertical
        self.labels = saved_label, current_label
        self.empty_label = empty_label
        self.vectors = (None, None)
        self.setMinimumHeight(Size.TABLE_ROW * 6)
        self.setMinimumWidth(0)
        self.setAccessibleName(f'{horizontal} / {vertical}')

    def set_vectors(self, saved, current):
        self.vectors = tuple(tuple(v) if v is not None and all(math.isfinite(x) for x in v)
                             else None for v in (saved, current))
        self.setAccessibleDescription('; '.join(f'{label}: {vector}'
                                     for label, vector in zip(self.labels, self.vectors)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(ui_font(TypeSize.HINT))
        bounds = QRectF(self.rect()).adjusted(Size.GRID_GAP, Size.GAP_SM, -Size.GRID_GAP, -Size.GAP_SM)
        roles = ColorRole.MUTED_TEXT, ColorRole.ACCENT
        for index, (text, role) in enumerate(zip(self.labels, roles)):
            painter.setPen(QPen(QColor(color(role))))
            rect = QRectF(bounds.left() + index * bounds.width() / 2, bounds.top(), bounds.width() / 2, Size.CONTROL)
            alignment = Qt.AlignmentFlag.AlignLeft if index == 0 else Qt.AlignmentFlag.AlignRight
            painter.drawText(rect, alignment | Qt.AlignmentFlag.AlignVCenter, text)
        plot = bounds.adjusted(Size.GRID_GAP, Size.CONTROL + Size.GAP_SM, -Size.GRID_GAP, -Size.CONTROL)
        centre = plot.center()
        painter.setPen(QPen(QColor(color(ColorRole.BORDER))))
        painter.drawLine(QPointF(plot.left(), centre.y()), QPointF(plot.right(), centre.y()))
        painter.drawLine(QPointF(centre.x(), plot.top()), QPointF(centre.x(), plot.bottom()))
        painter.setPen(QPen(QColor(color(ColorRole.SECONDARY_TEXT))))
        painter.drawText(QRectF(plot.left(), plot.bottom(), plot.width(), Size.CONTROL),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.horizontal)
        painter.drawText(QRectF(plot.left(), plot.top() - Size.CONTROL, plot.width(), Size.CONTROL),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.vertical)
        valid = [v for v in self.vectors if v is not None]
        if not valid:
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self.empty_label)
            return
        extent = max((abs(x) for v in valid for x in v), default=1) or 1
        # Equal physical scale on both axes, so angles are never distorted.
        radius = max(1, min(plot.width(), plot.height()) / 2 - Size.GAP)
        for vector, role, dashed in zip(self.vectors, roles, (True, False)):
            if vector is None:
                continue
            endpoint = centre + QPointF(vector[0] / extent * radius, -vector[1] / extent * radius)
            pen = QPen(QColor(color(role)), Size.ACCENT_LINE)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(centre, endpoint)
            delta = endpoint - centre
            length = math.hypot(delta.x(), delta.y())
            if length > Size.GAP:
                unit = delta / length
                side = QPointF(-unit.y(), unit.x())
                painter.setBrush(QColor(color(role)))
                painter.drawPolygon(QPolygonF([endpoint,
                    endpoint - unit * Size.GAP + side * Size.GAP_SM,
                    endpoint - unit * Size.GAP - side * Size.GAP_SM]))
            else:
                painter.drawEllipse(endpoint, Size.GAP_XS, Size.GAP_XS)
