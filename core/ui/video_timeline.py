"""One selected media interval on Arrow Forge's shared clip canvas.

The host owns media playback and validation. Edits commit on release; Escape
restores the gesture. No video decoding or game semantics live in this widget.
"""
from dataclasses import dataclass
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from core.themes import P
from core.translations import ui_text
from core.ui.clip_timeline import ClipTimelineWidget, TimelineOverviewWidget


@dataclass
class _Boundary:
    time: float
    label: str = ''
    end: bool = False


class VideoTimeline(ClipTimelineWidget):
    intervalChanged = pyqtSignal(float, float)
    intervalPreview = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(134)
        self.setMaximumHeight(134)
        self._view_span_ratio = 1.
        self._show_locks = False
        self.editable = False
        self._before = None
        self.fps = 0.
        self.keyMoved.connect(lambda *_: self.intervalPreview.emit(*self.interval()))
        self.setAccessibleName(ui_text('usm_video_timeline'))
        self.setToolTip(ui_text('usm_timeline_hint'))

    def set_media(self, duration, start=0., end=None, *, label='', editable=False, fps=0.):
        duration = max(0., duration)
        changed_source = self._duration_override != duration
        self._duration_override = duration or None
        self.editable, self.fps = editable, fps
        if not self._dragging:
            self._keys = ([_Boundary(start, label), _Boundary(duration if end is None else end, end=True)]
                          if duration else [])
        if changed_source:
            self.fit_view()
        self._clamp_view_range()
        self.update()

    def interval(self):
        return tuple(key.time for key in self._keys) if self._keys else (0., 0.)

    def _key_time_limits(self, index):
        start, end = self.interval()
        minimum_span = min(.001, self._duration())
        return (0., max(0., end - minimum_span)) if index == 0 else (min(self._duration(), start + minimum_span), self._duration())

    def _track_bounds(self):
        # Keep the shared 36 px ruler captions inside this compact surface.
        return 18, max(19, self.width() - 18)

    def _is_neutral_key(self, key):
        return key.end

    def _is_locked(self, index):
        return not self.editable

    def _lock_hit(self, pos):
        return -1

    def _format_time(self, value):
        return f'{value:.2f}' if value < 100 else f'{int(value // 60)}:{int(value % 60):02d}'

    def _empty_text(self):
        return ui_text('usm_empty_timeline')

    def mousePressEvent(self, event):
        self._before = self.interval()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        before = self._before
        super().mouseReleaseEvent(event)
        self._before = None
        if self.editable and before and before != self.interval():
            self.intervalChanged.emit(*self.interval())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._before:
            for key, value in zip(self._keys, self._before):
                key.time = value
            self._before = None
            self._dragging = self._scrubbing_playhead = False
            self.unsetCursor()
            self.update()
            return
        current = self._playhead_time or 0.
        step = 1 / self.fps if self.fps else .001
        targets = {Qt.Key.Key_Home: 0., Qt.Key.Key_End: self._duration(),
                   Qt.Key.Key_Left: max(0., current - step), Qt.Key.Key_Right: min(self._duration(), current + step)}
        if self._keys and event.key() in targets:
            self.set_playhead_time(targets[event.key()])
            self.playheadScrubbed.emit(targets[event.key()])
            event.accept()
        else:
            super().keyPressEvent(event)


class VideoTimelineOverview(TimelineOverviewWidget):
    def _segments(self):
        if len(self._keys) < 2:
            return []
        return [(self._keys[0].time, self._keys[1].time, QColor(P['accent']))]
