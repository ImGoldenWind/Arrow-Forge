"""
ASBR Texture Editor
Full-featured XFBIN texture editor with:
  • Thumbnail grid with filter / search
  • Large zoomable preview
  • Live quick-edit adjustments (brightness / contrast / saturation / hue)
  • Flip, rotate
  • Export single texture as DDS or PNG
  • Export all textures at once
  • Replace texture from DDS / PNG / NUT file
  • Port textures from another XFBIN
  • Save modified XFBIN
"""

import os
import io

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSlider,
    QFileDialog, QMessageBox, QDialog, QListWidget, QListWidgetItem,
    QAbstractItemView, QCheckBox, QSizePolicy, QProgressDialog,
    QToolButton, QSpacerItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QThread, QObject
from PyQt6.QtGui import QFont, QPixmap, QImage, QCursor, QColor, QPainter

from PIL import Image, ImageEnhance, ImageOps, ImageFilter

from core.themes import P
from core.style_helpers import (
    TOOLBAR_BTN_H, TOOLBAR_H,
    ss_bg_dark, ss_bg_panel, ss_btn, ss_dim_label,
    ss_check, ss_field_label, ss_gradient_slider, ss_input,
    ss_error_label, ss_file_label, ss_file_label_loaded, ss_main_label,
    ss_scrollarea, ss_scrollarea_transparent, ss_section_label, ss_slider,
    ss_search, ss_sep, ss_sidebar_btn, ss_sidebar_frame, ss_toggle_btn, ss_transparent,
)
from core.icons import _pil_to_qpixmap
from parsers.texture_xfbin_parser import (
    TextureEntry, load_xfbin, save_xfbin,
    replace_texture_from_file, apply_pil_edits_to_entry,
    export_entry_dds, export_entry_png,
    load_xfbin_for_port, port_entries_into_xfbin,
)
from core.translations import ui_text

THUMB_SIZE    = 100
THUMB_PADDING = 6
THUMB_COLS    = 2


# Shared style helpers
def _ss_lineedit():
    return (
        f"QLineEdit {{background:{P['bg_card']}; border:1px solid {P['border']}; "
        f"color:{P['text_main']}; padding:3px 7px; border-radius:4px;}}"
        f"QLineEdit:focus {{border:1px solid {P['accent']};}}"
    )


def _ss_slider():
    return (
        f"QSlider::groove:horizontal {{height:4px; background:{P['mid']}; border-radius:2px;}}"
        f"QSlider::handle:horizontal {{background:{P['accent']}; width:12px; height:12px; "
        f"margin:-4px 0; border-radius:6px;}}"
        f"QSlider::sub-page:horizontal {{background:{P['accent']}; border-radius:2px;}}"
    )


def _make_sep():
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFixedHeight(1)
    sep.setStyleSheet(ss_sep())
    return sep


# Thumbnail widget
class _Thumb(QFrame):
    clicked = pyqtSignal(object)   # emits TextureEntry

    _NORMAL = None
    _SELECT = None

    def _style_normal(self):
        return (
            f"_Thumb {{background:{P['bg_card']}; border:2px solid {P['border']}; border-radius:6px;}}"
            f"_Thumb:hover {{background:{P['bg_card_hov']}; border:2px solid {P['secondary']};}}"
        )

    def _style_select(self):
        return (
            f"_Thumb {{background:{P['bg_card_hov']}; border:2px solid {P['accent']}; border-radius:6px;}}"
        )

    def __init__(self, entry: TextureEntry, parent=None):
        super().__init__(parent)
        self._entry    = entry
        self._selected = False
        self.setFixedSize(THUMB_SIZE + THUMB_PADDING * 2,
                          THUMB_SIZE + THUMB_PADDING * 2 + 28)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._style_normal())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(THUMB_PADDING, THUMB_PADDING, THUMB_PADDING, 3)
        lay.setSpacing(2)

        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(ui_text("ui_texture_background_transparent_border_none"))
        self._img_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._img_lbl)

        self._name_lbl = QLabel(_truncate(entry.name, 14))
        self._name_lbl.setFont(QFont("Consolas", 8))
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(f"color:{P['text_main']}; background:transparent; border:none;")
        self._name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._name_lbl)

        # Build pixmap in background so the grid appears quickly
        if entry.pil_image:
            QTimer.singleShot(0, self._set_thumb)
        else:
            self._img_lbl.setText("?")
            self._img_lbl.setStyleSheet(
                f"color:{P['text_dim']}; font-size:24px; background:transparent; border:none;"
            )

    def _set_thumb(self):
        if self._entry.pil_image is None:
            return
        thumb = self._entry.pil_image.copy()
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        # Checkerboard background for alpha
        bg = _checkerboard(THUMB_SIZE, THUMB_SIZE)
        bg.paste(thumb, ((THUMB_SIZE - thumb.width) // 2, (THUMB_SIZE - thumb.height) // 2),
                 thumb if thumb.mode == 'RGBA' else None)
        self._img_lbl.setPixmap(_pil_to_qpixmap(bg))

    def set_selected(self, v: bool):
        self._selected = v
        self.setStyleSheet(self._style_select() if v else self._style_normal())

    def update_image(self):
        self._set_thumb()

    def mousePressEvent(self, ev):
        self.clicked.emit(self._entry)
        super().mousePressEvent(ev)


def _checkerboard(w: int, h: int, block: int = 8) -> Image.Image:
    img = Image.new('RGBA', (w, h))
    c1, c2 = (180, 180, 180, 255), (120, 120, 120, 255)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = c1 if ((x // block + y // block) % 2 == 0) else c2
    return img


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + '…'


# Thumbnail grid
class _ThumbnailGrid(QWidget):
    texture_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[TextureEntry] = []
        self._thumbs:  list[_Thumb]       = []
        self._active:  _Thumb | None      = None
        self._filter   = ''

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Filter bar
        fbar = QWidget()
        fbar.setFixedHeight(38)
        fbar.setStyleSheet(f"background:{P['bg_panel']};")
        fl   = QHBoxLayout(fbar)
        fl.setContentsMargins(8, 4, 8, 4)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(ui_text("ui_texture_filter_textures"))
        self._filter_edit.setFont(QFont("Consolas", 10))
        self._filter_edit.setStyleSheet(_ss_lineedit())
        self._filter_edit.textChanged.connect(self._on_filter)
        fl.addWidget(self._filter_edit)
        root.addWidget(fbar)

        root.addWidget(_make_sep())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea {{background:{P['bg_dark']}; border:none;}}"
            f"QScrollBar:vertical {{background:{P['bg_dark']}; width:8px; border-radius:4px;}}"
            f"QScrollBar::handle:vertical {{background:{P['mid']}; border-radius:4px; min-height:20px;}}"
            f"QScrollBar::handle:vertical:hover {{background:{P['secondary']};}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{height:0; border:none;}}"
        )

        self._container = QWidget()
        self._container.setStyleSheet(f"background:{P['bg_dark']};")
        self._grid_lay  = QGridLayout(self._container)
        self._grid_lay.setContentsMargins(8, 8, 8, 8)
        self._grid_lay.setSpacing(6)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._count_lbl = QLabel(ui_text("ui_texture_0_textures"))
        self._count_lbl.setFont(QFont("Segoe UI", 9))
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(
            f"color:{P['text_dim']}; padding:3px; background:{P['bg_panel']};"
        )
        root.addWidget(self._count_lbl)

    def load(self, entries: list[TextureEntry]):
        self._entries = entries
        self._active  = None
        self._rebuild()

    def refresh_active_thumb(self):
        if self._active:
            self._active.update_image()

    def _on_filter(self, text: str):
        self._filter = text.lower()
        self._rebuild()

    def _rebuild(self):
        # Clear old thumbs
        for th in self._thumbs:
            th.setParent(None)
        self._thumbs.clear()
        self._active = None

        visible = [
            e for e in self._entries
            if not self._filter or self._filter in e.name.lower()
            or self._filter in e.format_name.lower()
        ]

        for idx, entry in enumerate(visible):
            th = _Thumb(entry, self._container)
            th.clicked.connect(self._on_thumb_click)
            self._grid_lay.addWidget(th, idx // THUMB_COLS, idx % THUMB_COLS)
            self._thumbs.append(th)

        self._count_lbl.setText(
            ui_text("ui_texture_value_value_textures", p0=len(visible), p1=len(self._entries))
        )

    def _on_thumb_click(self, entry: TextureEntry):
        for th in self._thumbs:
            th.set_selected(th._entry is entry)
            if th._entry is entry:
                self._active = th
        self.texture_selected.emit(entry)

    def select_entry(self, entry: TextureEntry):
        for th in self._thumbs:
            if th._entry is entry:
                self._on_thumb_click(entry)
                break


class _TextureList(QWidget):
    texture_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[TextureEntry] = []
        self._thumbs: list[QPushButton] = []
        self._active_entry: TextureEntry | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)
        self.setStyleSheet(ss_bg_panel())

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(ui_text("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        root.addWidget(self._search_entry)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(ss_scrollarea_transparent())

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, 1)

        self._count_lbl = QLabel(ui_text("ui_texture_0_textures"))
        self._count_lbl.setFont(QFont("Segoe UI", 9))
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(ss_dim_label())
        root.addWidget(self._count_lbl)

    def load(self, entries: list[TextureEntry]):
        self._entries = entries
        self._active_entry = None
        self._clear()
        for entry in entries:
            row = self._make_row(entry)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._thumbs.append(row)
        self._filter_list()

    def refresh_active_thumb(self):
        if self._active_entry is not None:
            self._refresh_row(self._active_entry)

    def select_entry(self, entry: TextureEntry):
        self._select(entry, emit=True)

    def _clear(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._list_layout.addStretch()
        self._thumbs.clear()

    def _make_row(self, entry: TextureEntry) -> QPushButton:
        btn = QPushButton()
        btn._entry = entry
        btn.setFixedHeight(44)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(ss_sidebar_btn(False))

        lay = QVBoxLayout(btn)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(0)

        name_lbl = QLabel(entry.name or "<unnamed>")
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn._name_lbl = name_lbl
        lay.addWidget(name_lbl)

        meta_lbl = QLabel(self._meta(entry))
        meta_lbl.setFont(QFont("Consolas", 11))
        meta_lbl.setStyleSheet(ss_dim_label())
        meta_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn._meta_lbl = meta_lbl
        lay.addWidget(meta_lbl)

        btn.clicked.connect(lambda checked=False, e=entry: self._select(e, emit=True))
        return btn

    def _meta(self, entry: TextureEntry) -> str:
        return f"{entry.format_name} / {entry.size_str}"

    def _select(self, entry: TextureEntry, emit: bool):
        self._active_entry = entry
        for row in self._thumbs:
            row.setStyleSheet(ss_sidebar_btn(row._entry is entry))
        if emit:
            self.texture_selected.emit(entry)

    def _refresh_row(self, entry: TextureEntry):
        for row in self._thumbs:
            if row._entry is entry:
                row._name_lbl.setText(entry.name or "<unnamed>")
                row._meta_lbl.setText(self._meta(entry))
                break
        self._filter_list()

    def _filter_list(self):
        query = self._search_entry.text().lower().strip()
        shown = 0
        for row in self._thumbs:
            entry = row._entry
            haystack = " ".join([
                entry.name,
                entry.file_path,
                entry.format_name,
                entry.size_str,
            ]).lower()
            visible = not query or query in haystack
            row.setVisible(visible)
            if visible:
                shown += 1
        total = len(self._entries)
        self._count_lbl.setText(ui_text("ui_texture_value_value_textures", p0=shown, p1=total))


# Preview panel
class _PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pil: Image.Image | None = None
        self._zoom = 1.0
        self.setStyleSheet(ss_bg_dark())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 12)
        lay.setSpacing(8)

        # Zoom controls
        zbar = QWidget()
        zbar.setFixedHeight(46)
        zbar.setStyleSheet(ss_bg_dark())
        zl = QHBoxLayout(zbar)
        zl.setContentsMargins(0, 8, 0, 8)
        zl.setSpacing(4)

        for label, delta in (("−", -0.25), ("+", 0.25)):
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setMinimumWidth(34)
            b.setFont(QFont("Segoe UI", 10))
            b.setStyleSheet(ss_btn())
            b.clicked.connect(lambda _, d=delta: self._change_zoom(d))
            zl.addWidget(b)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFont(QFont("Segoe UI", 10))
        self._zoom_lbl.setStyleSheet(ss_dim_label())
        zl.addWidget(self._zoom_lbl)

        fit_btn = QPushButton(ui_text("ui_texture_fit"))
        fit_btn.setFixedHeight(28)
        fit_btn.setMinimumWidth(42)
        fit_btn.setFont(QFont("Segoe UI", 10))
        fit_btn.setStyleSheet(ss_btn())
        fit_btn.clicked.connect(self._fit)
        zl.addWidget(fit_btn)

        orig_btn = QPushButton("1:1")
        orig_btn.setFixedHeight(28)
        orig_btn.setMinimumWidth(42)
        orig_btn.setFont(QFont("Segoe UI", 10))
        orig_btn.setStyleSheet(ss_btn())
        orig_btn.clicked.connect(lambda: self._set_zoom(1.0))
        zl.addWidget(orig_btn)
        zl.addStretch()
        lay.addWidget(zbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(ss_scrollarea())
        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._img_lbl)
        lay.addWidget(self._scroll, 1)

        self._info_lbl = QLabel(ui_text("ui_texture_no_texture_selected"))
        self._info_lbl.setFont(QFont("Consolas", 9))
        self._info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_lbl.setStyleSheet(ss_dim_label())
        lay.addWidget(self._info_lbl)

    def show_image(self, img: Image.Image | None, info: str = ''):
        self._pil = img
        self._info_lbl.setText(info)
        self._fit()

    def _fit(self):
        if self._pil is None:
            self._img_lbl.clear()
            return
        vp = self._scroll.viewport()
        vw, vh = vp.width() - 4, vp.height() - 4
        iw, ih = self._pil.size
        if iw == 0 or ih == 0:
            return
        ratio = min(vw / iw, vh / ih, 1.0)
        self._set_zoom(ratio)

    def _change_zoom(self, delta: float):
        self._set_zoom(max(0.1, min(8.0, self._zoom + delta)))

    def _set_zoom(self, z: float):
        self._zoom = z
        self._zoom_lbl.setText(ui_text("ui_texture_value", p0=int(z * 100)))
        self._render()

    def _render(self):
        if self._pil is None:
            self._img_lbl.clear()
            return
        w = max(1, int(self._pil.width  * self._zoom))
        h = max(1, int(self._pil.height * self._zoom))
        resized = self._pil.resize((w, h), Image.NEAREST if self._zoom > 1 else Image.LANCZOS)
        # Composite on checkerboard
        bg = _checkerboard(w, h)
        if resized.mode == 'RGBA':
            bg.paste(resized, (0, 0), resized)
        else:
            bg.paste(resized.convert('RGBA'), (0, 0))
        pm = _pil_to_qpixmap(bg)
        self._img_lbl.setPixmap(pm)
        self._img_lbl.setFixedSize(w, h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pil:
            QTimer.singleShot(50, self._fit)


# Slider row helper
class _SliderRow(QWidget):
    value_changed = pyqtSignal(int)

    def __init__(self, label: str, lo: int, hi: int, default: int, parent=None):
        super().__init__(parent)
        self._default = default
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setFixedWidth(88)
        lbl.setStyleSheet(ss_field_label())
        lay.addWidget(lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(lo, hi)
        self._slider.setValue(default)
        self._slider.setFixedHeight(30)
        self._slider.setStyleSheet(ss_slider())
        self._slider.valueChanged.connect(self._on_change)
        lay.addWidget(self._slider, 1)

        self._val_lbl = QLabel(str(default))
        self._val_lbl.setFont(QFont("Consolas", 9))
        self._val_lbl.setFixedWidth(36)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val_lbl.setStyleSheet(ss_main_label())
        lay.addWidget(self._val_lbl)

    def _on_change(self, v: int):
        self._val_lbl.setText(str(v))
        self.value_changed.emit(v)

    @property
    def value(self) -> int:
        return self._slider.value()

    def reset(self):
        self._slider.setValue(self._default)


# Gradient slider row (hue / saturation / lightness)
def _sat_gradient_css(hue_val: int) -> str:
    """Gray → vivid color at the given hue (–180..180)."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(((hue_val + 180) % 360) / 360.0, 1.0, 1.0)
    vivid = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 #808080, stop:1 {vivid})")


class _GradSliderRow(QWidget):
    """Slider whose groove shows a CSS gradient (hue rainbow / sat / lightness)."""
    value_changed = pyqtSignal(int)

    # Static gradient strings
    HUE_CSS = (
        ui_text("ui_texture_qlineargradient_x1_0_y1_0_x2_1_y2_0_stop_0_ff0000_stop_")
    )
    LIGHT_CSS = (
        ui_text("ui_texture_qlineargradient_x1_0_y1_0_x2_1_y2_0_stop_0_000000_stop_")
    )

    def __init__(self, label: str, lo: int, hi: int, default: int,
                 gradient_css: str = '', parent=None):
        super().__init__(parent)
        self._default = default
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setFixedWidth(88)
        lbl.setStyleSheet(ss_field_label())
        lay.addWidget(lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(lo, hi)
        self._slider.setValue(default)
        self._slider.setFixedHeight(30)
        self._slider.valueChanged.connect(self._on_change)
        lay.addWidget(self._slider, 1)

        self._val_lbl = QLabel(str(default))
        self._val_lbl.setFont(QFont("Consolas", 9))
        self._val_lbl.setFixedWidth(36)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val_lbl.setStyleSheet(ss_main_label())
        lay.addWidget(self._val_lbl)

        self.set_gradient(gradient_css)

    def _make_ss(self, bg: str) -> str:
        return ss_gradient_slider(bg)

    def set_gradient(self, gradient_css: str):
        self._slider.setStyleSheet(self._make_ss(gradient_css or P['mid']))

    def _on_change(self, v: int):
        self._val_lbl.setText(str(v))
        self.value_changed.emit(v)

    @property
    def value(self) -> int:
        return self._slider.value()

    def reset(self):
        self._slider.setValue(self._default)


# Right panel: info + quick-edit + operations
class _RightPanel(QWidget):
    sig_export_dds  = pyqtSignal()
    sig_export_png  = pyqtSignal()
    sig_export_all  = pyqtSignal()
    sig_replace     = pyqtSignal()
    sig_port        = pyqtSignal()
    sig_apply_edits = pyqtSignal(dict)   # emits dict of adjustments
    sig_reset_edits = pyqtSignal()
    sig_flip_h      = pyqtSignal()
    sig_flip_v      = pyqtSignal()
    sig_rotate      = pyqtSignal(int)    # degrees
    sig_copy_name   = pyqtSignal()
    sig_add_text    = pyqtSignal()
    sig_rename      = pyqtSignal(str, str)  # new_name, new_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(290)
        self.setStyleSheet(ss_bg_dark())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(ss_scrollarea())
        inner = QWidget()
        inner.setStyleSheet(ss_bg_dark())
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 0, 12, 12)
        lay.setSpacing(8)

        # Texture Info
        lay.addWidget(self._section_label(ui_text("ui_texture_texture_info")))

        # Name (editable)
        name_row = QHBoxLayout(); name_row.setSpacing(4); name_row.setContentsMargins(0,0,0,0)
        name_key = QLabel(ui_text("ui_texture_name")); name_key.setFixedWidth(42)
        name_key.setFont(QFont("Segoe UI", 12))
        name_key.setStyleSheet(ss_dim_label())
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(ui_text("ui_texture_texture_name"))
        self._name_edit.setFont(QFont("Consolas", 13))
        self._name_edit.setStyleSheet(ss_input())
        self._name_edit.setFixedHeight(30)
        name_row.addWidget(name_key)
        name_row.addWidget(self._name_edit, 1)
        lay.addLayout(name_row)

        # Path (editable)
        path_row = QHBoxLayout(); path_row.setSpacing(4); path_row.setContentsMargins(0,0,0,0)
        path_key = QLabel(ui_text("ui_texture_path")); path_key.setFixedWidth(42)
        path_key.setFont(QFont("Segoe UI", 12))
        path_key.setStyleSheet(ss_dim_label())
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(ui_text("ui_texture_file_path"))
        self._path_edit.setFont(QFont("Consolas", 13))
        self._path_edit.setStyleSheet(ss_input())
        self._path_edit.setFixedHeight(30)
        path_row.addWidget(path_key)
        path_row.addWidget(self._path_edit, 1)
        lay.addLayout(path_row)

        self._size_lbl   = self._info_row(ui_text("sound_field_size"),   "—")
        self._fmt_lbl    = self._info_row(ui_text("ui_texture_format"), "—")
        self._mip_lbl    = self._info_row(ui_text("ui_texture_mipmaps"),"—")
        for w in (self._size_lbl, self._fmt_lbl, self._mip_lbl):
            lay.addWidget(w)

        # Copy + Rename buttons
        cr_row = QHBoxLayout(); cr_row.setSpacing(6)
        copy_btn = QPushButton(ui_text("ui_texture_copy_name"))
        copy_btn.setFixedHeight(28)
        copy_btn.setFont(QFont("Segoe UI", 10))
        copy_btn.setStyleSheet(ss_btn())
        copy_btn.clicked.connect(self.sig_copy_name)
        cr_row.addWidget(copy_btn)

        self._rename_btn = QPushButton(ui_text("ui_texture_rename"))
        self._rename_btn.setFixedHeight(28)
        self._rename_btn.setFont(QFont("Segoe UI", 10))
        self._rename_btn.setStyleSheet(ss_btn())
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._emit_rename)
        cr_row.addWidget(self._rename_btn)
        lay.addLayout(cr_row)

        lay.addWidget(_make_sep())

        # Quick Edits
        lay.addWidget(self._section_label(ui_text("ui_texture_quick_edits")))

        self._brightness = _SliderRow(ui_text("ui_texture_brightness"), -100, 100, 0)
        self._contrast   = _SliderRow(ui_text("ui_texture_contrast"),   -100, 100, 0)
        self._sharpness  = _SliderRow(ui_text("ui_texture_sharpness"),  -100, 100, 0)

        for sl in (self._brightness, self._contrast, self._sharpness):
            sl.value_changed.connect(self._on_slider_changed)
            lay.addWidget(sl)

        # Hue / Saturation sub-group
        lay.addWidget(self._section_label(ui_text("ui_texture_hue_saturation")))

        self._hue        = _GradSliderRow(ui_text("ui_texture_hue"),        -180, 180, 0, _GradSliderRow.HUE_CSS)
        self._saturation = _GradSliderRow(ui_text("ui_texture_saturation"),  -100, 100, 0, _sat_gradient_css(0))
        self._lightness  = _GradSliderRow(ui_text("ui_texture_lightness"),   -100, 100, 0, _GradSliderRow.LIGHT_CSS)

        for sl in (self._hue, self._saturation, self._lightness):
            sl.value_changed.connect(self._on_slider_changed)
            lay.addWidget(sl)

        # Colorize checkbox
        colorize_row = QHBoxLayout()
        colorize_row.setSpacing(6)
        self._colorize_chk = QCheckBox(ui_text("ui_texture_colorize"))
        self._colorize_chk.setFont(QFont("Segoe UI", 12))
        self._colorize_chk.setStyleSheet(ss_check())
        self._colorize_chk.stateChanged.connect(self._on_slider_changed)
        colorize_row.addWidget(self._colorize_chk)
        colorize_row.addStretch()
        lay.addLayout(colorize_row)

        # Flip / Rotate row
        frow = QHBoxLayout()
        frow.setSpacing(4)
        for lbl, sig in ((ui_text("ui_texture_flip_h"), self.sig_flip_h),
                         (ui_text("ui_texture_flip_v"), self.sig_flip_v)):
            b = QPushButton(lbl)
            b.setFixedHeight(28)
            b.setFont(QFont("Segoe UI", 10))
            b.setStyleSheet(ss_btn())
            b.clicked.connect(sig)
            frow.addWidget(b)
        lay.addLayout(frow)

        rrow = QHBoxLayout()
        rrow.setSpacing(4)
        for deg, lbl in ((90, "↻ 90°"), (-90, "↺ 90°"), (180, "↻ 180°")):
            b = QPushButton(lbl)
            b.setFixedHeight(28)
            b.setFont(QFont("Segoe UI", 10))
            b.setStyleSheet(ss_btn())
            b.clicked.connect(lambda _, d=deg: self.sig_rotate.emit(d))
            rrow.addWidget(b)
        lay.addLayout(rrow)

        # Add Text (Quick Edits shortcut)
        add_text_btn = QPushButton(ui_text("ui_texture_add_text"))
        add_text_btn.setFixedHeight(30)
        add_text_btn.setFont(QFont("Segoe UI", 10))
        add_text_btn.setStyleSheet(ss_btn())
        add_text_btn.clicked.connect(self.sig_add_text)
        lay.addWidget(add_text_btn)

        # Apply / Reset
        ar_row = QHBoxLayout()
        ar_row.setSpacing(6)
        self._apply_btn = QPushButton(ui_text("ui_texture_apply"))
        self._apply_btn.setFixedHeight(30)
        self._apply_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._apply_btn.setStyleSheet(ss_btn(accent=True))
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._emit_apply)
        ar_row.addWidget(self._apply_btn)

        reset_btn = QPushButton(ui_text("ui_texture_reset"))
        reset_btn.setFixedHeight(30)
        reset_btn.setFont(QFont("Segoe UI", 10))
        reset_btn.setStyleSheet(ss_btn())
        reset_btn.clicked.connect(self._reset_sliders)
        ar_row.addWidget(reset_btn)
        lay.addLayout(ar_row)

        lay.addWidget(_make_sep())

        # Operations
        lay.addWidget(self._section_label(ui_text("ui_texture_operations")))

        for lbl, sig, acc in (
            (ui_text("ui_texture_export_dds"),       self.sig_export_dds,  False),
            (ui_text("ui_texture_export_png"),       self.sig_export_png,  False),
            (ui_text("ui_texture_export_all_2"),     self.sig_export_all,  False),
            (ui_text("ui_texture_replace"),        self.sig_replace,     False),
            (ui_text("ui_texture_port_from_xfbin_2"), self.sig_port,       False),
        ):
            b = QPushButton(lbl)
            b.setFixedHeight(30)
            b.setFont(QFont("Segoe UI", 10))
            b.setStyleSheet(ss_btn(accent=acc))
            b.clicked.connect(sig)
            lay.addWidget(b)

        lay.addStretch()
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(scroll)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(16)   # ~1 frame — smooth live preview
        self._preview_timer.timeout.connect(self._emit_apply_preview)
        self._pending_entry: TextureEntry | None = None

    # Helpers
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(8, 10, 0, 2)
        return lbl

    def _info_row(self, key: str, val: str) -> QWidget:
        w   = QWidget()
        w.setStyleSheet(ss_transparent())
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        klbl = QLabel(key + ":")
        klbl.setFont(QFont("Segoe UI", 12))
        klbl.setFixedWidth(58)
        klbl.setStyleSheet(ss_dim_label())
        vlbl = QLabel(val)
        vlbl.setFont(QFont("Consolas", 12))
        vlbl.setStyleSheet(ss_main_label())
        vlbl.setWordWrap(True)
        row.addWidget(klbl)
        row.addWidget(vlbl, 1)
        w._val = vlbl
        return w

    # Public API
    def set_entry(self, entry: TextureEntry | None):
        self._pending_entry = entry
        if entry is None:
            self._name_edit.setText("")
            self._path_edit.setText("")
            for w, v in ((self._size_lbl, "—"), (self._fmt_lbl, "—"),
                         (self._mip_lbl, "—")):
                w._val.setText(v)
            self._apply_btn.setEnabled(False)
            self._rename_btn.setEnabled(False)
            return
        self._name_edit.setText(entry.name)
        self._path_edit.setText(entry.file_path)
        self._size_lbl._val.setText(entry.size_str)
        self._fmt_lbl._val.setText(ui_text("ui_texture_value_id_value", p0=entry.format_name, p1=entry.pixel_format))
        self._mip_lbl._val.setText(str(entry.mipmap_count))
        self._apply_btn.setEnabled(entry.pil_image is not None)
        self._rename_btn.setEnabled(True)

    def _emit_rename(self):
        name = self._name_edit.text().strip()
        path = self._path_edit.text().strip()
        if name:
            self.sig_rename.emit(name, path)

    def get_adjustments(self) -> dict:
        return {
            'brightness': self._brightness.value,
            'contrast':   self._contrast.value,
            'sharpness':  self._sharpness.value,
            'hue':        self._hue.value,
            'saturation': self._saturation.value,
            'lightness':  self._lightness.value,
            'colorize':   self._colorize_chk.isChecked(),
        }

    # Slider interaction
    def _on_slider_changed(self, _):
        # Keep saturation gradient in sync with the current hue
        self._saturation.set_gradient(_sat_gradient_css(self._hue.value))
        self._preview_timer.start()

    def _emit_apply_preview(self):
        self.sig_apply_edits.emit({'preview': True, **self.get_adjustments()})

    def _emit_apply(self):
        self.sig_apply_edits.emit({'preview': False, **self.get_adjustments()})

    def _reset_sliders(self):
        for sl in (self._brightness, self._contrast, self._sharpness,
                   self._hue, self._saturation, self._lightness):
            sl.reset()
        self._colorize_chk.setChecked(False)
        self.sig_reset_edits.emit()


# Port dialog
class _PortDialog(QDialog):
    def __init__(self, entries: list[TextureEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle(ui_text("ui_texture_port_textures"))
        self.setMinimumSize(480, 500)
        self.setStyleSheet(
            f"QDialog {{background:{P['bg_dark']}; color:{P['text_main']};}}"
        )
        self._entries = entries
        self._selected: list[TextureEntry] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        hdr = QLabel(ui_text("ui_texture_select_textures_to_port_into_the_current_xfbin"))
        hdr.setFont(QFont("Segoe UI", 11))
        hdr.setStyleSheet(f"color:{P['text_sec']};")
        lay.addWidget(hdr)

        filt = QLineEdit()
        filt.setPlaceholderText(ui_text("ui_texture_filter"))
        filt.setFont(QFont("Consolas", 10))
        filt.setStyleSheet(_ss_lineedit())
        filt.textChanged.connect(self._filter)
        lay.addWidget(filt)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setFont(QFont("Consolas", 10))
        self._list.setStyleSheet(
            f"QListWidget {{background:{P['bg_card']}; color:{P['text_main']}; border:none;}}"
            f"QListWidget::item:selected {{background:{P['accent']}; color:{P['bg_dark']};}}"
            f"QListWidget::item:hover {{background:{P['bg_card_hov']};}}"
        )
        self._populate(entries)
        lay.addWidget(self._list, 1)

        # Buttons
        brow = QHBoxLayout()
        sel_all = QPushButton(ui_text("ui_texture_select_all"))
        sel_all.setFont(QFont("Segoe UI", 10))
        sel_all.setStyleSheet(ss_btn())
        sel_all.clicked.connect(self._list.selectAll)
        brow.addWidget(sel_all)
        brow.addStretch()

        ok_btn = QPushButton(ui_text("ui_texture_port_selected"))
        ok_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ok_btn.setStyleSheet(ss_btn(accent=True))
        ok_btn.clicked.connect(self._accept)
        brow.addWidget(ok_btn)

        cancel_btn = QPushButton(ui_text("ui_texture_cancel"))
        cancel_btn.setFont(QFont("Segoe UI", 11))
        cancel_btn.setStyleSheet(ss_btn())
        cancel_btn.clicked.connect(self.reject)
        brow.addWidget(cancel_btn)
        lay.addLayout(brow)

    def _populate(self, entries: list[TextureEntry]):
        self._list.clear()
        for e in entries:
            item = QListWidgetItem(
                f"{e.name}  [{e.format_name}  {e.size_str}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, e)
            self._list.addItem(item)

    def _filter(self, text: str):
        t = text.lower()
        filtered = [e for e in self._entries
                    if not t or t in e.name.lower() or t in e.format_name.lower()]
        self._populate(filtered)

    def _accept(self):
        self._selected = [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).isSelected()
        ]
        if not self._selected:
            QMessageBox.warning(self, ui_text("ui_texture_port"), ui_text("ui_texture_no_textures_selected"))
            return
        self.accept()

    def get_selected(self) -> list[TextureEntry]:
        return self._selected


# Export-all worker
class _ExportWorker(QObject):
    progress = pyqtSignal(int)
    done     = pyqtSignal(int, str)   # count, errors

    def __init__(self, entries: list[TextureEntry], folder: str, fmt: str):
        super().__init__()
        self._entries = entries
        self._folder  = folder
        self._fmt     = fmt   # 'dds' or 'png'

    def run(self):
        ok = 0
        errs = []
        for i, e in enumerate(self._entries):
            try:
                if self._fmt == 'dds':
                    data = export_entry_dds(e)
                    ext  = '.dds'
                else:
                    data = export_entry_png(e)
                    ext  = '.png'
                if data:
                    out = os.path.join(self._folder, f"{e.name}{ext}")
                    with open(out, 'wb') as f:
                        f.write(data)
                    ok += 1
                else:
                    errs.append(e.name)
            except Exception as ex:
                errs.append(f"{e.name}: {ex}")
            self.progress.emit(i + 1)
        self.done.emit(ok, '\n'.join(errs[:5]) if errs else '')


# Main Texture Editor widget
class TextureEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t_func     = t
        self._xfbin      = None
        self._entries:   list[TextureEntry] = []
        self._cur_entry: TextureEntry | None = None
        self._xfbin_path: str | None = None
        self._unsaved   = False
        self._orig_pil: Image.Image | None = None   # cached original for live preview

        self._build_ui()

    # UI construction
    def _build_ui_legacy(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(f"background:{P['bg_dark']};")

        # Top bar
        bar = QFrame()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            f"background:{P['bg_panel']}; border-bottom:1px solid {P['border']};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.setSpacing(8)

        open_btn = QPushButton(ui_text("xfa_btn_open"))
        open_btn.setFixedHeight(32)
        open_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._open_xfbin)
        bl.addWidget(open_btn)

        self._save_btn = QPushButton(ui_text("xfa_btn_save"))
        self._save_btn.setFixedHeight(32)
        self._save_btn.setFont(QFont("Segoe UI", 11))
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_xfbin)
        bl.addWidget(self._save_btn)

        self._saveas_btn = QPushButton(ui_text("ui_texture_save_as"))
        self._saveas_btn.setFixedHeight(32)
        self._saveas_btn.setFont(QFont("Segoe UI", 11))
        self._saveas_btn.setStyleSheet(ss_btn())
        self._saveas_btn.setEnabled(False)
        self._saveas_btn.clicked.connect(self._save_xfbin_as)
        bl.addWidget(self._saveas_btn)

        bl.addWidget(_make_sep())

        self._status_lbl = QLabel(ui_text("ui_texture_open_an_xfbin_file_to_get_started"))
        self._status_lbl.setFont(QFont("Segoe UI", 10))
        self._status_lbl.setStyleSheet(f"color:{P['text_dim']};")
        bl.addWidget(self._status_lbl, 1)

        root.addWidget(bar)

        # Three-column splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(
            f"QSplitter::handle {{background:{P['border']};}}"
        )

        # Left: thumbnail grid
        self._grid = _ThumbnailGrid()
        self._grid.setMinimumWidth(230)
        self._grid.texture_selected.connect(self._on_select)
        splitter.addWidget(self._grid)

        # Centre: preview
        self._preview = _PreviewPanel()
        self._preview.setMinimumWidth(300)
        splitter.addWidget(self._preview)

        # Right: info + controls
        self._right = _RightPanel()
        self._right.sig_export_dds.connect(self._export_dds)
        self._right.sig_export_png.connect(self._export_png)
        self._right.sig_export_all.connect(self._export_all)
        self._right.sig_replace.connect(self._replace)
        self._right.sig_port.connect(self._port)
        self._right.sig_add_text.connect(self._add_text)
        self._right.sig_rename.connect(self._rename)
        self._right.sig_apply_edits.connect(self._apply_edits)
        self._right.sig_reset_edits.connect(self._reset_edits)
        self._right.sig_flip_h.connect(self._flip_h)
        self._right.sig_flip_v.connect(self._flip_v)
        self._right.sig_rotate.connect(self._rotate)
        self._right.sig_copy_name.connect(self._copy_name)
        splitter.addWidget(self._right)

        splitter.setSizes([240, 500, 290])
        root.addWidget(splitter, 1)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        open_btn = QPushButton(ui_text("btn_open_file"))
        open_btn.setFixedHeight(TOOLBAR_BTN_H)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._open_xfbin)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_xfbin)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(ui_text("ui_btladjprm_no_file_loaded"))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont("Segoe UI", 10))
        self._status_lbl.setStyleSheet(ss_dim_label())
        top_layout.addWidget(self._status_lbl)
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(ss_sidebar_frame())
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self._grid = _TextureList()
        self._grid.texture_selected.connect(self._on_select)
        list_layout.addWidget(self._grid)
        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        content = QWidget()
        content.setStyleSheet(ss_bg_dark())
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._preview = _PreviewPanel()
        self._preview.setMinimumWidth(300)
        content_layout.addWidget(self._preview, 1)

        right_divider = QFrame()
        right_divider.setFixedWidth(1)
        right_divider.setStyleSheet(ss_sep())
        content_layout.addWidget(right_divider)

        self._right = _RightPanel()
        self._right.sig_export_dds.connect(self._export_dds)
        self._right.sig_export_png.connect(self._export_png)
        self._right.sig_export_all.connect(self._export_all)
        self._right.sig_replace.connect(self._replace)
        self._right.sig_port.connect(self._port)
        self._right.sig_add_text.connect(self._add_text)
        self._right.sig_rename.connect(self._rename)
        self._right.sig_apply_edits.connect(self._apply_edits)
        self._right.sig_reset_edits.connect(self._reset_edits)
        self._right.sig_flip_h.connect(self._flip_h)
        self._right.sig_flip_v.connect(self._flip_v)
        self._right.sig_rotate.connect(self._rotate)
        self._right.sig_copy_name.connect(self._copy_name)
        content_layout.addWidget(self._right)

        main_layout.addWidget(content, 1)
        root.addWidget(main, 1)

    # Open / Save
    def _open_xfbin(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("xfa_btn_open"), "", "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        self._status(ui_text("ui_effect_loading"))
        QTimer.singleShot(30, lambda: self._do_load(path))

    def _do_load(self, path: str):
        try:
            xfbin, entries = load_xfbin(path)
        except Exception as exc:
            self._status(f"Error loading: {exc}", error=True)
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(exc))
            return

        self._xfbin      = xfbin
        self._entries    = entries
        self._xfbin_path = path
        self._cur_entry  = None
        self._unsaved    = False

        self._grid.load(entries)
        self._preview.show_image(None)
        self._right.set_entry(None)
        self._save_btn.setEnabled(True)

        fname = os.path.basename(path)
        self._file_label.setText(fname)
        self._file_label.setStyleSheet(ss_file_label_loaded())
        n_tex = len(entries)
        self._status(f"Loaded  {fname}  —  {n_tex} texture{'s' if n_tex != 1 else ''}")

    def _save_xfbin(self):
        if self._xfbin is None or self._xfbin_path is None:
            return
        try:
            save_xfbin(self._xfbin, self._xfbin_path)
            self._unsaved = False
            self._file_label.setText(os.path.basename(self._xfbin_path))
            self._file_label.setStyleSheet(ss_file_label_loaded())
            self._status(f"Saved  {os.path.basename(self._xfbin_path)}")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(exc))

    def _save_xfbin_as(self):
        if self._xfbin is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, ui_text("ui_texture_save_xfbin_as"), self._xfbin_path or "",
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        try:
            save_xfbin(self._xfbin, path)
            self._xfbin_path = path
            self._unsaved    = False
            self._file_label.setText(os.path.basename(path))
            self._file_label.setStyleSheet(ss_file_label_loaded())
            self._status(f"Saved  {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(exc))

    # Selection
    def _on_select(self, entry: TextureEntry):
        self._cur_entry = entry
        self._orig_pil  = entry.pil_image.copy() if entry.pil_image else None
        self._right.set_entry(entry)
        self._show_preview(entry.pil_image)

    def _show_preview(self, img: Image.Image | None):
        if self._cur_entry is None:
            self._preview.show_image(None)
            return
        e = self._cur_entry
        info = f"{e.name}  |  {e.format_name}  |  {e.size_str}  |  {e.mipmap_count} mip"
        self._preview.show_image(img, info)

    # Live quick-edit preview
    def _apply_edits(self, adj: dict):
        if self._cur_entry is None or self._orig_pil is None:
            return
        img = _apply_adjustments(self._orig_pil.copy(), adj)

        if adj.get('preview', True):
            self._show_preview(img)
            return

        # Permanent apply
        err = apply_pil_edits_to_entry(self._cur_entry, img)
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_apply_error"), err)
            return
        self._orig_pil = img.copy()
        self._grid.refresh_active_thumb()
        self._show_preview(img)
        fmt_note = ""
        if self._cur_entry.pixel_format != 17:
            fmt_note = ui_text("ui_texture_converted_to_rgba8888")
        self._status(f"Edits applied to  {self._cur_entry.name}{fmt_note}")
        self._unsaved = True

    def _reset_edits(self):
        if self._cur_entry is None or self._orig_pil is None:
            return
        self._show_preview(self._orig_pil)

    # Flip / Rotate
    def _flip_h(self):
        if self._orig_pil is None:
            return
        img = ImageOps.mirror(self._orig_pil)
        self._commit_edit(img)

    def _flip_v(self):
        if self._orig_pil is None:
            return
        img = ImageOps.flip(self._orig_pil)
        self._commit_edit(img)

    def _rotate(self, deg: int):
        if self._orig_pil is None:
            return
        img = self._orig_pil.rotate(-deg, expand=True)
        self._commit_edit(img)

    def _commit_edit(self, img: Image.Image):
        if self._cur_entry is None:
            return
        err = apply_pil_edits_to_entry(self._cur_entry, img)
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_apply_error"), err)
            return
        self._orig_pil = img.copy()
        self._grid.refresh_active_thumb()
        self._right.set_entry(self._cur_entry)
        self._show_preview(img)
        self._unsaved = True

    # Export single
    def _export_dds(self):
        if self._cur_entry is None:
            return
        data = export_entry_dds(self._cur_entry)
        if data is None:
            QMessageBox.warning(self, ui_text("ui_texture_export"), ui_text("ui_texture_could_not_generate_dds_data_for_this_texture"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, ui_text("ui_texture_export_dds"),
            os.path.join(os.path.dirname(self._xfbin_path or ''),
                         self._cur_entry.name + '.dds'),
            "DDS Files (*.dds)"
        )
        if path:
            with open(path, 'wb') as f:
                f.write(data)
            self._status(f"Exported  {os.path.basename(path)}")

    def _export_png(self):
        if self._cur_entry is None:
            return
        data = export_entry_png(self._cur_entry)
        if data is None:
            QMessageBox.warning(self, ui_text("ui_texture_export"), ui_text("ui_texture_no_image_data_available"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, ui_text("ui_texture_export_png"),
            os.path.join(os.path.dirname(self._xfbin_path or ''),
                         self._cur_entry.name + '.png'),
            "PNG Files (*.png)"
        )
        if path:
            with open(path, 'wb') as f:
                f.write(data)
            self._status(f"Exported  {os.path.basename(path)}")

    # Export all
    def _export_all(self):
        if not self._entries:
            return

        folder = QFileDialog.getExistingDirectory(self, ui_text("ui_texture_export_all_choose_folder"))
        if not folder:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(ui_text("ui_texture_export_all"))
        dlg.setFixedSize(300, 120)
        dlg.setStyleSheet(f"QDialog {{background:{P['bg_dark']}; color:{P['text_main']};}}")
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lbl = QLabel(ui_text("ui_texture_export_format"))
        lbl.setFont(QFont("Segoe UI", 11))
        lbl.setStyleSheet(f"color:{P['text_sec']};")
        lay.addWidget(lbl)
        btn_row = QHBoxLayout()
        for fmt in ('png', 'dds'):
            b = QPushButton(fmt.upper())
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            b.setStyleSheet(ss_btn(accent=(fmt == 'png')))
            b.clicked.connect(lambda _, f=fmt, d=dlg: (d.done(0), self._run_export_all(folder, f)))
            btn_row.addWidget(b)
        cancel = QPushButton(ui_text("ui_texture_cancel"))
        cancel.setFont(QFont("Segoe UI", 11))
        cancel.setStyleSheet(ss_btn())
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        lay.addLayout(btn_row)
        dlg.exec()

    def _run_export_all(self, folder: str, fmt: str):
        total = len(self._entries)
        prog = QProgressDialog(
            ui_text("ui_texture_exporting_value_textures", p0=total),
            ui_text("ui_texture_cancel"),
            0,
            total,
            self,
        )
        prog.setWindowTitle(ui_text("ui_texture_export_all"))
        prog.setMinimumDuration(0)
        prog.setWindowModality(Qt.WindowModality.WindowModal)

        thread = QThread(self)
        worker = _ExportWorker(self._entries, folder, fmt)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(prog.setValue)
        worker.done.connect(
            lambda ok, errs: self._on_export_all_done(ok, errs, folder, prog, thread)
        )
        thread.start()
        prog.exec()

    def _on_export_all_done(self, ok: int, errs: str,
                            folder: str, prog: QProgressDialog, thread: QThread):
        prog.close()
        thread.quit()
        thread.wait()
        if errs:
            QMessageBox.warning(self, ui_text("ui_texture_export_all"),
                                ui_text("ui_texture_exported_value_textures_some_failures_value", p0=ok, p1=errs))
        else:
            self._status(f"Exported {ok} textures  →  {folder}")

    # Replace
    def _replace(self):
        if self._cur_entry is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_texture_replace_texture"),
            os.path.dirname(self._xfbin_path or ''),
            "Texture Files (*.dds *.png *.jpg *.bmp *.tga *.nut);;All Files (*)"
        )
        if not path:
            return
        err = replace_texture_from_file(self._cur_entry, path)
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_replace_error"), err)
            return
        self._orig_pil = self._cur_entry.pil_image.copy() if self._cur_entry.pil_image else None
        self._grid.refresh_active_thumb()
        self._right.set_entry(self._cur_entry)
        self._show_preview(self._cur_entry.pil_image)
        self._unsaved = True
        self._status(f"Replaced  {self._cur_entry.name}  ←  {os.path.basename(path)}")

    # Port
    def _port(self):
        if self._xfbin is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_texture_port_from_xfbin"),
            os.path.dirname(self._xfbin_path or ''),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        try:
            src_entries = load_xfbin_for_port(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_texture_port_error"), ui_text("ui_texture_could_not_load_value", p0=exc))
            return
        if not src_entries:
            QMessageBox.information(self, ui_text("ui_texture_port"), ui_text("ui_texture_no_textures_found_in_that_xfbin"))
            return

        dlg = _PortDialog(src_entries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected()
        if not selected:
            return

        added = port_entries_into_xfbin(self._xfbin, selected)
        # Reload entries from the (now modified) xfbin
        from parsers.texture_xfbin_parser import _chunk_to_entry
        new_entries = []
        for pidx, page in enumerate(self._xfbin.pages):
            for chunk in page.chunks:
                e = _chunk_to_entry(chunk, pidx)
                if e:
                    new_entries.append(e)
        self._entries = new_entries
        self._grid.load(new_entries)
        self._unsaved = True
        self._status(f"Ported {added} texture{'s' if added != 1 else ''}  ←  {os.path.basename(path)}")

    # Copy name
    def _copy_name(self):
        if self._cur_entry is None:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._cur_entry.name)
        self._status(f'Copied  \u201c{self._cur_entry.name}\u201d  to clipboard')

    def _rename(self, name: str, path: str):
        if self._cur_entry is None or not name:
            return
        old_name = self._cur_entry.name
        self._cur_entry.name      = name
        self._cur_entry.file_path = path
        # Propagate to the underlying XFBIN chunk
        if self._cur_entry.chunk is not None:
            self._cur_entry.chunk.name     = name
            self._cur_entry.chunk.filePath = path
        # Refresh the thumbnail label in the grid
        for thumb in self._grid._thumbs:
            if thumb._entry is self._cur_entry:
                thumb._name_lbl.setText(_truncate(name, 14))
                break
        self._right.set_entry(self._cur_entry)
        self._unsaved = True
        self._status(f'Renamed  \u201c{old_name}\u201d  \u2192  \u201c{name}\u201d')

    # Add Text Overlay
    def _add_text(self):
        if self._cur_entry is None or self._orig_pil is None:
            QMessageBox.information(self, ui_text("ui_texture_add_text_2"), ui_text("ui_texture_open_a_texture_first"))
            return
        dlg = _TextOverlayDialog(self._orig_pil.copy(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        result = dlg.get_result()
        if result is None:
            return
        err = apply_pil_edits_to_entry(self._cur_entry, result)
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_text_apply_error"), err)
            return
        self._orig_pil = result.copy()
        self._grid.refresh_active_thumb()
        self._right.set_entry(self._cur_entry)
        self._show_preview(result)
        self._unsaved = True
        self._status(f"Text baked into  {self._cur_entry.name}")

    # Status bar
    def _status(self, msg: str, error: bool = False):
        self._status_lbl.setStyleSheet(ss_error_label() if error else ss_dim_label())
        self._status_lbl.setText(msg)


# Adjustment helpers
import numpy as _np

def _rgb_to_hsv_np(rgb: '_np.ndarray') -> '_np.ndarray':
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    maxc = _np.maximum(_np.maximum(r, g), b)
    minc = _np.minimum(_np.minimum(r, g), b)
    v = maxc
    diff = maxc - minc
    s = _np.where(maxc > 1e-7, diff / maxc, 0.0)
    safe = _np.where(diff > 1e-7, diff, 1.0)
    h = _np.where(maxc == r, (g - b) / safe % 6,
        _np.where(maxc == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) / 6.0
    h = _np.where(diff > 1e-7, h % 1.0, 0.0)
    return _np.stack([h, s, v], axis=2).astype(_np.float32)

def _hsv_to_rgb_np(hsv: '_np.ndarray') -> '_np.ndarray':
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    i = (_np.floor(h * 6)).astype(_np.int32) % 6
    f = h * 6.0 - _np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    r = _np.choose(i, [v, q, p, p, t, v])
    g = _np.choose(i, [t, v, v, q, p, p])
    b = _np.choose(i, [p, p, t, v, v, q])
    return _np.stack([r, g, b], axis=2).clip(0.0, 1.0).astype(_np.float32)

def _apply_adjustments(img: Image.Image, adj: dict) -> Image.Image:
    img = img.convert('RGBA')

    def _f(v): return max(0.0, 1.0 + v / 100.0)

    b = adj.get('brightness', 0)
    if b != 0:
        img = ImageEnhance.Brightness(img).enhance(_f(b))

    c = adj.get('contrast', 0)
    if c != 0:
        img = ImageEnhance.Contrast(img).enhance(_f(c))

    sh = adj.get('sharpness', 0)
    if sh != 0:
        img = ImageEnhance.Sharpness(img).enhance(_f(sh))

    h        = adj.get('hue', 0)
    s        = adj.get('saturation', 0)
    l        = adj.get('lightness', 0)
    colorize = adj.get('colorize', False)

    if h != 0 or s != 0 or l != 0 or colorize:
        arr   = _np.array(img, dtype=_np.float32) / 255.0
        alpha = arr[:, :, 3].copy()
        hsv   = _rgb_to_hsv_np(arr[:, :, :3])

        if colorize:
            # Replace hue of every pixel with the slider's absolute hue,
            # use a fixed default saturation boosted by the sat slider,
            # then shift lightness (value).
            hsv[:, :, 0] = ((h + 180) / 360.0) % 1.0
            hsv[:, :, 1] = _np.clip(0.5 + s / 200.0, 0.0, 1.0)
            hsv[:, :, 2] = _np.clip(hsv[:, :, 2] + l / 100.0, 0.0, 1.0)
        else:
            if h != 0:
                hsv[:, :, 0] = (hsv[:, :, 0] + h / 360.0) % 1.0
            if s != 0:
                hsv[:, :, 1] = _np.clip(hsv[:, :, 1] * _f(s), 0.0, 1.0)
            if l != 0:
                hsv[:, :, 2] = _np.clip(hsv[:, :, 2] + l / 100.0, 0.0, 1.0)

        rgb_out = _hsv_to_rgb_np(hsv)
        out = _np.concatenate([rgb_out, alpha[:, :, _np.newaxis]], axis=2)
        img = Image.fromarray((out * 255).clip(0, 255).astype(_np.uint8), 'RGBA')

    return img


# Font utilities

_SYS_FONTS: dict[str, str] = {}   # lowercase_name -> abs_path
_FONTS_LOADED = False


def _ensure_fonts() -> dict[str, str]:
    global _SYS_FONTS, _FONTS_LOADED
    if _FONTS_LOADED:
        return _SYS_FONTS
    _FONTS_LOADED = True
    _SYS_FONTS = _scan_system_fonts()
    return _SYS_FONTS


def _scan_system_fonts() -> dict[str, str]:
    """Return {lowercase_display_name: abs_path} for every installed font file."""
    result: dict[str, str] = {}

    # Windows registry (fastest & most complete)
    if os.name == 'nt':
        try:
            import winreg
            fonts_dir = os.path.join(
                os.environ.get('WINDIR', ui_text("ui_texture_c_windows")), ui_text("ui_texture_fonts"))
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                ui_text("ui_texture_software_microsoft_windows_nt_currentversion_fonts"))
            i = 0
            while True:
                try:
                    reg_name, path, _ = winreg.EnumValue(key, i)
                    if not os.path.isabs(path):
                        path = os.path.join(fonts_dir, path)
                    if os.path.exists(path) and path.lower().endswith(
                            ('.ttf', '.otf', '.ttc')):
                        # "Arial Bold (TrueType)" → "arial bold"
                        clean = reg_name.split('(')[0].strip().lower()
                        result[clean] = path
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    # Fallback: scan Fonts directory
    if not result:
        for fdir in (
            os.path.join(os.environ.get('WINDIR', ''), ui_text("ui_texture_fonts")),
            '/usr/share/fonts', '/usr/local/share/fonts',
            os.path.expanduser(ui_text("ui_texture_fonts_2")),
        ):
            if not os.path.isdir(fdir):
                continue
            for root, _, files in os.walk(fdir):
                for fname in files:
                    if fname.lower().endswith(('.ttf', '.otf', '.ttc')):
                        key = os.path.splitext(fname)[0].lower()
                        result[key] = os.path.join(root, fname)

    return result


def _resolve_font_path(family: str, bold: bool, italic: bool) -> str | None:
    """
    Given a QFontComboBox family name + style flags, return the best matching
    font file path for PIL, or None if nothing found.
    """
    fonts = _ensure_fonts()
    base = family.lower()

    # Build priority list of candidate names (most specific → least specific)
    candidates: list[str] = []
    if bold and italic:
        candidates += [base + ' bold italic', base + ' bolditalic',
                       base + ' bold oblique']
    if bold:
        candidates += [base + ' bold', base + ' bd']
    if italic:
        candidates += [base + ' italic', base + ' oblique',
                       base + ' it']
    candidates += [base + ' regular', base]

    for c in candidates:
        if c in fonts:
            return fonts[c]

    # Partial-match fallback: any key that starts with the base name
    for key, path in fonts.items():
        if key.startswith(base):
            return path

    return None


def _pil_font(family: str, size: int, bold: bool, italic: bool):
    """Load an ImageFont; fall back to default if the font file can't be found."""
    from PIL import ImageFont
    path = _resolve_font_path(family, bold, italic)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Try PIL's built-in truetype default
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _render_text_overlay(
    base: Image.Image,
    text: str,
    family: str,
    size: int,
    bold: bool,
    italic: bool,
    color: tuple,         # (R, G, B)
    opacity: int,         # 0-255
    x_pct: float,         # 0.0-1.0 of image width
    y_pct: float,         # 0.0-1.0 of image height
    anchor: str,          # 'lt' | 'mt' | 'rt' | 'lm' | 'mm' | 'rm' | 'lb' | 'mb' | 'rb'
    align: str,           # 'left' | 'center' | 'right'
    outline: int,         # outline thickness px
    outline_color: tuple, # (R, G, B)
    shadow_x: int,
    shadow_y: int,
    shadow_color: tuple,  # (R, G, B)
    shadow_opacity: int,
) -> Image.Image:
    from PIL import ImageDraw

    img    = base.convert('RGBA')
    canvas = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    font   = _pil_font(family, size, bold, italic)

    px = int(x_pct * img.width)
    py = int(y_pct * img.height)

    fill_main    = (*color,         opacity)
    fill_outline = (*outline_color, opacity)
    fill_shadow  = (*shadow_color,  shadow_opacity)

    def _draw_text(d, ox, oy, fill):
        d.multiline_text((px + ox, py + oy), text, font=font,
                         fill=fill, anchor=anchor, align=align,
                         spacing=int(size * 0.25))

    # Shadow pass
    if (shadow_x != 0 or shadow_y != 0) and shadow_opacity > 0:
        _draw_text(draw, shadow_x, shadow_y, fill_shadow)

    # Outline pass (stroke)
    if outline > 0:
        for dx in range(-outline, outline + 1):
            for dy in range(-outline, outline + 1):
                if abs(dx) + abs(dy) <= outline + 1:
                    _draw_text(draw, dx, dy, fill_outline)

    # Main text
    _draw_text(draw, 0, 0, fill_main)

    return Image.alpha_composite(img, canvas)


# Draggable preview label (used by _TextOverlayDialog)

class _DraggablePreview(QLabel):
    """QLabel that turns mouse clicks/drags into (x_pct, y_pct) signals."""
    position_changed = pyqtSignal(float, float)   # 0.0–1.0 each

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._emit(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._emit(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _emit(self, pos):
        w = max(1, self.width())
        h = max(1, self.height())
        self.position_changed.emit(
            max(0.0, min(1.0, pos.x() / w)),
            max(0.0, min(1.0, pos.y() / h)),
        )


# Text Overlay Dialog

class _TextOverlayDialog(QDialog):
    """Full-featured text-overlay dialog with live preview."""

    # Anchor labels shown in the UI -> PIL anchor strings
    _ANCHOR_OPTS = [
        (ui_text("ui_texture_tl_top_left"),     "lt"), (ui_text("ui_texture_tc_top_center"),  "mt"), (ui_text("ui_texture_tr_top_right"),   "rt"),
        (ui_text("ui_texture_ml_mid_left"),     "lm"), (ui_text("ui_texture_cc_center"),      "mm"), (ui_text("ui_texture_mr_mid_right"),   "rm"),
        (ui_text("ui_texture_bl_bot_left"),     "lb"), (ui_text("ui_texture_bc_bot_center"),  "mb"), (ui_text("ui_texture_br_bot_right"),   "rb"),
    ]

    def __init__(self, base_img: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle(ui_text("ui_texture_add_text_overlay"))
        self.setMinimumSize(900, 620)
        self.resize(1050, 680)
        self.setStyleSheet(
            f"QDialog {{background:{P['bg_dark']}; color:{P['text_main']};}}"
        )
        self._base    = base_img.convert('RGBA')
        self._result  = None
        self._color         = (255, 255, 255)
        self._outline_color = (0,   0,   0)
        self._shadow_color  = (0,   0,   0)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._update_preview)

        self._build_ui()
        QTimer.singleShot(100, self._update_preview)

    # UI
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left: preview
        preview_wrap = QWidget()
        preview_wrap.setStyleSheet(f"background:{P['bg_dark']};")
        pl = QVBoxLayout(preview_wrap)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(4)

        pv_hdr = QHBoxLayout(); pv_hdr.setSpacing(8)
        pv_lbl = QLabel(ui_text("ui_texture_preview"))
        pv_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        pv_lbl.setStyleSheet(f"color:{P['accent']};")
        pv_hdr.addWidget(pv_lbl)
        drag_hint = QLabel(ui_text("ui_texture_drag_to_reposition_text"))
        drag_hint.setFont(QFont("Segoe UI", 9))
        drag_hint.setStyleSheet(f"color:{P['text_dim']};")
        pv_hdr.addWidget(drag_hint)
        pv_hdr.addStretch()
        pl.addLayout(pv_hdr)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_scroll.setStyleSheet(
            f"QScrollArea {{background:{P['bg_card']}; border:1px solid {P['border']}; border-radius:4px;}}"
            f"QScrollBar:vertical {{background:{P['bg_dark']}; width:8px;}}"
            f"QScrollBar::handle:vertical {{background:{P['mid']}; border-radius:4px;}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{height:0;}}"
            f"QScrollBar:horizontal {{background:{P['bg_dark']}; height:8px;}}"
            f"QScrollBar::handle:horizontal {{background:{P['mid']}; border-radius:4px;}}"
            f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{width:0;}}"
        )
        self._preview_lbl = _DraggablePreview()
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet(ui_text("ui_texture_background_transparent"))
        self._preview_lbl.position_changed.connect(self._on_preview_drag)
        self._preview_scroll.setWidget(self._preview_lbl)
        self._preview_scroll.setWidgetResizable(False)
        pl.addWidget(self._preview_scroll, 1)

        root.addWidget(preview_wrap, 1)

        # Right: controls
        ctrl_scroll = QScrollArea()
        ctrl_scroll.setFixedWidth(320)
        ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setFrameShape(QFrame.Shape.NoFrame)
        ctrl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ctrl_scroll.setStyleSheet(
            f"QScrollArea {{background:{P['bg_panel']}; border-left:1px solid {P['border']};}}"
            f"QScrollBar:vertical {{background:{P['bg_panel']}; width:6px;}}"
            f"QScrollBar::handle:vertical {{background:{P['mid']}; border-radius:3px;}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{height:0;}}"
        )
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background:{P['bg_panel']};")
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # Text input
        cl.addWidget(self._sec(ui_text("ui_galleryartparam_text")))
        from PyQt6.QtWidgets import QPlainTextEdit
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText(ui_text("ui_texture_enter_text_ctrl_enter_new_line"))
        self._text_edit.setFixedHeight(80)
        self._text_edit.setFont(QFont("Segoe UI", 11))
        self._text_edit.setStyleSheet(
            f"QPlainTextEdit {{background:{P['bg_card']}; border:1px solid {P['border']}; "
            f"color:{P['text_main']}; padding:4px 6px; border-radius:4px;}}"
            f"QPlainTextEdit:focus {{border:1px solid {P['accent']};}}"
        )
        self._text_edit.textChanged.connect(self._kick)
        cl.addWidget(self._text_edit)

        # Font
        cl.addWidget(self._sec(ui_text("ui_texture_font")))

        from PyQt6.QtWidgets import QFontComboBox
        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont("Arial"))
        self._font_combo.setStyleSheet(
            f"QFontComboBox {{background:{P['bg_card']}; border:1px solid {P['border']}; "
            f"color:{P['text_main']}; padding:2px 6px; border-radius:4px;}}"
            f"QFontComboBox::drop-down {{border:none; width:22px;}}"
            f"QFontComboBox QAbstractItemView {{background:{P['bg_card']}; "
            f"color:{P['text_main']}; selection-background-color:{P['accent']};}}"
        )
        self._font_combo.currentFontChanged.connect(self._kick)
        cl.addWidget(self._font_combo)

        # Size + Bold + Italic row
        srow = QHBoxLayout(); srow.setSpacing(6)
        from PyQt6.QtWidgets import QSpinBox
        size_lbl = QLabel(ui_text("ui_texture_size"))
        size_lbl.setFont(QFont("Segoe UI", 10))
        size_lbl.setStyleSheet(f"color:{P['text_dim']};")
        srow.addWidget(size_lbl)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 512)
        self._size_spin.setValue(36)
        self._size_spin.setFixedWidth(64)
        self._size_spin.setFont(QFont("Consolas", 11))
        self._size_spin.setStyleSheet(
            f"QSpinBox {{background:{P['bg_card']}; border:1px solid {P['border']}; "
            f"color:{P['text_main']}; padding:2px 4px; border-radius:4px;}}"
            f"QSpinBox::up-button, QSpinBox::down-button {{width:18px;}}"
        )
        self._size_spin.valueChanged.connect(self._kick)
        srow.addWidget(self._size_spin)

        self._bold_btn   = self._toggle_btn("B", QFont.Weight.Bold)
        self._italic_btn = self._toggle_btn("I", QFont.Weight.Normal, italic=True)
        srow.addWidget(self._bold_btn)
        srow.addWidget(self._italic_btn)
        srow.addStretch()
        cl.addLayout(srow)

        # Color
        cl.addWidget(self._sec(ui_text("ui_texture_colors_opacity")))

        self._color_btn = self._color_picker_btn(ui_text("ui_texture_text_color"), (255, 255, 255),
                                                  self._pick_text_color)
        cl.addWidget(self._color_btn[0])

        self._opacity_row = _SliderRow(ui_text("ui_texture_opacity"), 0, 255, 255)
        self._opacity_row.value_changed.connect(self._kick)
        cl.addWidget(self._opacity_row)

        # Outline
        self._outline_row = _SliderRow(ui_text("ui_texture_outline_px"), 0, 20, 0)
        self._outline_row.value_changed.connect(self._kick)
        cl.addWidget(self._outline_row)

        self._outline_btn = self._color_picker_btn(ui_text("ui_texture_outline_color"), (0, 0, 0),
                                                    self._pick_outline_color)
        cl.addWidget(self._outline_btn[0])

        # Shadow
        cl.addWidget(self._sec(ui_text("ui_texture_shadow_2")))

        sh_row = QHBoxLayout(); sh_row.setSpacing(6)
        for lbl, attr, lo, hi, default in (
            ("X",  '_shadow_x', -30, 30, 3),
            ("Y",  '_shadow_y', -30, 30, 3),
        ):
            ql = QLabel(lbl + ":")
            ql.setFont(QFont("Segoe UI", 10))
            ql.setStyleSheet(f"color:{P['text_dim']};")
            sh_row.addWidget(ql)
            sl = _SliderRow("", lo, hi, default)
            sl.value_changed.connect(self._kick)
            setattr(self, attr + '_slider', sl)
            sh_row.addWidget(sl, 1)
        cl.addLayout(sh_row)

        self._shadow_op_row = _SliderRow(ui_text("ui_texture_shadow"), 0, 255, 0)
        self._shadow_op_row.value_changed.connect(self._kick)
        cl.addWidget(self._shadow_op_row)

        self._shadow_btn = self._color_picker_btn(ui_text("ui_texture_shadow_color"), (0, 0, 0),
                                                   self._pick_shadow_color)
        cl.addWidget(self._shadow_btn[0])

        # Position
        cl.addWidget(self._sec(ui_text("ui_texture_position")))

        self._x_row = _SliderRow(ui_text("ui_texture_x"), 0, 100, 50)
        self._x_row.value_changed.connect(self._kick)
        cl.addWidget(self._x_row)

        self._y_row = _SliderRow(ui_text("ui_texture_y"), 0, 100, 50)
        self._y_row.value_changed.connect(self._kick)
        cl.addWidget(self._y_row)

        # Anchor grid (3×3)
        from PyQt6.QtWidgets import QButtonGroup
        cl.addWidget(QLabel(ui_text("ui_texture_anchor")))
        ag_widget = QWidget()
        ag_widget.setStyleSheet(ui_text("ui_texture_background_transparent"))
        ag_layout = QGridLayout(ag_widget)
        ag_layout.setContentsMargins(0, 0, 0, 0)
        ag_layout.setSpacing(3)
        self._anchor_group = QButtonGroup(self)
        self._anchor_btns: dict[str, QPushButton] = {}
        for i, (label, anc) in enumerate(self._ANCHOR_OPTS):
            btn = QPushButton(label.split()[0])
            btn.setCheckable(True)
            btn.setFixedSize(46, 28)
            btn.setFont(QFont("Segoe UI", 10))
            btn.setStyleSheet(ss_toggle_btn())
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, a=anc: self._on_anchor(a))
            self._anchor_group.addButton(btn)
            self._anchor_btns[anc] = btn
            ag_layout.addWidget(btn, i // 3, i % 3)
        self._anchor_btns['mm'].setChecked(True)
        self._current_anchor = 'mm'
        cl.addWidget(ag_widget)

        # Alignment row
        align_row = QHBoxLayout(); align_row.setSpacing(4)
        self._align_group = QButtonGroup(self)
        for symbol, val in ((ui_text("ui_texture_l"), 'left'), (ui_text("ui_texture_c"), 'center'), (ui_text("ui_texture_r"), 'right')):
            btn = QPushButton(symbol)
            btn.setCheckable(True)
            btn.setFixedSize(42, 26)
            btn.setFont(QFont("Segoe UI", 10))
            btn.setStyleSheet(ss_toggle_btn())
            btn.setProperty('align_val', val)
            btn.clicked.connect(self._kick)
            self._align_group.addButton(btn)
            align_row.addWidget(btn)
            if val == 'left':
                btn.setChecked(True)
        align_row.addStretch()
        cl.addLayout(align_row)

        # Accept / Cancel
        cl.addStretch()
        cl.addWidget(_make_sep())

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        ok_btn = QPushButton(ui_text("ui_texture_apply_to_texture"))
        ok_btn.setFixedHeight(34)
        ok_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ok_btn.setStyleSheet(ss_btn(accent=True))
        ok_btn.clicked.connect(self._accept)
        btn_row.addWidget(ok_btn, 1)

        cancel_btn = QPushButton(ui_text("ui_texture_cancel"))
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont("Segoe UI", 11))
        cancel_btn.setStyleSheet(ss_btn())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        cl.addLayout(btn_row)

        ctrl_scroll.setWidget(ctrl)
        root.addWidget(ctrl_scroll)

    # Small helpers
    @staticmethod
    def _sec(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color:{P['accent']}; padding-top:4px;")
        return lbl

    @staticmethod
    def _toggle_btn(label: str, weight, italic: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFixedSize(30, 28)
        f = QFont("Segoe UI", 11, weight)
        f.setItalic(italic)
        btn.setFont(f)
        btn.setStyleSheet(ss_toggle_btn())
        return btn

    def _color_picker_btn(self, label: str, default: tuple, callback) -> tuple:
        """Returns (QWidget, setter_fn) where the widget shows a color swatch + label."""
        w   = QWidget(); w.setStyleSheet(ui_text("ui_texture_background_transparent"))
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)

        lbl = QLabel(label + ":")
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setStyleSheet(f"color:{P['text_dim']};")
        row.addWidget(lbl)

        swatch = QPushButton()
        swatch.setFixedSize(56, 22)
        swatch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        swatch.setStyleSheet(
            f"QPushButton {{background: rgb{default}; border:1px solid {P['border']}; "
            f"border-radius:3px;}} QPushButton:hover {{border:1px solid {P['accent']};}}"
        )
        swatch.clicked.connect(callback)
        row.addWidget(swatch)
        row.addStretch()

        # store reference so we can update the swatch color later
        w._swatch = swatch
        return w, swatch

    # Color pickers
    def _pick_text_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(
            QColor(*self._color), self, ui_text("ui_texture_text_color"),
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue())
            self._color_btn[0]._swatch.setStyleSheet(
                f"QPushButton {{background:rgb{self._color}; border:1px solid {P['border']}; border-radius:3px;}}"
                f"QPushButton:hover {{border:1px solid {P['accent']};}}"
            )
            self._kick()

    def _pick_outline_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(*self._outline_color), self, ui_text("ui_texture_outline_color"))
        if c.isValid():
            self._outline_color = (c.red(), c.green(), c.blue())
            self._outline_btn[0]._swatch.setStyleSheet(
                f"QPushButton {{background:rgb{self._outline_color}; border:1px solid {P['border']}; border-radius:3px;}}"
                f"QPushButton:hover {{border:1px solid {P['accent']};}}"
            )
            self._kick()

    def _pick_shadow_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(*self._shadow_color), self, ui_text("ui_texture_shadow_color"))
        if c.isValid():
            self._shadow_color = (c.red(), c.green(), c.blue())
            self._shadow_btn[0]._swatch.setStyleSheet(
                f"QPushButton {{background:rgb{self._shadow_color}; border:1px solid {P['border']}; border-radius:3px;}}"
                f"QPushButton:hover {{border:1px solid {P['accent']};}}"
            )
            self._kick()

    # Anchor / alignment
    def _on_anchor(self, anc: str):
        self._current_anchor = anc
        for a, btn in self._anchor_btns.items():
            btn.setChecked(a == anc)
        self._kick()

    def _on_preview_drag(self, x: float, y: float):
        """Called when user drags on the preview image; updates X/Y sliders."""
        self._x_row._slider.blockSignals(True)
        self._y_row._slider.blockSignals(True)
        self._x_row._slider.setValue(int(round(x * 100)))
        self._y_row._slider.setValue(int(round(y * 100)))
        self._x_row._val_lbl.setText(str(int(round(x * 100))))
        self._y_row._val_lbl.setText(str(int(round(y * 100))))
        self._x_row._slider.blockSignals(False)
        self._y_row._slider.blockSignals(False)
        self._debounce.start()

    def _current_align(self) -> str:
        for btn in self._align_group.buttons():
            if btn.isChecked():
                return btn.property('align_val') or 'left'
        return 'left'

    # Preview plumbing
    def _kick(self, *_):
        self._debounce.start()

    def _update_preview(self):
        rendered = self._render()
        # Scale to fit the preview area
        vp = self._preview_scroll.viewport()
        vw, vh = max(1, vp.width() - 4), max(1, vp.height() - 4)
        iw, ih = rendered.size
        scale = min(vw / iw, vh / ih, 1.0)
        w2 = max(1, int(iw * scale))
        h2 = max(1, int(ih * scale))
        thumb = rendered.resize((w2, h2), Image.LANCZOS)
        bg = _checkerboard(w2, h2)
        bg.paste(thumb, (0, 0), thumb if thumb.mode == 'RGBA' else None)
        pm = _pil_to_qpixmap(bg)
        self._preview_lbl.setPixmap(pm)
        self._preview_lbl.setFixedSize(w2, h2)

    def _render(self) -> Image.Image:
        text = self._text_edit.toPlainText()
        if not text:
            return self._base.copy()

        family  = self._font_combo.currentFont().family()
        size    = self._size_spin.value()
        bold    = self._bold_btn.isChecked()
        italic  = self._italic_btn.isChecked()
        opacity = self._opacity_row.value
        outline = self._outline_row.value
        sx      = self._shadow_x_slider.value
        sy      = self._shadow_y_slider.value
        s_op    = self._shadow_op_row.value
        x_pct   = self._x_row.value / 100.0
        y_pct   = self._y_row.value / 100.0
        anchor  = self._current_anchor
        align   = self._current_align()

        return _render_text_overlay(
            self._base, text,
            family, size, bold, italic,
            self._color, opacity,
            x_pct, y_pct, anchor, align,
            outline, self._outline_color,
            sx, sy, self._shadow_color, s_op,
        )

    # Accept
    def _accept(self):
        if not self._text_edit.toPlainText().strip():
            QMessageBox.warning(self, ui_text("ui_texture_add_text_2"), ui_text("ui_texture_please_enter_some_text_first"))
            return
        self._result = self._render()
        self.accept()

    def get_result(self) -> Image.Image | None:
        return self._result

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(60, self._update_preview)
