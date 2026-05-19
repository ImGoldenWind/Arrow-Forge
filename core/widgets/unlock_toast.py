from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout

from core.style_helpers import ss_unlock_toast


class UnlockToast(QFrame):
    def __init__(self, parent, title: str, message: str):
        super().__init__(parent)
        self.setObjectName("UnlockToast")
        self.setFixedSize(316, 86)
        self.setStyleSheet(ss_unlock_toast())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 12)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("UnlockToastTitle")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_lbl.setWordWrap(False)
        layout.addWidget(title_lbl)

        body_lbl = QLabel(message)
        body_lbl.setObjectName("UnlockToastBody")
        body_lbl.setFont(QFont("Segoe UI", 11))
        body_lbl.setWordWrap(True)
        layout.addWidget(body_lbl)

        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self._effect = effect
        self._animations = []

    def _target_pos(self, index: int = 0, bottom_offset: int = 0):
        parent = self.parentWidget()
        margin = 18
        stack_gap = 10
        x = max(margin, parent.width() - self.width() - margin)
        y = parent.height() - self.height() - margin - bottom_offset - index * (self.height() + stack_gap)
        y = max(margin, y)
        return QPoint(x, y)

    def show_animated(self, index: int = 0, bottom_offset: int = 0):
        parent = self.parentWidget()
        if parent is None:
            self.show()
            return
        self._stack_index = index
        self._bottom_offset = bottom_offset
        end = self._target_pos(index, bottom_offset)
        y = end.y()
        start = QPoint(parent.width() + 6, y)
        self.move(start)
        self.raise_()
        self.show()

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(360)
        slide.setStartValue(start)
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.OutBack)

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(240)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animations.extend([slide, fade])
        slide.start()
        fade.start()
        QTimer.singleShot(4300, self._hide_animated)

    def move_to_anchor(self, index: int | None = None, bottom_offset: int | None = None):
        parent = self.parentWidget()
        if parent is None:
            return
        if index is None:
            index = getattr(self, "_stack_index", 0)
        if bottom_offset is None:
            bottom_offset = getattr(self, "_bottom_offset", 0)
        self._stack_index = index
        self._bottom_offset = bottom_offset
        self.move(self._target_pos(index, bottom_offset))
        self.raise_()

    def _hide_animated(self):
        parent = self.parentWidget()
        if parent is None:
            self.deleteLater()
            return
        end = QPoint(parent.width() + 6, self.y())

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(260)
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.InCubic)

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(220)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)

        self._animations.extend([slide, fade])
        fade.finished.connect(self.deleteLater)
        slide.start()
        fade.start()
