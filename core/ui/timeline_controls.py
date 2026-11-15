"""Timeline navigation controls shared with the original LipSync editor."""
from PyQt6.QtCore import QSize, Qt, QSignalBlocker
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSlider
from core.design_tokens import LayoutRole, Size
from core.icons import _themed_icon
from core.style_helpers import ss_dim_label, ss_slider
from core.themes import P
from core.translations import ui_text
from core.ui.editor_widgets import configure_button, configure_layout


def timeline_icon_button(tooltip, icon_name, callback, *, danger=False):
    button = configure_button(QPushButton(), danger=danger)
    button.setFixedWidth(34)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setIcon(_themed_icon(icon_name, color=P.get('button_text', P['text_main']), size=16))
    button.setIconSize(QSize(17, 17))
    button.clicked.connect(callback)
    return button


class TimelineZoomControls(QWidget):
    def __init__(self, timeline=None, parent=None, *, show_fit=True):
        super().__init__(parent)
        self.timeline = None
        layout = configure_layout(QHBoxLayout(self), LayoutRole.FIELD)
        for text in ('−', '+'):
            label = QLabel(text)
            label.setStyleSheet(ss_dim_label())
            label.setFixedWidth(Size.SCROLLBAR)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if text == '−':
                layout.addWidget(label)
                self.slider = QSlider(Qt.Orientation.Horizontal)
                self.slider.setRange(0, 100)
                self.slider.setFixedWidth(92)
                self.slider.setFixedHeight(Size.COMPACT_CONTROL)
                self.slider.setToolTip(ui_text('ui_lipsync_zoom_fit'))
                self.slider.setAccessibleName(ui_text('motion_zoom'))
                self.slider.setStyleSheet(ss_slider())
                self.slider.valueChanged.connect(self._zoom_changed)
                layout.addWidget(self.slider)
            else:
                layout.addWidget(label)
        self.fit_button = None
        if show_fit:
            self.fit_button = timeline_icon_button(ui_text('ui_lipsync_view_fit'), 'fa6s.expand', self._fit)
            layout.addWidget(self.fit_button)
        if timeline is not None:
            self.bind(timeline)

    def bind(self, timeline):
        self.timeline = timeline
        timeline.viewRangeChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        if self.timeline is not None:
            with QSignalBlocker(self.slider):
                self.slider.setValue(round(self.timeline.zoom_normalized() * 100))

    def _zoom_changed(self, value):
        if self.timeline is not None:
            self.timeline.set_zoom_normalized(value / 100.)

    def _fit(self):
        if self.timeline is not None:
            self.timeline.fit_view()
