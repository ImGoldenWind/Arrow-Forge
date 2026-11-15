"""Independent authored events on the shared LipSync clip canvas.

Drawing, ruler, playhead, zoom and overview are shared. Event edits remain
requests: unlike phoneme boundaries, these records never sort or move neighbors.
"""
from dataclasses import dataclass
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QToolTip
from core.design_tokens import TypeSize, mono_font
from core.themes import P
from core.translations import ui_text
from core.ui.clip_timeline import ClipTimelineWidget, TimelineOverviewWidget


@dataclass(frozen=True)
class TimelineEvent:
    index: int
    track: str
    label: str
    start: int
    duration: int = 0
    original_start: int | None = None
    track_label: str = ''
    resizable: bool = False


@dataclass
class _EventClip:
    event: TimelineEvent
    time: float


class EventTimeline(ClipTimelineWidget):
    selected = pyqtSignal(int)
    moved = pyqtSignal(int, int)
    resized = pyqtSignal(int, int)
    cursorChanged = pyqtSignal(int)
    LANE = 58

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = []
        self.extent = 30
        self.compare = True
        self._show_locks = False
        self._tracks = []
        self._drag = None
        self._hits = []
        self._scrubbing = False
        self._view_span_ratio = 1.
        self.playheadScrubbed.connect(self._scrubbed)
        self.set_playhead_time(0.)

    @property
    def current(self):
        return self._selected

    @current.setter
    def current(self, value):
        self._selected = value

    @property
    def cursor(self):
        return round(self._playhead_time or 0)

    @cursor.setter
    def cursor(self, value):
        self.set_playhead_time(float(value))

    def set_events(self, events, extent, current=-1):
        self.events = events
        self.extent = max(1, extent)
        self._tracks = list(dict.fromkeys(e.track for e in events))
        self._track_top, self._event_row = {}, {}
        rows = 0
        for track in self._tracks:
            self._track_top[track] = rows
            ends = []
            for index in sorted((i for i, e in enumerate(events) if e.track == track),
                                key=lambda i: (events[i].start, i)):
                item = events[index]
                row = next((i for i, end in enumerate(ends) if end <= item.start), len(ends)) if item.duration else 0
                self._event_row[index] = row
                if row == len(ends):
                    ends.append(item.start + item.duration)
                elif item.duration:
                    ends[row] = item.start + item.duration
            rows += max(1, len(ends))
        self._keys = [_EventClip(e, float(e.start)) for e in events]
        self._selected = current
        self._clamp_view_range()
        self.setFixedHeight(max(210, self._ruler_y() + 8 + self.LANE * rows + 16))
        self.update()
        self.viewRangeChanged.emit(*self.view_range())

    def _duration(self):
        return self.extent + max(1., self.extent * .03)

    def _min_visible_duration(self):
        return min(self._duration(), max(1., self._duration() * .04))

    def _track_bounds(self):
        return 122, max(123, self.width() - 10)

    def _format_time(self, value):
        return ui_text('finish_frame_tick', p0=round(value))

    def _empty_text(self):
        return ui_text('motion_empty_events')

    def x_at(self, frame):
        return self._x_for_time(frame)

    def frame_at(self, x):
        return max(0, min(0xFFFFFFFF, round(self._time_for_x(x))))

    def _color_for_key(self, key):
        roles = ('accent', 'secondary', 'highlight', 'accent_dim', 'text_sec')
        return QColor(P[roles[self._tracks.index(key.event.track) % len(roles)]])

    def _label_for_key(self, key):
        event = key.event
        name = event.label.rsplit(' · ', 1)[-1]
        return f'#{event.index} · {name}' if name else f'#{event.index}'

    def _visible_segment_indices(self):
        indices = [i for i in range(len(self._keys)) if self._segment_time_range(i)[1] >= self._view_start
                   and self._segment_time_range(i)[0] <= self._view_end()]
        return [i for i in indices if i != self._selected] + ([self._selected] if self._selected in indices else [])

    def _segment_time_range(self, idx):
        item = self.events[idx]
        start, duration = item.start, item.duration
        if self._drag and self._drag[0] == idx:
            if self._drag[1] == 'duration':
                duration = self._drag[2]
            else:
                start = self._drag[2]
        return start, start + duration

    def _segment_next_index(self, idx):
        return idx if self.events[idx].resizable else -1

    def _segment_rect(self, idx):
        start, end = self._segment_time_range(idx)
        left, right = self._track_bounds()
        x1 = max(left, min(right, self._x_for_time(start)))
        x2 = max(left, min(right, self._x_for_time(end)))
        width = max(7., x2 - x1)
        lane = self._track_top[self.events[idx].track] + self._event_row[idx]
        y = self._ruler_y() + 8 + self.LANE * lane + 10
        return QRectF(x1, y, min(width, max(1., right - x1)), 38)

    def _lock_hit(self, pos):
        return -1

    def reveal(self, frame):
        start, end = self.view_range()
        if frame < start or frame > end:
            span = end - start
            self.set_view_range(frame - span / 2, frame + span / 2)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        for index in self._visible_segment_indices():
            item = self.events[index]
            rect = self._segment_rect(index)
            self._hits.append((rect, item))
            if self.compare and item.original_start is not None and item.original_start != self._segment_time_range(index)[0]:
                original_x = self.x_at(item.original_start)
                left, right = self._track_bounds()
                if left <= original_x <= right:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(P['text_dim']), 1, Qt.PenStyle.DashLine))
                    painter.drawRoundedRect(QRectF(original_x, rect.top(), 7, rect.height()), 3, 3)
                    painter.drawLine(QPointF(original_x, rect.center().y()), QPointF(rect.left(), rect.center().y()))
        for track in self._tracks:
            representative = next(k for k in self._keys if k.event.track == track)
            y = self._ruler_y() + 8 + self.LANE * self._track_top[track]
            painter.setPen(self._color_for_key(representative))
            painter.setFont(mono_font(TypeSize.HINT))
            label = representative.event.track_label or track
            label = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, 106)
            painter.drawText(QRectF(10, y + 8, 106, 20), Qt.AlignmentFlag.AlignVCenter, label)
            painter.setPen(QColor(P['text_dim']))
            painter.setFont(mono_font(TypeSize.TINY))
            painter.drawText(QRectF(10, y + 28, 106, 16), Qt.AlignmentFlag.AlignVCenter, track)

    def _hit(self, pos):
        hits = [i for i in self._visible_segment_indices() if self._segment_rect(i).adjusted(-4, -3, 4, 3).contains(pos)]
        if not hits:
            return None
        # Start handles remain selectable where duration bars overlap.
        return min(hits, key=lambda i: abs(self._segment_rect(i).left() - pos.x()))

    def _scrubbed(self, time):
        frame = max(0, min(0xFFFFFFFF, round(time)))
        self.set_playhead_time(frame)
        self.cursorChanged.emit(frame)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = (event.position().x(), self.view_range())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._ruler_hit(event.position()):
            self._scrubbing = True
            self._set_scrub_position_from_x(event.position().x())
            return
        index = self._hit(event.position())
        if index is None:
            self._scrubbing = True
            self._set_scrub_position_from_x(event.position().x())
            return
        self.selected.emit(index)
        if self.current != index:
            return
        item = self.events[index]
        rect = self._segment_rect(index)
        mode = 'duration' if item.resizable and abs(event.position().x() - rect.right()) <= 8 else 'time'
        self._drag = (index, mode, item.duration if mode == 'duration' else item.start, event.position().x(),
                      item.duration if mode == 'duration' else item.start)
        self.setCursor(Qt.CursorShape.SizeHorCursor if mode == 'duration' else Qt.CursorShape.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if getattr(self, '_pan', None):
            origin, (start, end) = self._pan
            left, right = self._track_bounds()
            delta = (origin - event.position().x()) / max(1, right - left) * (end - start)
            self.set_view_range(start + delta, end + delta)
        elif self._scrubbing:
            self._set_scrub_position_from_x(event.position().x())
        elif self._drag:
            index, mode, _, origin, original = self._drag
            left, right = self._track_bounds()
            delta = round((event.position().x() - origin) / max(1, right - left) * self._visible_duration())
            value = max(0, min(0x7FFFFFFF if mode == 'duration' else 0xFFFFFFFF, original + delta))
            self._drag = (index, mode, value, origin, original)
            self.update()
        else:
            index = self._hit(event.position())
            if index is not None:
                QToolTip.showText(event.globalPosition().toPoint(), self.events[index].label, self)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                QToolTip.hideText()
                self.unsetCursor()

    def mouseReleaseEvent(self, event):
        if self._drag:
            index, mode, value, origin, original = self._drag
            self._drag = None
            if value != original and abs(event.position().x() - origin) >= 3:
                (self.resized if mode == 'duration' else self.moved).emit(index, value)
        self._scrubbing = False
        self._pan = None
        self.unsetCursor()
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            frame = (0 if event.key() == Qt.Key.Key_Home else self.extent if event.key() == Qt.Key.Key_End
                     else max(0, min(self.extent, self.cursor + (-1 if event.key() == Qt.Key.Key_Left else 1))))
            self._scrubbed(frame)
        else:
            super().keyPressEvent(event)


class EventTimelineOverview(TimelineOverviewWidget):
    def set_timeline(self, timeline):
        self.timeline = timeline
        timeline.viewRangeChanged.connect(self.refresh)
        self.viewRangeChanged.connect(timeline.set_view_range)
        self.refresh()

    def refresh(self, *_):
        self.set_data(self.timeline._keys, self.timeline.timeline_duration(), *self.timeline.view_range())

    def _segments(self):
        return [(key.event.start, key.event.start + key.event.duration, self.timeline._color_for_key(key))
                for key in self._keys]
