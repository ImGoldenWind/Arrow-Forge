"""Shared clip drawing, ruler, playhead, viewport and overview from LipSync.

Subclasses own clip semantics, colors, labels and domain editing constraints.
The original LipSync subclasses remain import-compatible in lipsync_editor.
"""
from __future__ import annotations
import math
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget
from core.design_tokens import TypeSize, mono_font
from core.themes import P
from core.translations import ui_text


class ClipTimelineWidget(QWidget):
    keySelected = pyqtSignal(int)
    keyMoved = pyqtSignal(int, float)
    playheadScrubbed = pyqtSignal(float)
    viewRangeChanged = pyqtSignal(float, float)
    segmentSplitRequested = pyqtSignal(int, float)
    lockToggleRequested = pyqtSignal(int)
    editStarted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list = []
        self._show_locks = True
        self._selected = -1
        self._dragging = False
        self._drag_idx = -1
        self._playhead_time: float | None = None
        self._duration_override: float | None = None
        self._view_start = 0.0
        self._view_span_ratio = 0.45
        self._range_drag_mode: str | None = None
        self._range_drag_x = 0.0
        self._range_drag_start = 0.0
        self._range_drag_end = 0.0
        self._drag_mode: str | None = None
        self._drag_next_idx = -1
        self._drag_x = 0.0
        self._drag_start_time = 0.0
        self._drag_end_time = 0.0
        self._scrubbing_playhead = False
        self._waveform: list[float] = []
        self._waveform_duration = 0.0
        self._tool_mode = "cursor"
        self._snap_enabled = True
        self._locked_indices: set[int] = set()
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_keys(self, keys: list, selected: int = -1):
        self._keys = keys
        self._selected = selected
        self._clamp_view_range()
        self.update()

    def set_playhead_time(self, time_value: float | None):
        self._playhead_time = time_value
        self.update()

    def set_waveform(self, peaks: list[float] | None, duration: float = 0.0):
        self._waveform = list(peaks or [])
        self._waveform_duration = max(0.0, float(duration or 0.0))
        self.update()

    def set_tool_mode(self, mode: str):
        self._tool_mode = "blade" if mode == "blade" else "cursor"
        self.update()

    def set_snap_enabled(self, enabled: bool):
        self._snap_enabled = bool(enabled)

    def set_locked_indices(self, indices: set[int] | list[int] | tuple[int, ...]):
        self._locked_indices = {int(idx) for idx in indices}
        self.update()

    def set_duration_override(self, duration: float | None):
        self._duration_override = duration if duration and duration > 0 else None
        self._clamp_view_range()
        self.update()

    def _duration(self) -> float:
        if not self._keys:
            return self._duration_override or 1.0
        max_time = max(key.time for key in self._keys)
        if self._duration_override is not None:
            return max(0.001, self._duration_override)
        return max(1.0, max_time + max(0.25, max_time * 0.1))

    def _visible_duration(self) -> float:
        duration = self._duration()
        return min(duration, max(self._min_visible_duration(), duration * self._view_span_ratio))

    def _min_visible_duration(self) -> float:
        duration = self._duration()
        return min(duration, max(0.15, duration * 0.04))

    def _view_end(self) -> float:
        return min(self._duration(), self._view_start + self._visible_duration())

    def _max_view_start(self) -> float:
        return max(0.0, self._duration() - self._visible_duration())

    def _clamp_view_range(self):
        duration = self._duration()
        self._view_span_ratio = max(self._min_visible_duration() / duration, min(1.0, self._view_span_ratio))
        max_start = self._max_view_start()
        self._view_start = min(max(self._view_start, 0.0), max_start)

    def _set_view_range(self, start: float, end: float):
        duration = self._duration()
        min_span = self._min_visible_duration()
        start = max(0.0, min(duration - min_span, start))
        end = max(start + min_span, min(duration, end))
        if end - start > duration:
            start, end = 0.0, duration
        self._view_start = start
        self._view_span_ratio = max(min_span / duration, min(1.0, (end - start) / duration))
        self._clamp_view_range()
        self.update()
        self.viewRangeChanged.emit(self._view_start, self._view_end())

    def view_range(self) -> tuple[float, float]:
        return self._view_start, self._view_end()

    def timeline_duration(self) -> float:
        return self._duration()

    def set_view_range(self, start: float, end: float):
        self._set_view_range(start, end)

    def shift_view(self, direction: float):
        span = self._visible_duration()
        delta = span * 0.35 * direction
        self._set_view_range(self._view_start + delta, self._view_end() + delta)

    def zoom_view(self, factor: float):
        duration = self._duration()
        start = self._view_start
        end = self._view_end()
        center = (start + end) * 0.5
        new_span = max(self._min_visible_duration(), min(duration, (end - start) * factor))
        self._set_view_range(center - new_span * 0.5, center + new_span * 0.5)

    def zoom_normalized(self) -> float:
        duration = self._duration()
        min_span = self._min_visible_duration()
        span_range = max(0.000001, duration - min_span)
        return max(0.0, min(1.0, (duration - self._visible_duration()) / span_range))

    def set_zoom_normalized(self, value: float):
        duration = self._duration()
        min_span = self._min_visible_duration()
        value = max(0.0, min(1.0, float(value)))
        span = duration - (duration - min_span) * value
        center = (self._view_start + self._view_end()) * 0.5
        self._set_view_range(center - span * 0.5, center + span * 0.5)

    def fit_view(self):
        self._set_view_range(0.0, self._duration())

    def _ordered_key_indices(self) -> list[int]:
        return sorted(range(len(self._keys)), key=lambda idx: (self._keys[idx].time, idx))


    def _is_locked(self, idx: int) -> bool:
        return idx in self._locked_indices

    def _key_time_limits(self, idx: int) -> tuple[float, float]:
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return 0.0, self._duration()
        pos = ordered.index(idx)
        epsilon = min(0.01, max(0.001, self._duration() * 0.0005))
        min_time = 0.0
        max_time = self._duration()
        if pos > 0:
            min_time = self._keys[ordered[pos - 1]].time + epsilon
        if pos < len(ordered) - 1:
            max_time = self._keys[ordered[pos + 1]].time - epsilon
        return min(min_time, max_time), max(min_time, max_time)

    def _segment_time_range(self, idx: int) -> tuple[float, float]:
        if (
            self._dragging
            and self._drag_mode == "body"
            and idx == self._drag_idx
            and 0 <= self._drag_next_idx < len(self._keys)
        ):
            start = max(0.0, self._keys[self._drag_idx].time)
            end = max(start, self._keys[self._drag_next_idx].time)
            return start, end
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return 0.0, 0.0
        pos = ordered.index(idx)
        start = max(0.0, self._keys[idx].time)
        end = self._duration()
        if pos < len(ordered) - 1:
            end = self._keys[ordered[pos + 1]].time
        return start, max(start, end)

    def _segment_next_index(self, idx: int) -> int:
        if (
            self._dragging
            and self._drag_mode == "body"
            and idx == self._drag_idx
            and 0 <= self._drag_next_idx < len(self._keys)
        ):
            return self._drag_next_idx
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return -1
        pos = ordered.index(idx)
        return ordered[pos + 1] if pos < len(ordered) - 1 else -1


    def _visible_segment_indices(self) -> list[int]:
        view_start = self._view_start
        view_end = self._view_end()
        indices: list[int] = []
        for idx in self._ordered_key_indices():
            key = self._keys[idx]
            if self._is_neutral_key(key):
                continue
            start, end = self._segment_time_range(idx)
            if end >= view_start and start <= view_end:
                indices.append(idx)
        return indices

    def _track_bounds(self) -> tuple[int, int]:
        left = 10
        return left, max(left + 1, self.width() - 10)

    def _scrollbar_track_rect(self) -> QRectF:
        left, right = self._track_bounds()
        return QRectF(left, max(0, self.height() - 18), right - left, 8)

    def _ruler_y(self) -> int:
        return 54

    def _lane_rect(self) -> QRectF:
        left, right = self._track_bounds()
        top = self._ruler_y() + 8
        bottom = max(top + 60, self.height() - 12)
        return QRectF(left, top, right - left, bottom - top)

    def _scrollbar_thumb_rect(self) -> QRectF:
        track = self._scrollbar_track_rect()
        duration = self._duration()
        start_ratio = self._view_start / duration
        end_ratio = self._view_end() / duration
        return QRectF(
            track.left() + track.width() * start_ratio,
            track.top() - 1,
            track.width() * max(0.0, end_ratio - start_ratio),
            track.height() + 2,
        )

    def _scrollbar_hit_mode(self, pos) -> str | None:
        track = self._scrollbar_track_rect().adjusted(0, -3, 0, 3)
        if not track.contains(pos):
            return None
        thumb = self._scrollbar_thumb_rect().adjusted(-2, -5, 2, 5)
        edge_width = 10
        if abs(pos.x() - thumb.left()) <= edge_width:
            return "left"
        if abs(pos.x() - thumb.right()) <= edge_width:
            return "right"
        if self._duration() <= self._visible_duration() + 0.0001:
            return None
        if thumb.contains(pos):
            return "move"
        return "jump"

    def _x_for_time(self, value: float) -> int:
        left, right = self._track_bounds()
        ratio = (value - self._view_start) / max(0.000001, self._visible_duration())
        return int(left + (right - left) * ratio)

    def _time_for_x(self, x: float, duration: float | None = None) -> float:
        left, right = self._track_bounds()
        ratio = min(1.0, max(0.0, (x - left) / (right - left)))
        return min(self._duration(), max(0.0, self._view_start + ratio * (duration if duration is not None else self._visible_duration())))


    def _segment_rect(self, idx: int) -> QRectF:
        start, end = self._segment_time_range(idx)
        view_start = self._view_start
        view_end = self._view_end()
        clipped_start = max(start, view_start)
        clipped_end = min(end, view_end)
        left, right = self._track_bounds()
        x1 = max(left, min(right, self._x_for_time(clipped_start)))
        x2 = max(left, min(right, self._x_for_time(clipped_end)))
        if x2 - x1 < 5:
            x2 = min(right, x1 + 5)
        lane = self._lane_rect()
        lane_h = 38
        lane_y = lane.center().y() - lane_h // 2
        return QRectF(x1, lane_y, max(1.0, x2 - x1), lane_h)

    def _segment_hit(self, pos) -> tuple[str, int] | None:
        edge_width = 12
        for idx in reversed(self._visible_segment_indices()):
            base_rect = self._segment_rect(idx)
            hit_rect = base_rect.adjusted(-edge_width, -4, edge_width, 4)
            if not hit_rect.contains(pos):
                continue
            short_segment = base_rect.width() <= edge_width * 2.4
            center_x = base_rect.center().x()
            if short_segment:
                return ("left" if pos.x() <= center_x else "right"), idx
            if abs(pos.x() - base_rect.left()) <= edge_width:
                return "left", idx
            next_idx = self._segment_next_index(idx)
            if next_idx >= 0 and abs(pos.x() - base_rect.right()) <= edge_width:
                return "right", idx
            return "body", idx
        return None

    def _lock_rect(self, idx: int) -> QRectF:
        clip_rect = self._segment_rect(idx)
        size = 15
        return QRectF(clip_rect.right() - size - 4, clip_rect.top() + 5, size, size)

    def _lock_hit(self, pos) -> int:
        for idx in reversed(self._visible_segment_indices()):
            if self._lock_rect(idx).adjusted(-3, -3, 3, 3).contains(pos):
                return idx
        return -1

    def _snap_time(self, value: float, exclude: set[int] | None = None) -> float:
        if not self._snap_enabled:
            return value
        exclude = exclude or set()
        threshold = max(0.015, self._visible_duration() * 0.018)
        candidates = [0.0, self._duration()]
        candidates.extend(key.time for idx, key in enumerate(self._keys) if idx not in exclude)
        best = min(candidates, key=lambda candidate: abs(candidate - value))
        return best if abs(best - value) <= threshold else value

    def _timeline_lane_rect(self) -> QRectF:
        return self._lane_rect()

    def _playhead_hit(self, pos) -> bool:
        if self._playhead_time is None:
            return False
        x = self._x_for_time(self._playhead_time)
        marker = QRectF(x - 8, 4, 16, 16)
        center = QRectF(x - 7, self._lane_rect().center().y() - 7, 14, 14)
        return marker.contains(pos) or center.contains(pos)

    def _ruler_hit(self, pos) -> bool:
        left, right = self._track_bounds()
        ruler_y = self._ruler_y()
        return QRectF(left, ruler_y - 34, right - left, 42).contains(pos)

    def _set_scrub_position_from_x(self, x: float):
        time_value = self._time_for_x(x)
        self._playhead_time = time_value
        self.playheadScrubbed.emit(time_value)
        self.update()

    def _paint_waveform(self, painter: QPainter, lane: QRectF):
        if not self._waveform or self._waveform_duration <= 0:
            return
        view_start = self._view_start
        view_end = self._view_end()
        sample_count = len(self._waveform)
        if sample_count <= 0:
            return

        visible_start = max(0, int(math.floor((view_start / self._waveform_duration) * sample_count)))
        visible_end = min(sample_count, int(math.ceil((view_end / self._waveform_duration) * sample_count)) + 1)
        if visible_end <= visible_start:
            return

        center_y = lane.center().y()
        max_h = lane.height() * 0.42
        waveform_color = QColor(P["text_dim"])
        waveform_color.setAlpha(70)
        painter.setPen(QPen(waveform_color, 1))

        left, right = self._track_bounds()
        last_x = -1000
        column_peak = 0.0
        for idx in range(visible_start, visible_end):
            time_value = self._waveform_duration * (idx / max(1, sample_count - 1))
            x = max(left, min(right, self._x_for_time(time_value)))
            peak = self._waveform[idx]
            if x == last_x:
                column_peak = max(column_peak, peak)
                continue
            if last_x >= left:
                half_h = max(1.0, column_peak * max_h)
                painter.drawLine(last_x, int(center_y - half_h), last_x, int(center_y + half_h))
            last_x = x
            column_peak = peak
        if last_x >= left:
            half_h = max(1.0, column_peak * max_h)
            painter.drawLine(last_x, int(center_y - half_h), last_x, int(center_y + half_h))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, QColor(P.get("panel_card_bg", P["bg_panel"])))

        if not self._keys:
            painter.setPen(QColor(P["text_dim"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._empty_text())
            painter.end()
            return

        left, right = self._track_bounds()
        canvas_top = max(0, self._ruler_y() - 36)
        canvas = QRectF(left, canvas_top, right - left, max(1, rect.height() - canvas_top - 8))
        painter.setPen(QPen(QColor(P["border"]), 1))
        painter.setBrush(QColor(P["bg_card"]))
        painter.drawRoundedRect(canvas, 6, 6)

        lane = self._lane_rect()
        axis_y = int(lane.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(P.get("panel_card_bg", P["bg_panel"])))
        painter.drawRoundedRect(lane, 6, 6)
        self._paint_waveform(painter, lane.adjusted(0, 3, 0, -3))

        grid_pen = QPen(QColor(P["border"]), 1)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        minor_count = max(8, min(64, int(self._visible_duration() * 12)))
        for tick in range(minor_count + 1):
            time_value = self._view_start + self._visible_duration() * tick / minor_count
            x = self._x_for_time(time_value)
            painter.drawLine(x, int(lane.top()), x, int(lane.bottom()))

        if self._playhead_time is not None:
            playhead_x = self._x_for_time(self._playhead_time)
            progress_width = 0
            if self._playhead_time >= self._view_end():
                progress_width = right - left
            elif self._playhead_time >= self._view_start:
                progress_width = max(0, playhead_x - left)
            progress = QRectF(left, lane.bottom() - 3, progress_width, 2)
            painter.setBrush(QColor(P["accent_dim"]))
            painter.drawRoundedRect(progress, 1, 1)

        view_start = self._view_start
        view_end = self._view_end()
        visible_duration = max(0.000001, view_end - view_start)
        tick_count = max(2, min(10, int(visible_duration * 2) + 2))
        painter.setFont(mono_font(TypeSize.CAPTION))
        painter.setPen(QPen(QColor(P["text_dim"]), 1))
        ruler_y = self._ruler_y()
        for tick in range(tick_count + 1):
            time_value = view_start + visible_duration * tick / tick_count
            x = self._x_for_time(time_value)
            painter.drawLine(x, ruler_y - 8, x, ruler_y)
            painter.drawText(
                x - 18,
                ruler_y - 28,
                36,
                14,
                Qt.AlignmentFlag.AlignCenter,
                self._format_time(time_value),
            )

        for idx in self._visible_segment_indices():
            key = self._keys[idx]
            color = self._color_for_key(key)
            clip_rect = self._segment_rect(idx)
            fill = QColor(color)
            fill.setAlpha(210 if idx == self._selected else 165)
            painter.setBrush(color)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(P["shine"] if idx == self._selected else P["border"]), 1))
            painter.drawRoundedRect(clip_rect, 5, 5)

            edge = QColor(P["shine"])
            edge.setAlpha(190 if idx == self._selected else 120)
            painter.setBrush(edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(clip_rect.left() + 3, clip_rect.top() + 4, 2, clip_rect.height() - 8), 1, 1)
            if self._segment_next_index(idx) >= 0 and clip_rect.width() > 16:
                painter.drawRoundedRect(QRectF(clip_rect.right() - 5, clip_rect.top() + 4, 2, clip_rect.height() - 8), 1, 1)

            label = self._label_for_key(key)
            painter.setPen(QColor(P["shine"]))
            painter.setFont(mono_font(TypeSize.CAPTION, QFont.Weight.Bold))
            if clip_rect.width() >= 24:
                painter.drawText(clip_rect.adjusted(3, -4, -3, -4), Qt.AlignmentFlag.AlignCenter,
                                 painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight,
                                                                max(0, int(clip_rect.width() - 6))))
                painter.setFont(mono_font(TypeSize.TINY))
                start, end = self._segment_time_range(idx)
                painter.drawText(
                    clip_rect.adjusted(3, 18, -3, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    self._format_time(max(0.0, end - start)),
                )
            elif idx == self._selected:
                painter.drawText(clip_rect.adjusted(-12, -16, 12, -16), Qt.AlignmentFlag.AlignCenter, label)

            lock_rect = self._lock_rect(idx)
            if self._show_locks and clip_rect.width() >= 34:
                lock_bg = QColor(P["bg_card"])
                lock_bg.setAlpha(185)
                painter.setBrush(lock_bg)
                painter.setPen(QPen(QColor(P["border"]), 1))
                painter.drawRoundedRect(lock_rect, 3, 3)
                lock_color = QColor(P["shine"] if self._is_locked(idx) else P["text_dim"])
                painter.setPen(QPen(lock_color, 1))
                body = QRectF(lock_rect.left() + 4, lock_rect.top() + 7, 7, 5)
                painter.drawRoundedRect(body, 1, 1)
                painter.drawArc(QRectF(lock_rect.left() + 4, lock_rect.top() + 3, 7, 8), 0, 180 * 16)
                if not self._is_locked(idx):
                    painter.drawLine(int(lock_rect.left() + 10), int(lock_rect.top() + 4), int(lock_rect.left() + 13), int(lock_rect.top() + 3))

        if self._playhead_time is not None:
            x = self._x_for_time(self._playhead_time)
            if left <= x <= right:
                painter.setPen(QPen(QColor(P["shine"]), 2))
                painter.drawLine(x, self._ruler_y() - 8, x, rect.height() - 12)
                painter.setBrush(QColor(P["shine"]))
                handle = QPainterPath()
                handle.moveTo(x, self._ruler_y() - 8)
                handle.lineTo(x - 6, self._ruler_y() - 18)
                handle.lineTo(x + 6, self._ruler_y() - 18)
                handle.closeSubpath()
                painter.drawPath(handle)
                painter.drawEllipse(x - 4, axis_y - 4, 8, 8)

        painter.end()

    def mousePressEvent(self, event):
        if not self._keys:
            return

        if event.button() == Qt.MouseButton.LeftButton and self._playhead_hit(event.position()):
            self._scrubbing_playhead = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_scrub_position_from_x(event.position().x())
            return

        if event.button() == Qt.MouseButton.LeftButton and self._ruler_hit(event.position()):
            self._scrubbing_playhead = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_scrub_position_from_x(event.position().x())
            return

        lock_idx = self._lock_hit(event.position())
        if event.button() == Qt.MouseButton.LeftButton and lock_idx >= 0:
            self.lockToggleRequested.emit(lock_idx)
            return

        segment_hit = self._segment_hit(event.position())
        if segment_hit:
            hit_mode, idx = segment_hit
            self._selected = idx
            self.keySelected.emit(idx)
            if self._tool_mode == "blade":
                if not self._is_locked(idx):
                    self.editStarted.emit()
                    self.segmentSplitRequested.emit(idx, self._time_for_x(event.position().x()))
                self.update()
                return
            if self._is_locked(idx):
                self.update()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self.editStarted.emit()
            if hit_mode == "body":
                idx = self._ensure_gap_before_segment(idx)
                self._selected = idx
                self.keySelected.emit(idx)
            self._dragging = event.button() == Qt.MouseButton.LeftButton
            self._drag_mode = hit_mode
            self._drag_idx = idx
            self._drag_next_idx = self._segment_next_index(idx)
            self._drag_x = event.position().x()
            self._drag_start_time, self._drag_end_time = self._segment_time_range(idx)
            if self._dragging:
                if hit_mode == "right" and self._drag_next_idx < 0:
                    self._dragging = False
                    self._drag_mode = None
                elif hit_mode == "body" and self._drag_next_idx < 0:
                    self._drag_mode = "left"
                self.setCursor(Qt.CursorShape.SizeAllCursor if self._drag_mode == "body" else Qt.CursorShape.SizeHorCursor)
            self.update()
            return

    def mouseMoveEvent(self, event):
        if not self._keys:
            return
        if self._scrubbing_playhead:
            self._set_scrub_position_from_x(event.position().x())
            return
        if self._dragging and 0 <= self._drag_idx < len(self._keys):
            if self._drag_mode == "body" and 0 <= self._drag_next_idx < len(self._keys):
                left, right = self._track_bounds()
                delta = (event.position().x() - self._drag_x) / max(1.0, right - left) * self._visible_duration()
                span = self._drag_end_time - self._drag_start_time
                raw_start = max(0.0, min(max(0.0, self._duration() - span), self._drag_start_time + delta))
                raw_end = raw_start + span
                snapped_start = self._snap_time(raw_start, {self._drag_idx, self._drag_next_idx})
                snapped_end = self._snap_time(raw_end, {self._drag_idx, self._drag_next_idx})
                if abs(snapped_start - raw_start) <= abs(snapped_end - raw_end):
                    start_time = max(0.0, min(max(0.0, self._duration() - span), snapped_start))
                    end_time = start_time + span
                else:
                    end_time = max(span, min(self._duration(), snapped_end))
                    start_time = end_time - span
                self._keys[self._drag_idx].time = start_time
                self._keys[self._drag_next_idx].time = end_time
                self.keyMoved.emit(self._drag_idx, start_time)
                self.keyMoved.emit(self._drag_next_idx, end_time)
                self._selected = self._drag_idx
                self.keySelected.emit(self._drag_idx)
            else:
                target_idx = self._drag_next_idx if self._drag_mode == "right" else self._drag_idx
                new_time = self._time_for_x(event.position().x())
                min_time, max_time = self._key_time_limits(target_idx)
                new_time = max(min_time, min(max_time, new_time))
                new_time = max(min_time, min(max_time, self._snap_time(new_time, {target_idx})))
                self._keys[target_idx].time = new_time
                self.keyMoved.emit(target_idx, new_time)
                if self._drag_mode == "right":
                    self._selected = self._drag_idx
                    self.keySelected.emit(self._drag_idx)
            self.update()
            return
        if self._lock_hit(event.position()) >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        segment_hit = self._segment_hit(event.position())
        if segment_hit:
            hit_mode, _idx = segment_hit
            if self._tool_mode == "blade":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor if hit_mode == "body" else Qt.CursorShape.SizeHorCursor)
            return
        if self._playhead_hit(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if self._ruler_hit(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if not self._visible_segment_indices():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self._dragging and self._drag_mode == "body" and 0 <= self._drag_idx < len(self._keys):
            selected_key = self._keys[self._drag_idx]
            self._keys.sort(key=lambda key: key.time)
            self._selected = self._keys.index(selected_key) if selected_key in self._keys else -1
            if self._selected >= 0:
                self.keySelected.emit(self._selected)
        self._dragging = False
        self._drag_idx = -1
        self._drag_next_idx = -1
        self._drag_mode = None
        self._range_drag_mode = None
        self._scrubbing_playhead = False
        self.unsetCursor()
        self.update()


    def _is_neutral_key(self, key):
        return False

    def _empty_text(self):
        return ui_text('ui_lipsync_no_keys')

    def _color_for_key(self, key):
        return QColor(P['accent'])

    def _label_for_key(self, key):
        return str(getattr(key, 'label', ''))

    def _format_time(self, value):
        return f'{value:g}'

    def _ensure_gap_before_segment(self, idx):
        return idx


class TimelineOverviewWidget(QWidget):
    viewRangeChanged = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list = []
        self._duration = 1.0
        self._view_start = 0.0
        self._view_end = 1.0
        self._dragging = False
        self._drag_mode: str | None = None
        self._drag_x = 0.0
        self._drag_start = 0.0
        self._drag_end = 1.0
        self.setFixedHeight(34)
        self.setMouseTracking(True)

    def set_data(self, keys: list, duration: float, view_start: float, view_end: float):
        self._keys = keys
        self._duration = max(0.001, float(duration or 1.0))
        self._view_start = max(0.0, min(self._duration, float(view_start)))
        self._view_end = max(self._view_start, min(self._duration, float(view_end)))
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(6, 8, max(1, self.width() - 12), 18)

    def _x_for_time(self, time_value: float) -> float:
        track = self._track_rect()
        return track.left() + track.width() * (time_value / self._duration)

    def _time_for_x(self, x: float) -> float:
        track = self._track_rect()
        ratio = max(0.0, min(1.0, (x - track.left()) / max(1.0, track.width())))
        return ratio * self._duration

    def _thumb_rect(self) -> QRectF:
        track = self._track_rect()
        left = self._x_for_time(self._view_start)
        right = self._x_for_time(self._view_end)
        return QRectF(left, track.top() - 4, max(14.0, right - left), track.height() + 8)

    def _thumb_hit_mode(self, pos) -> str | None:
        thumb = self._thumb_rect().adjusted(-4, -4, 4, 4)
        if not thumb.contains(pos):
            return None
        edge = 9
        if abs(pos.x() - thumb.left()) <= edge:
            return "left"
        if abs(pos.x() - thumb.right()) <= edge:
            return "right"
        return "move"

    def _emit_view(self, start: float, end: float):
        span = max(0.03, end - start)
        start = max(0.0, min(self._duration - span, start))
        end = start + span
        self._view_start = start
        self._view_end = end
        self.viewRangeChanged.emit(start, end)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        bg = QColor(P.get("bg_card", P["bg_panel"]))
        bg.setAlpha(70)
        painter.fillRect(rect, bg)
        track = self._track_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        track_color = QColor(P["mid"])
        track_color.setAlpha(105)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 3, 3)

        for start, end, color in self._segments():
            x1 = self._x_for_time(start)
            x2 = self._x_for_time(end)
            color = QColor(color)
            color.setAlpha(170)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x1, track.top() + 3, max(2.0, x2 - x1), track.height() - 6), 2, 2)

        thumb = self._thumb_rect()
        thumb_fill = QColor(P.get("bg_card_hov", P["bg_panel"]))
        thumb_fill.setAlpha(108)
        thumb_border = QColor(P["border_hov"] if self._dragging else P["border"])
        thumb_border.setAlpha(195)
        painter.setBrush(thumb_fill)
        painter.setPen(QPen(thumb_border, 1))
        painter.drawRoundedRect(thumb, 5, 5)
        highlight = QColor(P["shine"])
        highlight.setAlpha(45)
        painter.setBrush(highlight)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(thumb.adjusted(2, 2, -2, -thumb.height() / 2), 4, 4)
        grip_color = QColor(P["shine"])
        grip_color.setAlpha(215)
        painter.setBrush(grip_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(thumb.left() + 5, thumb.top() + 6, 2, thumb.height() - 12), 1, 1)
        painter.drawRoundedRect(QRectF(thumb.right() - 7, thumb.top() + 6, 2, thumb.height() - 12), 1, 1)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_mode = self._thumb_hit_mode(event.position())
        if self._drag_mode is None:
            return
        self._dragging = True
        self._drag_x = event.position().x()
        self._drag_start = self._view_start
        self._drag_end = self._view_end
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._drag_mode == "move" else Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            mode = self._thumb_hit_mode(event.position())
            if mode in ("left", "right"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif mode == "move":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        delta = self._time_for_x(event.position().x()) - self._time_for_x(self._drag_x)
        if self._drag_mode == "move":
            span = self._drag_end - self._drag_start
            self._emit_view(self._drag_start + delta, self._drag_start + delta + span)
        elif self._drag_mode == "left":
            self._emit_view(min(self._drag_end - 0.03, self._drag_start + delta), self._drag_end)
        elif self._drag_mode == "right":
            self._emit_view(self._drag_start, max(self._drag_start + 0.03, self._drag_end + delta))

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._drag_mode = None
        self.unsetCursor()


    def _segments(self):
        return [(max(0., key.time), max(0., key.time), QColor(P['text_dim'])) for key in self._keys]
