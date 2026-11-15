"""Native texture inspection on the shared image surface."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QCheckBox, QSlider
from core.design_tokens import LayoutRole, TypeSize, mono_font
from core.style_helpers import ss_dim_label, ss_check, ss_slider
from core.ui.editor_widgets import configure_layout, configure_input
from core.ui.image_preview import ImagePreview
from core.texture_tools import inspect_channel, compare_pixels
from core.translations import ui_text


class TexturePreview(QWidget):
    color_picked = pyqtSignal(str)
    level_changed = pyqtSignal(int)
    face_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pil = self._original = None
        self._info = ''
        self._color_pick_enabled = False
        layout = configure_layout(QVBoxLayout(self), LayoutRole.PAGE)
        self.channel = configure_input(QComboBox())
        for key, value in (('texture_channel_rgba', 'rgba'), ('texture_channel_rgb', 'rgb'),
                           ('texture_channel_r', 'r'), ('texture_channel_g', 'g'),
                           ('texture_channel_b', 'b'), ('texture_channel_a', 'a')):
            self.channel.addItem(ui_text(key), value)
        self.channel.setToolTip(ui_text('texture_channel_hint'))
        self.mode = configure_input(QComboBox())
        for key, value in (('texture_view_current', 'current'), ('texture_view_original', 'original'),
                           ('texture_view_split', 'split'), ('texture_view_difference', 'difference')):
            self.mode.addItem(ui_text(key), value)
        self.mode.setToolTip(ui_text('texture_comparison_hint'))
        self.level = configure_input(QComboBox())
        self.level.setToolTip(ui_text('texture_mip_hint'))
        self.face = configure_input(QComboBox())
        self.face.hide()
        for combo in (self.channel, self.mode, self.level, self.face):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(5)
            combo.setMinimumWidth(0)
            layout.addWidget(combo)
        self.split = QSlider(Qt.Orientation.Horizontal)
        self.split.setRange(0, 100)
        self.split.setValue(50)
        self.split.setStyleSheet(ss_slider())
        self.split.setAccessibleName(ui_text('texture_split_position'))
        self.split.setToolTip(ui_text('texture_split_position'))
        layout.addWidget(self.split)
        self.surface = ImagePreview(maximum_height=None)
        layout.addWidget(self.surface, 1)
        self.surface.set_checkerboard(True)
        self.surface.set_smooth(False)
        options = configure_layout(QVBoxLayout(), LayoutRole.FIELD)
        self.checker = QCheckBox(ui_text('texture_transparency'))
        self.smooth = QCheckBox(ui_text('texture_smooth'))
        self.checker.setChecked(True)
        for check in (self.checker, self.smooth):
            check.setStyleSheet(ss_check())
            options.addWidget(check)
        layout.addLayout(options)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setFont(mono_font(TypeSize.HINT))
        self.status.setStyleSheet(ss_dim_label())
        layout.addWidget(self.status)
        self.notice = QLabel(ui_text('texture_preview_scope'))
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(ss_dim_label())
        layout.addWidget(self.notice)
        self.channel.currentIndexChanged.connect(self._render)
        self.mode.currentIndexChanged.connect(self._render)
        self.split.valueChanged.connect(self._render)
        self.level.currentIndexChanged.connect(lambda _: self.level_changed.emit(self.level.currentData() or 0))
        self.face.currentIndexChanged.connect(lambda _: self.face_changed.emit(self.face.currentData() or 0))
        self.checker.toggled.connect(self.surface.set_checkerboard)
        self.smooth.toggled.connect(self.surface.set_smooth)
        self.surface.view.pixel_hovered.connect(self._inspect)
        self.surface.view.pixel_clicked.connect(self._pick)
        self.show_image(None)

    def set_levels(self, width, height, count):
        previous = self.level.currentData() or 0
        self.level.blockSignals(True)
        self.level.clear()
        for level in range(count):
            self.level.addItem(ui_text('texture_mip_level', level=level,
                                      width=max(1, width >> level), height=max(1, height >> level)), level)
        self.level.setCurrentIndex(min(previous, count - 1))
        self.level.blockSignals(False)

    def set_faces(self, count):
        if self.face.count() == count:
            return
        self.face.blockSignals(True)
        self.face.clear()
        for face in range(count):
            self.face.addItem(ui_text('texture_cube_face', face=face), face)
        self.face.setVisible(count > 1)
        self.face.blockSignals(False)

    def show_image(self, img, info='', *, original=None, reset_view=False):
        self._pil, self._original, self._info = img, original, info
        self.mode.blockSignals(True)
        for index in range(1, self.mode.count()):
            self.mode.model().item(index).setEnabled(original is not None)
        if original is None:
            self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        for control in (self.channel, self.mode, self.level, self.checker, self.smooth):
            control.setEnabled(img is not None)
        self._render(preserve_view=not reset_view)

    def _render(self, *_, preserve_view=True):
        mode = self.mode.currentData()
        self.split.setVisible(mode == 'split' and self._pil is not None)
        if self._pil is None:
            self.surface.set_image(None)
            self.status.setText(self._info or ui_text('ui_texture_no_texture_selected'))
            return
        current = inspect_channel(self._pil, self.channel.currentData())
        original = inspect_channel(self._original, self.channel.currentData()) if self._original else None
        self.surface.set_image(compare_pixels(current, original, mode, self.split.value()), preserve_view=preserve_view)
        self.status.setText(self._info)

    def set_color_pick_enabled(self, enabled):
        self._color_pick_enabled = bool(enabled)
        view = self.surface.view
        view.pixel_pick = bool(enabled)
        if enabled:
            view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            view.viewport().unsetCursor()

    def _inspect(self, point):
        image = self._original if self.mode.currentData() == 'original' else self._pil
        if image is not None and 0 <= point.x() < image.width and 0 <= point.y() < image.height:
            r, g, b, a = image.getpixel((point.x(), point.y()))
            self.status.setText(f'X {point.x()}  Y {point.y()}   RGBA {r}, {g}, {b}, {a}   #{r:02X}{g:02X}{b:02X}')

    def _pick(self, point):
        # Pick unmodified source colours, never the checker or channel visualization.
        image = self._original if self.mode.currentData() == 'original' else self._pil
        if self._color_pick_enabled and image is not None and 0 <= point.x() < image.width and 0 <= point.y() < image.height:
            r, g, b, _ = image.getpixel((point.x(), point.y()))
            self.color_picked.emit(f'#{r:02X}{g:02X}{b:02X}')
        self.set_color_pick_enabled(False)
