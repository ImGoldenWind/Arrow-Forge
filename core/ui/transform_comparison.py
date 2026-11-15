"""Interactive comparison of supplied 2D transforms, without game semantics.

Positions share equal axis units, Y points down. Basis glyphs compare rotation
and relative scale; their length is diagram geometry, never model dimensions.
Dragging only changes the current position. Fit stays fixed during a gesture.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.design_tokens import ColorRole, Size, TypeSize, color, ui_font


class TransformComparison(QWidget):
    positionEdited = pyqtSignal(float, float)

    def __init__(self, original_label, current_label, parent=None):
        super().__init__(parent)
        self.labels = original_label, current_label
        self.transforms = (None, None)
        self._extent = 1.
        self._drag = None
        self._drag_offset = QPointF()
        self.setMinimumHeight(Size.TABLE_ROW * 8)
        self.setMinimumWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def set_transforms(self, original, current):
        self.transforms = tuple(tuple(v) if v is not None and all(math.isfinite(x) for x in v)
                                else None for v in (original, current))
        self.setAccessibleDescription('; '.join(f'{label}: {value}' for label, value in zip(self.labels, self.transforms)))
        if self._drag is None:
            self.fit()
        self.update()

    def fit(self):
        self._extent = max((abs(x) for v in self.transforms if v is not None for x in v[:2]), default=1) or 1
        self.update()

    def _geometry(self):
        bounds = QRectF(self.rect()).adjusted(Size.GRID_GAP, Size.CONTROL * 2,
                                            -Size.GRID_GAP, -Size.CONTROL)
        centre = bounds.center()
        ratio = max(1, min(bounds.width(), bounds.height()) / 2 - Size.LARGE_CONTROL) / self._extent
        return bounds, centre, ratio

    def map_position(self, x, y):
        _, centre, ratio = self._geometry()
        return centre + QPointF(x * ratio, y * ratio)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(ui_font(TypeSize.HINT))
        plot, centre, ratio = self._geometry()
        painter.setPen(QPen(QColor(color(ColorRole.BORDER))))
        painter.drawLine(QPointF(plot.left(), centre.y()), QPointF(plot.right(), centre.y()))
        painter.drawLine(QPointF(centre.x(), plot.top()), QPointF(centre.x(), plot.bottom()))
        painter.setPen(QPen(QColor(color(ColorRole.SECONDARY_TEXT))))
        painter.drawText(QRectF(plot.right() - Size.CONTROL, centre.y(), Size.CONTROL, Size.CONTROL), Qt.AlignmentFlag.AlignRight, 'X')
        painter.drawText(QRectF(centre.x(), plot.bottom(), Size.CONTROL, Size.CONTROL), Qt.AlignmentFlag.AlignCenter, 'Y')
        scale = max((abs(v[3]) for v in self.transforms if v is not None), default=1) or 1
        for i, (label, value, role) in enumerate(zip(self.labels, self.transforms, (ColorRole.MUTED_TEXT, ColorRole.ACCENT))):
            painter.setPen(QPen(QColor(color(role))))
            text = label if value is None else f'{label}: X {value[0]:.7g}  Y {value[1]:.7g}  {value[2]:.7g}°  ×{value[3]:.7g}'
            painter.drawText(QRectF(Size.GRID_GAP, Size.GAP + i * Size.CONTROL,
                                   self.width() - 2 * Size.GRID_GAP, Size.CONTROL),
                             Qt.AlignmentFlag.AlignLeft, text)
            if value is None:
                continue
            point = self.map_position(*value[:2])
            pen = QPen(QColor(color(role)), Size.ACCENT_LINE)
            if i == 0:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(point, Size.GAP, Size.GAP)
            angle = math.radians(value[2] % 360)
            length = Size.CONTROL * (value[3] / scale)
            direction = QPointF(math.cos(angle), math.sin(angle)) * length
            side = QPointF(-direction.y(), direction.x())
            painter.drawLine(point, point + direction)
            painter.drawLine(point, point + side)
            painter.drawEllipse(point + direction, Size.GAP_XS, Size.GAP_XS)

    def mousePressEvent(self, event):
        current = self.transforms[1]
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled() and current:
            point = self.map_position(*current[:2])
            if (event.position() - point).manhattanLength() <= Size.LARGE_CONTROL:
                self._drag = current[:2]
                self._drag_offset = event.position() - point
                self.setFocus()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            _, centre, ratio = self._geometry()
            delta = event.position() - self._drag_offset - centre
            self.positionEdited.emit(delta.x() / ratio, delta.y() / ratio)
            event.accept()
            return
        current = self.transforms[1]
        hover = current and (event.position() - self.map_position(*current[:2])).manhattanLength() <= Size.LARGE_CONTROL
        self.setCursor(Qt.CursorShape.SizeAllCursor if hover else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
            self.fit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            original = self._drag
            self._drag = None
            self.positionEdited.emit(*original)
            self.fit()
            event.accept()
            return
        super().keyPressEvent(event)
