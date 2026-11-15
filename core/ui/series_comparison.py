"""Selectable scalar series on one shared scale; no game-specific behavior."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from core.design_tokens import ColorRole, Size, TypeSize, color, ui_font


class SeriesComparison(QWidget):
    selected = pyqtSignal(int)

    def __init__(self, original_label, current_label, horizontal_label, parent=None):
        super().__init__(parent)
        self.labels = original_label, current_label
        self.horizontal_label = horizontal_label
        self.series = ((), ())
        self.current_row = None
        self.setMinimumHeight(Size.TABLE_ROW * 7)
        self.setMinimumWidth(0)
        self.setMouseTracking(True)
        self.setAccessibleName(horizontal_label)

    def set_series(self, original, current, selected=None):
        self.series = tuple(tuple(float(v) for v in values) for values in (original, current))
        self.current_row = selected
        self.update()

    def plot_rect(self):
        minimum, maximum = self.bounds()
        metrics = QFontMetrics(ui_font(TypeSize.HINT))
        gutter = max(metrics.horizontalAdvance(f'{v:,.0f}') for v in (minimum, maximum)) + Size.GRID_GAP
        return QRectF(self.rect()).adjusted(gutter, Size.CONTROL,
                                           -Size.GRID_GAP, -Size.CONTROL)

    def bounds(self):
        values = [v for series in self.series for v in series if math.isfinite(v)]
        minimum, maximum = min(0, min(values, default=0)), max(0, max(values, default=1))
        return minimum, maximum if maximum > minimum else minimum + 1

    def row_at(self, x):
        plot = self.plot_rect()
        count = len(self.series[1])
        if not count or plot.width() <= 0:
            return None
        axis_count = max(len(values) for values in self.series)
        return max(0, min(count - 1, round((x - plot.left()) / plot.width() * max(1, axis_count - 1))))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.plot_rect().contains(event.position()):
            row = self.row_at(event.position().x())
            if row is not None:
                self.selected.emit(row)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        row = self.row_at(event.position().x())
        self.setToolTip('' if row is None else f'{self.horizontal_label} {row + 1}: {self.series[1][row]:,.12g}')
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(ui_font(TypeSize.HINT))
        plot = self.plot_rect()
        if plot.width() <= 0 or plot.height() <= 0:
            return
        minimum, maximum = self.bounds()
        span = maximum - minimum
        count = max((len(v) for v in self.series), default=0)
        painter.setPen(QPen(QColor(color(ColorRole.BORDER))))
        painter.drawRect(plot)
        painter.setPen(QPen(QColor(color(ColorRole.SECONDARY_TEXT))))
        for fraction in (0, .5, 1):
            y = plot.bottom() - plot.height() * fraction
            painter.drawText(QRectF(0, y - Size.GAP, plot.left() - Size.GAP, Size.CONTROL),
                             Qt.AlignmentFlag.AlignRight, f'{minimum + span * fraction:,.0f}')
        painter.drawText(QRectF(plot.left(), plot.bottom() + Size.GAP_SM, plot.width(), Size.CONTROL),
                         Qt.AlignmentFlag.AlignCenter, self.horizontal_label)
        # File positions have real labels even though IDs need not equal ordinals.
        painter.drawText(QRectF(plot.left(), plot.bottom(), Size.CONTROL, Size.CONTROL),
                         Qt.AlignmentFlag.AlignLeft, '1' if count else '')
        painter.drawText(QRectF(plot.right() - Size.CONTROL, plot.bottom(), Size.CONTROL, Size.CONTROL),
                         Qt.AlignmentFlag.AlignRight, str(count) if count else '')
        for values, role, dashed, label, i in zip(self.series,
                (ColorRole.MUTED_TEXT, ColorRole.ACCENT), (True, False), self.labels, range(2)):
            pen = QPen(QColor(color(role)), Size.ACCENT_LINE)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawText(QRectF(plot.left() + i * plot.width() / 2, 0, plot.width() / 2, Size.CONTROL),
                             Qt.AlignmentFlag.AlignVCenter, label)
            def point(row):
                return QPointF(plot.left() + row / max(1, count - 1) * plot.width(),
                               plot.bottom() - (values[row] - minimum) / span * plot.height())
            # Bound paint work for huge documents while retaining local extrema.
            step = max(1, len(values) // max(1, int(plot.width())))
            rows = []
            for start in range(0, len(values), step):
                end = min(start + step, len(values))
                rows.extend(sorted({start, end - 1, min(range(start, end), key=values.__getitem__),
                                    max(range(start, end), key=values.__getitem__)}))
            painter.drawPolyline(QPolygonF([point(row) for row in rows]))
            if not dashed and self.current_row is not None and 0 <= self.current_row < len(values):
                painter.setBrush(QColor(color(role)))
                painter.drawEllipse(point(self.current_row), Size.GAP_SM, Size.GAP_SM)
