"""Channel-separated, seekable PCM overview with the shared timeline zoom API."""
import math

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.design_tokens import TypeSize, mono_font
from core.themes import P
from core.translations import ui_text


class AudioWaveform(QWidget):
    seekRequested = pyqtSignal(float)
    viewRangeChanged = pyqtSignal()
    loopEditRequested = pyqtSignal(object)
    loopSelectionChanged = pyqtSignal(int)  # 0: off, 1: first point, 2: second point

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMinimumWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName(ui_text('awb_waveform'))
        self.setToolTip(ui_text('awb_waveform_hint'))
        self.envelope = None
        self.position = 0.
        self.loop = None
        self.loop_editable = False
        self._loop_drag = None
        self.loop_min_samples = 1
        self._select_loop = False
        self._selection_anchor = None
        self._selection_current = None
        self._start, self._span = 0., 1.

    def set_audio(self, envelope, loop=None):
        self.set_loop_selection_enabled(False)
        self.envelope, self.loop = envelope, loop
        self._loop_drag = None
        self.position = 0.
        self.fit_view()

    def clear(self):
        self.set_loop_selection_enabled(False)
        self.envelope = None
        self._loop_drag = None
        self.update()

    def set_position(self, seconds):
        self.position = max(0., seconds)
        self.update()

    def fit_view(self):
        self._start, self._span = 0., 1.
        self.viewRangeChanged.emit()
        self.update()

    def zoom_normalized(self):
        return -math.log2(self._span) / 6

    def set_zoom_normalized(self, value):
        duration = self.envelope.duration if self.envelope else 0
        anchor = self.position / duration if duration else self._start + self._span / 2
        self._span = 2 ** (-6 * max(0., min(1., value)))
        self._start = max(0., min(1 - self._span, anchor - self._span / 2))
        self.viewRangeChanged.emit()
        self.update()

    def wheelEvent(self, event):
        self.set_zoom_normalized(self.zoom_normalized() + event.angleDelta().y() / 2400)
        event.accept()

    def _seek(self, x):
        if self.envelope:
            ratio = self._start + self._span * max(0., min(1., x / max(1, self.width())))
            seconds = ratio * self.envelope.duration
            self.set_position(seconds)
            self.seekRequested.emit(seconds)

    def set_loop_selection_enabled(self, enabled):
        self._select_loop = bool(enabled)
        self._selection_anchor = self._selection_current = None
        self._loop_drag = None
        self.loopSelectionChanged.emit(1 if enabled else 0)
        self.update()

    @property
    def loop_selection_active(self):
        return self._select_loop

    def _sample_at(self, x):
        ratio = self._start + self._span * max(0., min(1., x / max(1, self.width())))
        return max(0, min(self.envelope.frames, round(ratio * self.envelope.frames)))

    def _finish_selection(self, sample):
        start, end = sorted((self._selection_anchor, sample))
        if end - start < self.loop_min_samples:
            return False
        self.set_loop_selection_enabled(False)
        self.loopEditRequested.emit((start, end))
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self.envelope and self._select_loop:
                sample = self._sample_at(event.position().x())
                if self._selection_anchor is None:
                    self._selection_anchor = self._selection_current = sample
                    self.loopSelectionChanged.emit(2)
                    self.update()
                else:
                    self._finish_selection(sample)
                return
            if self.envelope and self.loop and self.loop_editable and event.position().y() < 22:
                for index, seconds in enumerate(self.loop):
                    x = (seconds / self.envelope.duration - self._start) / self._span * self.width()
                    if abs(event.position().x() - x) <= 10:
                        self._loop_drag = (index, self.loop)
                        return
            self._seek(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._select_loop and self._selection_anchor is not None:
                self._selection_current = self._sample_at(event.position().x())
                self.update()
                return
            if self._loop_drag is not None:
                index, original = self._loop_drag
                sample = round((self._start + self._span * event.position().x() / max(1, self.width())) * self.envelope.frames)
                start, end = (round(t * self.envelope.sample_rate) for t in self.loop)
                if index == 0:
                    start = max(0, min(end - self.loop_min_samples, sample))
                else:
                    end = max(start + self.loop_min_samples, min(self.envelope.frames, sample))
                self.loop = (start / self.envelope.sample_rate, end / self.envelope.sample_rate)
                self.update()
            else:
                self._seek(event.position().x())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._select_loop and self._selection_anchor is not None:
            self._finish_selection(self._sample_at(event.position().x()))
            return
        if event.button() == Qt.MouseButton.LeftButton and self._loop_drag is not None:
            changed = self.loop != self._loop_drag[1]
            self._loop_drag = None
            if changed:
                self.loopEditRequested.emit(tuple(round(t * self.envelope.sample_rate) for t in self.loop))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._select_loop:
            self.set_loop_selection_enabled(False)
            return
        if event.key() == Qt.Key.Key_Escape and self._loop_drag is not None:
            self.loop = self._loop_drag[1]
            self._loop_drag = None
            self.update()
            return
        if not self.envelope:
            return super().keyPressEvent(event)
        duration = self.envelope.duration
        targets = {Qt.Key.Key_Home: 0., Qt.Key.Key_End: duration,
                   Qt.Key.Key_Left: max(0., self.position - duration * self._span / 100),
                   Qt.Key.Key_Right: min(duration, self.position + duration * self._span / 100)}
        if event.key() in targets:
            self.set_position(targets[event.key()])
            self.seekRequested.emit(self.position)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(P['bg_card']))
        painter.setFont(mono_font(TypeSize.HINT))
        if self.envelope is None:
            painter.setPen(QColor(P['text_dim']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, ui_text('awb_waveform_empty'))
            return
        audio = self.envelope
        width, height = self.width(), self.height() - 24
        duration = audio.duration
        def x_at(seconds):
            return (seconds / duration - self._start) / self._span * width
        if self.loop:
            left, right = (x_at(value) for value in self.loop)
            tint = QColor(P['accent']); tint.setAlpha(28)
            painter.fillRect(QRectF(left, 0, right - left, height), tint)
            painter.setPen(QPen(QColor(P['text_sec']), 1, Qt.PenStyle.DashLine))
            for x in (left, right):
                painter.drawLine(int(x), 0, int(x), height)
                if self.loop_editable:
                    painter.fillRect(QRectF(x - 4, 0, 8, 18), QColor(P['accent']))
        if self._selection_anchor is not None:
            left = x_at(self._selection_anchor / audio.sample_rate)
            right = x_at(self._selection_current / audio.sample_rate)
            tint = QColor(P['accent']); tint.setAlpha(45)
            painter.fillRect(QRectF(min(left, right), 0, abs(right - left), height), tint)
            painter.setPen(QPen(QColor(P['accent']), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(left), 0, int(left), height)
            painter.drawLine(int(right), 0, int(right), height)
        lane = height / audio.channels
        count = len(audio.low)
        first = int(self._start * audio.frames / audio.bin_size)
        last = min(count, math.ceil((self._start + self._span) * audio.frames / audio.bin_size))
        for channel in range(audio.channels):
            mid, scale = (channel + .5) * lane, lane * .44
            painter.setPen(QPen(QColor(P['border']), 1))
            painter.drawLine(0, int(mid), width, int(mid))
            painter.setPen(QColor(P['accent']))
            for index in range(first, last):
                x = int((index * audio.bin_size / audio.frames - self._start) / self._span * width)
                painter.drawLine(x, int(mid - audio.high[index, channel] * scale),
                                 x, int(mid - audio.low[index, channel] * scale))
            painter.setPen(QColor(P['text_sec']))
            painter.drawText(6, int(channel * lane) + 14, str(channel + 1))
        painter.setPen(QColor(P['text_dim']))
        for tick in range(5):
            x = tick * width / 4
            label = f'{(self._start + self._span * tick / 4) * duration:.2f}'
            label_width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(int(min(max(0, x - label_width / 2), width - label_width)), self.height() - 5, label)
        painter.setPen(QPen(QColor(P['text_main']), 1))
        x = int(x_at(self.position))
        painter.drawLine(x, 0, x, height)
        if self.hasFocus():
            painter.setPen(QColor(P['accent']))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
