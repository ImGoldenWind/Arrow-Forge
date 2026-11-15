"""Interactive view of authored UI shapes; geometry lives in core.ui_collisions."""
import copy
import math

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from core.design_tokens import TypeSize, mono_font
from core.themes import P
from core.ui_collisions import bounds, circle, hit_score, identity_index, preview_polygon, resize_box, vertices


class CollisionCanvas(QWidget):
    fields_changed = pyqtSignal()
    selection_requested = pyqtSignal(object)
    cursor_changed = pyqtSignal(int, int, object)
    gesture_finished = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._collisions, self._selected_coll = [], None
        self._original = None
        self._scale, self._min_x, self._min_y = 1., 0., 0.
        self._pad = 24
        self._drag_mode = None
        self._before = None
        self._pan = None
        self._cursor_world = (0, 0)
        self.show_original = True
        self.snap = 1
        self._fitted = False
        self.can_edit = lambda: True
        self._preserve_next_resize = False

    def set_data(self, collisions, selected_coll, original=None):
        self._collisions, self._selected_coll = list(collisions), selected_coll
        self._indices = {id(c): i for i, c in enumerate(collisions)}
        self._original = original
        if not self._fitted:
            self.fit()
        self.update()

    def view_state(self):
        return self._scale, self._min_x, self._min_y

    def restore_view(self, state):
        self._scale, self._min_x, self._min_y = state
        self._fitted = True
        self._preserve_next_resize = True
        self.update()

    def fit(self):
        boxes = [bounds(c) for c in self._collisions]
        if not boxes:
            return
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        self._scale = max(1e-9, min(max(1, self.width() - 2 * self._pad) / max(1, x1 - x0),
                                  max(1, self.height() - 2 * self._pad) / max(1, y1 - y0)))
        self._min_x = (x0 + x1) / 2 - (self.width() / 2 - self._pad) / self._scale
        self._min_y = (y0 + y1) / 2 - (self.height() / 2 - self._pad) / self._scale
        self._fitted = True
        self.update()

    def resizeEvent(self, event):
        if self._preserve_next_resize:
            self._preserve_next_resize = False
            return
        if not self._drag_mode and not self._pan:
            self.fit()

    def _w2c(self, x, y):
        return self._pad + (x - self._min_x) * self._scale, self._pad + (y - self._min_y) * self._scale

    def _c2w(self, x, y):
        return (x - self._pad) / self._scale + self._min_x, (y - self._pad) / self._scale + self._min_y

    def _path(self, c):
        path = QPainterPath()
        if c['type'] == 1:
            x, y, r = circle(c)
            cx, cy = self._w2c(x, y)
            r = abs(r) * self._scale
            path.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        else:
            path.addPolygon(QPolygonF([QPointF(*self._w2c(x, y)) for x, y in vertices(c)]))
            path.closeSubpath()
        return path

    def _handle_rects(self):
        c = self._selected_coll
        if c is None:
            return {}
        x, y, w, h = (c[k] for k in ('x', 'y', 'w', 'h'))
        points = {'tl': (x, y), 'tr': (x + w, y), 'bl': (x, y + h), 'br': (x + w, y + h)}
        if c['type'] == 2:
            vs = vertices(c)
            points = {'tl': vs[0], 'br': vs[2], 'rto': vs[1], 'lbo': vs[3]}
        elif c['type'] not in (0, 1):
            return {}
        return {tag: QRectF(cx - 5, cy - 5, 10, 10)
                for tag, point in points.items() for cx, cy in [self._w2c(*point)]}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(P['bg_dark']))
        # A logarithmic grid is view-only; it imposes no parameter range.
        step = 10 ** math.ceil(math.log10(45 / max(self._scale, 1e-12)))
        wx, wy = self._c2w(0, 0)
        ex, ey = self._c2w(self.width(), self.height())
        p.setPen(QPen(QColor(P['border']), 1))
        p.setFont(mono_font(TypeSize.CAPTION))
        for axis, lo, hi in ((0, wx, ex), (1, wy, ey)):
            for n in range(math.floor(lo / step), math.ceil(hi / step) + 1):
                value = n * step
                cx, cy = self._w2c(value if axis == 0 else 0, value if axis else 0)
                if axis == 0:
                    p.drawLine(QPointF(cx, 0), QPointF(cx, self.height()))
                    p.drawText(QPointF(cx + 3, 13), str(value))
                else:
                    p.drawLine(QPointF(0, cy), QPointF(self.width(), cy))
                    p.drawText(QPointF(3, cy - 3), str(value))
        if self.show_original and self._original is not None:
            p.setPen(QPen(QColor(P['text_dim']), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._path(self._original))
        ordered = [c for c in self._collisions if c is not self._selected_coll]
        if self._selected_coll is not None:
            ordered.append(self._selected_coll)
        for c in ordered:
            selected = c is self._selected_coll
            color = QColor(P['accent'] if selected else P['text_sec'])
            p.setPen(QPen(color, 2 if selected else 1))
            fill = QColor(color)
            fill.setAlpha(42 if selected else 12)
            path = self._path(c)
            if c['type'] == 1:
                p.fillPath(path, fill)
            else:
                hit_path = QPainterPath()
                hit_path.addPolygon(QPolygonF([QPointF(*self._w2c(x, y)) for x, y in preview_polygon(c)]))
                hit_path.closeSubpath()
                p.fillPath(hit_path, fill)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            rect = path.boundingRect()
            if rect.width() > 60 and rect.height() > 18:
                p.setPen(QColor(P['text_main'] if selected else P['text_dim']))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"#{self._indices[id(c)]} {c['name']}")
        p.setPen(QPen(QColor(P['accent']), 1))
        p.setBrush(QColor(P['bg_panel']))
        for rect in self._handle_rects().values():
            p.drawRect(rect)
        p.end()

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = pos, self._min_x, self._min_y
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        for tag, rect in self._handle_rects().items():
            if rect.adjusted(-3, -3, 3, 3).contains(pos):
                self._start_drag(tag, pos.x(), pos.y())
                return
        wx, wy = self._c2w(pos.x(), pos.y())
        hits = [c for c in self._collisions if hit_score(c, math.trunc(wx), math.trunc(wy)) >= 0]
        if hits:
            current = identity_index(hits, self._selected_coll)
            chosen = hits[(current + 1) % len(hits)] if event.modifiers() & Qt.KeyboardModifier.AltModifier else (self._selected_coll if current >= 0 else hits[-1])
            if chosen is not self._selected_coll:
                self.selection_requested.emit(chosen)
                return
            self._start_drag('move', pos.x(), pos.y())

    def _start_drag(self, mode, x, y):
        if not self.can_edit():
            return
        self._drag_mode, self._drag_start = mode, (x, y)
        self._before = copy.deepcopy(self._selected_coll)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._pan:
            start, x, y = self._pan
            self._min_x, self._min_y = x - (pos.x() - start.x()) / self._scale, y - (pos.y() - start.y()) / self._scale
            self.update()
            return
        wx, wy = self._c2w(pos.x(), pos.y())
        self._cursor_world = math.trunc(wx), math.trunc(wy)
        hits = [i for i, c in enumerate(self._collisions) if hit_score(c, *self._cursor_world) >= 0]
        self.cursor_changed.emit(*self._cursor_world, hits)
        if not self._drag_mode:
            handle = any(r.adjusted(-3, -3, 3, 3).contains(pos) for r in self._handle_rects().values())
            self.setCursor(Qt.CursorShape.SizeAllCursor if handle or hits else Qt.CursorShape.ArrowCursor)
            return
        step = self.snap
        dx, dy = (round((v - start) / self._scale / step) * step for v, start in zip((pos.x(), pos.y()), self._drag_start))
        change = resize_box(self._before, self._drag_mode, dx, dy)
        if change is not None and any(self._selected_coll[k] != v for k, v in change.items()):
            self._selected_coll.update(change)
            self.fields_changed.emit()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_mode:
            self.gesture_finished.emit(self._selected_coll, self._before)
        self._drag_mode, self._before, self._pan = None, None, None
        self.unsetCursor()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._drag_mode:
            self._selected_coll.update(self._before)
            self._drag_mode = None
            self.fields_changed.emit()
            self.update()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self._drag_mode:
            return
        pos = event.position()
        wx, wy = self._c2w(pos.x(), pos.y())
        self._scale = min(100., max(1e-9, self._scale * 1.2 ** (event.angleDelta().y() / 120)))
        self._min_x = wx - (pos.x() - self._pad) / self._scale
        self._min_y = wy - (pos.y() - self._pad) / self._scale
        self.update()
        event.accept()

    def get_cursor_world(self):
        return self._cursor_world
