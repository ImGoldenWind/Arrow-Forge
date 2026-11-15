"""Exact integer stepping alongside an ordinary, lossless text input.

The caller owns validation and commit. Stepping never clamps invalid manual
input or converts it to zero, and covers u32 ranges that QSpinBox cannot hold.
"""
from decimal import Decimal, InvalidOperation
import math
import struct

from PyQt6.QtCore import Qt, pyqtSignal, QSignalBlocker
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QSlider, QSpinBox, QSizePolicy

from core.design_tokens import LayoutRole, Size
from core.translations import ui_text
from core.ui.editor_widgets import configure_layout, configure_button, configure_input
from core.design_tokens import TypeSize, ui_font
from core.style_helpers import ss_field_label, ss_slider


class SliderInput(QWidget):
    """Bounded authoring value with an exact input and an optional data gradient."""
    value_changed = pyqtSignal(int)

    def __init__(self, label, minimum, maximum, default, parent=None):
        super().__init__(parent)
        self._default = default
        layout = configure_layout(QVBoxLayout(self), LayoutRole.FIELD)
        header = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self.label = QLabel(label)
        self.label.setFont(ui_font(TypeSize.LABEL))
        self.label.setStyleSheet(ss_field_label())
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setVisible(bool(label))
        header.addWidget(self.label, 1)
        self.input = configure_input(QSpinBox())
        self.input.setRange(minimum, maximum)
        self.input.setValue(default)
        self.input.setKeyboardTracking(False)
        self.input.setMinimumWidth(88)
        self.input.setMaximumWidth(110)
        self.input.setAccessibleName(label)
        self.label.setBuddy(self.input)
        header.addWidget(self.input)
        layout.addLayout(header)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(default)
        self._slider.setStyleSheet(ss_slider())
        self._slider.setAccessibleName(label)
        layout.addWidget(self._slider)
        self.input.valueChanged.connect(self._slider.setValue)
        self._slider.valueChanged.connect(self._changed)

    def _changed(self, value):
        self.input.setValue(value)
        self.value_changed.emit(value)

    @property
    def value(self):
        return self._slider.value()

    def reset(self):
        self._slider.setValue(self._default)


class IntegerStepper(QWidget):
    def __init__(self, edit, minimum, maximum, parent=None):
        super().__init__(parent)
        self.edit, self.minimum, self.maximum = edit, minimum, maximum
        layout = configure_layout(QHBoxLayout(self), LayoutRole.FIELD)
        layout.addWidget(edit, 1)
        self.decrease = configure_button(QPushButton('−'))
        self.increase = configure_button(QPushButton('+'))
        for button, direction, key in ((self.decrease, -1, 'number_decrease'),
                                        (self.increase, 1, 'number_increase')):
            button.setFixedWidth(Size.CONTROL)
            button.setAccessibleName(ui_text(key))
            button.setToolTip(ui_text(key))
            button.clicked.connect(lambda _, delta=direction: self.step(delta))
            layout.addWidget(button)
        edit.textChanged.connect(self.refresh)
        self.refresh()

    def value(self):
        text = self.edit.text()
        try:
            value = int(text, 16 if text.lower().startswith('0x') else 10)
            return value if self.minimum <= value <= self.maximum else None
        except ValueError:
            return None

    def step(self, delta):
        value = self.value()
        if value is not None and self.minimum <= value + delta <= self.maximum and not self.edit.isReadOnly():
            self.edit.setText(str(value + delta))

    def refresh(self):
        value = self.value()
        self.decrease.setEnabled(value is not None and value > self.minimum and not self.edit.isReadOnly())
        self.increase.setEnabled(value is not None and value < self.maximum and not self.edit.isReadOnly())


class FloatStepper(IntegerStepper):
    """Float32 storage stepping; manual input remains lossless and unclamped.

    Step size is an editing convenience supplied by the owner, not a game limit.
    Decimal arithmetic avoids changing unrelated digits when adding a small step.
    """
    def __init__(self, edit, step, parent=None):
        self.increment = Decimal(str(step))
        if not self.increment.is_finite() or self.increment <= 0:
            raise ValueError('A positive finite step is required.')
        super().__init__(edit, -3.4028234663852886e38, 3.4028234663852886e38, parent)

    def value(self):
        try:
            value = Decimal(self.edit.text())
            return value if value.is_finite() and self.minimum <= value <= self.maximum else None
        except InvalidOperation:
            return None

    def step(self, delta):
        value = self.value()
        if value is None or self.edit.isReadOnly():
            return
        candidate = value + self.increment * delta
        try:
            packed = struct.unpack('<f', struct.pack('<f', float(candidate)))[0]
            if math.isfinite(packed) and self.minimum <= candidate <= self.maximum:
                self.edit.setText(str(candidate))
        except (OverflowError, struct.error):
            return


class FloatSliderInput(QWidget):
    """A convenience drag span alongside lossless, unrestricted float entry.

    The owner supplies display units and validates/commits storage conversion.
    Out-of-span manual values and incomplete text never get clamped by the slider.
    """
    value_changed = pyqtSignal()

    def __init__(self, edit, minimum, maximum, step, parent=None):
        super().__init__(parent)
        self.edit = edit
        self.minimum, self.maximum = Decimal(str(minimum)), Decimal(str(maximum))
        layout = configure_layout(QVBoxLayout(self), LayoutRole.FIELD)
        self.stepper = FloatStepper(edit, step)
        layout.addWidget(self.stepper)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        positions = round((self.maximum - self.minimum) / self.stepper.increment)
        self.slider.setRange(0, max(1, min(0x7fffffff, positions)))
        self.slider.setStyleSheet(ss_slider())
        self.slider.setAccessibleName(edit.accessibleName())
        self.slider.setToolTip(ui_text('number_slider_span', minimum=minimum, maximum=maximum))
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._drag)
        edit.textChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        value = self.stepper.value()
        self.slider.setEnabled(value is not None and not self.edit.isReadOnly())
        if value is not None:
            ratio = (value - self.minimum) / (self.maximum - self.minimum)
            with QSignalBlocker(self.slider):
                self.slider.setValue(round(max(Decimal(0), min(Decimal(1), ratio)) * self.slider.maximum()))

    def _drag(self, position):
        value = self.minimum + (self.maximum - self.minimum) * position / self.slider.maximum()
        self.edit.setText(format(value.normalize(), 'f'))
        self.value_changed.emit()
