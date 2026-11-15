"""
ASBR Texture Editor
Full-featured XFBIN texture editor with:
  • Virtualized texture catalog with thumbnails / search / batch selection
  • Native pixel / channel / mip / cubemap-face inspection and comparison
  • Live quick-edit adjustments (brightness / contrast / saturation / hue)
  • Flip, rotate
  • Export single texture as DDS or PNG
  • Export all textures at once
  • Replace texture from DDS / PNG / NUT file
  • Port textures from another XFBIN
  • Save modified XFBIN
"""

from core.design_tokens import (
    HUE_GRADIENT,
    IconButtonRole,
    Insets,
    LIGHTNESS_GRADIENT,
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    ss_accent_label,
    ss_bg_dark,
    ss_bg_panel,
    ss_check,
    ss_dialog,
    ss_dim_label,
    ss_error_label,
    ss_field_label,
    ss_gradient_slider,
    ss_listwidget,
    ss_main_label,
    ss_radio,
    ss_scrollarea_card,
    ss_scrollarea_panel_edge,
    ss_section_label,
    ss_slider,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_file_label,
    configure_icon_button,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
    configure_table,
    configure_textedit,
    fit_scroll_page,
)
from core.ui.editor_chrome import install_editor_chrome, EditorSidebarPane
from core.ui.editor_actions import install_file_actions
import os
import copy
import threading

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QMessageBox, QDialog, QListWidget, QListWidgetItem,
    QAbstractItemView, QCheckBox, QSizePolicy, QProgressDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QColorDialog, QLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QObject, QRunnable, QThreadPool, QRegularExpression
from PyQt6.QtGui import QFont, QPixmap, QCursor, QColor, QRegularExpressionValidator

from PIL import Image, ImageOps

from core.themes import P
from core.editor_file_state import set_file_label
from core.icons import _pil_to_qpixmap
from core.undo_redo import EditorHistory
from parsers.texture_xfbin_parser import (
    TextureEntry, load_xfbin, save_xfbin,
    replace_texture_from_file, apply_pil_edits_to_entry,
    export_entry_dds, export_entry_png,
    load_xfbin_for_port, port_entries_into_xfbin,
    add_texture_from_file, duplicate_texture_entry,
    delete_texture_entry, refresh_texture_entries,
    entry_image, entry_editable,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.texture_batch import match_texture_files, export_filename
from core.ui.number_input import SliderInput
from core.ui.record_list import RecordListModel, EditorRecordList
from core.texture_tools import apply_adjustments as _apply_adjustments
from editors.texture_preview import TexturePreview as _PreviewPanel

DEFAULT_COLORIZE_HEX = "#FFFFFF"


def _icon_button(icon_name: str, tooltip: str, *, checkable: bool = False,
                 inline_picker: bool = False) -> QPushButton:
    btn = QPushButton()
    btn.setToolTip(tooltip)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setCheckable(checkable)
    configure_icon_button(btn, IconButtonRole.INLINE_PICKER if inline_picker else IconButtonRole.TOOLBAR)
    btn.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
    return btn


def _normalize_hex(text: str) -> str | None:
    raw = (text or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6 or any(c not in "0123456789abcdefABCDEF" for c in raw):
        return None
    return "#" + raw.upper()


def _hex_to_rgb(text: str) -> tuple[int, int, int]:
    hex_color = _normalize_hex(text) or DEFAULT_COLORIZE_HEX
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def _checkerboard(w: int, h: int, block: int = 8) -> Image.Image:
    from PIL import ImageDraw
    image = Image.new('RGBA', (w, h), P['bg_dark'])
    draw = ImageDraw.Draw(image)
    for y in range(0, h, block):
        for x in range(0, w, block):
            if (x // block + y // block) % 2:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill=P['border'])
    return image


def _texture_thumb_pixmap(entry: TextureEntry, size: int = 24) -> QPixmap:
    if entry.pil_image is None:
        pm = QPixmap(size, size)
        pm.fill(QColor(P.get("input_bg", P["bg_card"])))
        return pm
    img = entry.pil_image.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    tile = _checkerboard(size, size, block=max(4, size // 4))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    if img.mode == "RGBA":
        tile.paste(img, (x, y), img)
    else:
        tile.paste(img.convert("RGBA"), (x, y))
    return _pil_to_qpixmap(tile)


def _texture_slider_ss(track_background: str | None = None) -> str:
    return ss_gradient_slider(track_background) if track_background else ss_slider()


def _texture_open_dir() -> str:
    game_dir = load_settings().get("game_files_dir", "")
    if game_dir and os.path.isdir(game_dir):
        candidates = [
            os.path.join(game_dir, "data", "ui"),
            os.path.join(game_dir, "ui"),
        ]
        if os.path.basename(os.path.normpath(game_dir)).lower() == "ui":
            candidates.insert(0, game_dir)
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
    return game_files_dialog_dir(target_patterns="*.xfbin")


def _make_sep():
    sep = EditorSeparator()
    sep.setFrameShape(QFrame.Shape.HLine)


    return sep


def _swatch_style(color: tuple[int, int, int]) -> str:
    return (
        f"QPushButton {{background: rgb{color}; border:1px solid {P['border']}; "
        f"border-radius:3px;}} QPushButton:hover {{border:1px solid {P['accent']};}}"
    )


class _TextureList(QWidget):
    texture_selected = pyqtSignal(object)
    sig_new = pyqtSignal()
    sig_duplicate = pyqtSignal()
    sig_delete = pyqtSignal()
    sig_batch_replace = pyqtSignal()
    sig_export_checked_png = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[TextureEntry] = []
        self._thumbs: list[QPushButton] = []
        self._active_entry: TextureEntry | None = None
        self._file_loaded = False

        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.SIDEBAR)
        self.setStyleSheet(ss_bg_panel())

        self._search_entry = QLineEdit()
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(self._filter_list)
        root.addWidget(self._search_entry)

        btn_row = EditorActionRow()

        btn_layout = btn_row.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._new_btn = QPushButton(ui_text("btn_new"))
        self._new_btn.setIcon(qta.icon("fa6s.plus", color=P.get("button_text", P["text_main"])))
        self._new_btn.setIconSize(QSize(12, 12))
        configure_button(self._new_btn, height=Size.COMPACT_CONTROL)
        self._new_btn.setEnabled(False)
        self._new_btn.clicked.connect(self.sig_new)
        btn_layout.addWidget(self._new_btn, 1)

        self._dup_btn = QPushButton(ui_text("btn_dup_short"))
        self._dup_btn.setIcon(qta.icon("fa6s.copy", color=P.get("button_text", P["text_main"])))
        self._dup_btn.setIconSize(QSize(12, 12))
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.setEnabled(False)
        self._dup_btn.clicked.connect(self.sig_duplicate)
        btn_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(ui_text("btn_delete"))
        self._del_btn.setIcon(qta.icon("fa6s.trash-can", color=P.get("button_text", P["text_main"])))
        self._del_btn.setIconSize(QSize(12, 12))
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self.sig_delete)
        btn_layout.addWidget(self._del_btn, 1)

        root.addWidget(btn_row)

        batch_row = QWidget()
        batch_row.setStyleSheet(ss_transparent())
        batch_layout = QHBoxLayout(batch_row)
        batch_layout.setContentsMargins(0, 0, 0, 4)
        batch_layout.setSpacing(Size.GAP_SM)

        self._select_all_btn = QPushButton(ui_text("ui_texture_select_all"))
        configure_button(self._select_all_btn, height=Size.INSPECTOR_CONTROL)
        self._select_all_btn.setEnabled(False)
        self._select_all_btn.clicked.connect(lambda: self.set_all_checked(True))
        batch_layout.addWidget(self._select_all_btn, 1)

        self._deselect_all_btn = QPushButton(ui_text("ui_texture_deselect_all"))
        configure_button(self._deselect_all_btn, height=Size.INSPECTOR_CONTROL)
        self._deselect_all_btn.setEnabled(False)
        self._deselect_all_btn.clicked.connect(lambda: self.set_all_checked(False))
        batch_layout.addWidget(self._deselect_all_btn, 1)

        root.addWidget(batch_row)

        self._batch_btn = QPushButton(ui_text("ui_texture_batch_replace"))
        self._batch_btn.setIcon(qta.icon("fa6s.arrows-rotate", color=P.get("button_text", P["text_main"])))
        self._batch_btn.setIconSize(QSize(13, 13))
        configure_button(self._batch_btn, accent=True)
        self._batch_btn.setEnabled(False)
        self._batch_btn.clicked.connect(self.sig_batch_replace)
        root.addWidget(self._batch_btn)

        self._export_checked_btn = QPushButton(ui_text("ui_texture_export_checked_png"))
        self._export_checked_btn.setIcon(qta.icon("fa6s.file-export", color=P.get("button_text", P["text_main"])))
        self._export_checked_btn.setIconSize(QSize(13, 13))
        configure_button(self._export_checked_btn, height=Size.COMPACT_CONTROL)
        self._export_checked_btn.setEnabled(False)
        self._export_checked_btn.clicked.connect(self.sig_export_checked_png)
        root.addWidget(self._export_checked_btn)

        self._model = RecordListModel(self)
        self._checked = set()
        self._thumb_cache = {}
        self._scroll = EditorRecordList(self._model, self._describe, bind_row=self._bind_row)
        self._scroll.selectionModel().currentRowChanged.connect(self._selected_index)
        root.addWidget(self._scroll, 1)

    def _describe(self, index):
        entry = self._model.rows[index.row()][1]
        return entry.name, self._meta(entry), entry.name + '\n' + entry.file_path

    def _bind_row(self, row, index):
        entry = self._model.rows[index.row()][1]
        row._entry = entry
        if not hasattr(row, '_batch_check'):
            holder = QWidget(row)
            layout = configure_layout(QHBoxLayout(holder), LayoutRole.FIELD)
            check = row._batch_check = QCheckBox()
            check.setStyleSheet(ss_check())
            check.setToolTip(ui_text('ui_texture_batch_checkbox_tip'))
            check.toggled.connect(lambda checked, r=row: self._check(r._entry, checked))
            layout.addWidget(check)
            row._thumb_lbl = QLabel()
            row._thumb_lbl.setFixedSize(26, 26)
            row._thumb_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(row._thumb_lbl)
            labels = QWidget()
            labels.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout = configure_layout(QVBoxLayout(labels), LayoutRole.ROOT)
            for label in (row.title_label, row.subtitle_label):
                row.content_layout.removeWidget(label)
                text_layout.addWidget(label)
            layout.addWidget(labels, 1)
            row.content_layout.addWidget(holder)
        row._batch_check.blockSignals(True)
        row._batch_check.setChecked(id(entry) in self._checked)
        row._batch_check.blockSignals(False)
        key = id(entry)
        if key not in self._thumb_cache:
            if len(self._thumb_cache) >= 256:
                self._thumb_cache.pop(next(iter(self._thumb_cache)))
            self._thumb_cache[key] = _texture_thumb_pixmap(entry, 26)
        row._thumb_lbl.setPixmap(self._thumb_cache[key])

    def _check(self, entry, checked):
        if checked:
            self._checked.add(id(entry))
        else:
            self._checked.discard(id(entry))

    def _selected_index(self, current, previous):
        if current.isValid():
            self._select(self._model.rows[current.row()][1], emit=True, update_index=False)

    def load(self, entries):
        self._entries = entries
        self._active_entry = None
        self._checked.clear()
        self._thumb_cache.clear()
        self._filter_list()
        self._update_action_state()

    def refresh_active_thumb(self):
        if self._active_entry is not None:
            self._refresh_row(self._active_entry)

    def set_file_loaded(self, loaded):
        self._file_loaded = loaded
        self._update_action_state()

    def select_entry(self, entry):
        self._select(entry, emit=True)
        self._scroll.scrollTo(self._scroll.currentIndex())

    def _meta(self, entry):
        return f'{entry.format_name} / {entry.size_str}'

    def _select(self, entry, emit, update_index=True):
        self._active_entry = entry
        if update_index:
            row = next((n for n, item in enumerate(self._model.rows) if item[1] is entry), -1)
            selection = self._scroll.selectionModel()
            selection.blockSignals(True)
            self._scroll.setCurrentIndex(self._model.index(row, 0))
            selection.blockSignals(False)
        self._update_action_state()
        if emit:
            self.texture_selected.emit(entry)

    def _update_action_state(self):
        has_selection = self._active_entry is not None
        self._new_btn.setEnabled(self._file_loaded)
        self._dup_btn.setEnabled(has_selection)
        self._del_btn.setEnabled(has_selection)
        has_entries = self._file_loaded and bool(self._entries)
        for button in (self._batch_btn, self._export_checked_btn, self._select_all_btn, self._deselect_all_btn):
            button.setEnabled(has_entries)

    def set_all_checked(self, checked):
        self._checked = {id(entry) for entry in self._entries} if checked else set()
        self._scroll.refresh()

    def checked_entries(self):
        return [entry for entry in self._entries if id(entry) in self._checked]

    def _refresh_row(self, entry):
        self._thumb_cache.pop(id(entry), None)
        self._filter_list()

    def _filter_list(self):
        query = self._search_entry.text().casefold().strip()
        rows = [(entry.name, entry) for entry in self._entries if not query or query in ' '.join((
            entry.name, entry.file_path, entry.format_name, entry.size_str)).casefold()]
        selection = self._scroll.selectionModel()
        selection.blockSignals(True)
        self._model.reset_rows(rows)
        self._select(self._active_entry, emit=False)
        selection.blockSignals(False)


# Reuse the exact shared slider/input for image authoring and text overlays.
class _SliderRow(SliderInput):
    pass


def _sat_gradient_css(hue_val: int) -> str:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(((hue_val + 180) % 360) / 360.0, 1.0, 1.0)
    vivid = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    return f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #808080, stop:1 {vivid})"


class _GradSliderRow(_SliderRow):
    HUE_CSS = HUE_GRADIENT
    LIGHT_CSS = LIGHTNESS_GRADIENT

    def __init__(self, label, lo, hi, default, gradient_css='', parent=None):
        super().__init__(label, lo, hi, default, parent)
        self.set_gradient(gradient_css)

    def set_gradient(self, gradient_css):
        self._slider.setStyleSheet(_texture_slider_ss(gradient_css))


# Right panel: info + quick-edit + operations
class _RightPanel(QWidget):
    WIDTH = 330

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
    sig_pick_color  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(286)
        self.setMaximumWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(ss_bg_dark())

        self._document_loaded = False
        self._entry_buttons, self._document_buttons = [], []

        scroll = QScrollArea()
        self._scroll = scroll

        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(scroll)
        inner = QWidget()
        inner.setStyleSheet(ss_bg_dark())
        lay = configure_layout(QVBoxLayout(inner), LayoutRole.PAGE)

        # Texture Info
        info_card, info_lay = self._card(inner, ui_text("ui_texture_texture_info"), "fa6s.circle-info")

        # Name (editable)
        name_field, name_lay, _, _ = make_editor_field_shell(ui_text("ui_texture_name"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(ui_text("ui_texture_texture_name"))
        configure_input(self._name_edit, monospace=True)
        name_lay.addWidget(self._name_edit)
        info_lay.addWidget(name_field)

        # Path (editable)
        path_field, path_lay, _, _ = make_editor_field_shell(ui_text("ui_texture_path"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(ui_text("ui_texture_file_path"))
        configure_input(self._path_edit, monospace=True)
        path_lay.addWidget(self._path_edit)
        info_lay.addWidget(path_field)

        self._size_lbl   = self._info_row(ui_text("sound_field_size"),   "—")
        self._fmt_lbl    = self._info_row(ui_text("ui_texture_format"), "—")
        self._mip_lbl    = self._info_row(ui_text("ui_texture_mipmaps"),"—")
        for w in (self._size_lbl, self._fmt_lbl, self._mip_lbl):
            info_lay.addWidget(w)

        # Copy + Rename buttons
        cr_row = configure_layout(QVBoxLayout(), LayoutRole.FIELD)
        copy_btn = QPushButton(ui_text("ui_texture_copy_name"))
        copy_btn.setIcon(qta.icon("fa6s.copy", color=P.get("button_text", P["text_main"])))
        copy_btn.setIconSize(QSize(12, 12))
        configure_button(copy_btn, height=Size.COMPACT_CONTROL)
        copy_btn.clicked.connect(self.sig_copy_name)
        self._entry_buttons.append(copy_btn)
        cr_row.addWidget(copy_btn)

        self._rename_btn = QPushButton(ui_text("ui_texture_rename"))
        self._rename_btn.setIcon(qta.icon("fa6s.pen", color=P.get("button_text", P["text_main"])))
        self._rename_btn.setIconSize(QSize(12, 12))
        configure_button(self._rename_btn, height=Size.COMPACT_CONTROL)
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._emit_rename)
        cr_row.addWidget(self._rename_btn)
        info_lay.addLayout(cr_row)
        lay.addWidget(info_card)

        # Quick Edits
        edit_card, edit_lay = self._card(inner, ui_text("ui_texture_quick_edits"), "fa6s.sliders")

        self._brightness = _SliderRow(ui_text("ui_texture_brightness"), -100, 100, 0)
        self._contrast   = _SliderRow(ui_text("ui_texture_contrast"),   -100, 100, 0)
        self._sharpness  = _SliderRow(ui_text("ui_texture_sharpness"),  -100, 100, 0)

        for sl in (self._brightness, self._contrast, self._sharpness):
            sl.value_changed.connect(self._on_slider_changed)
            edit_lay.addWidget(sl)

        # Hue / Saturation sub-group
        edit_lay.addWidget(self._section_label(ui_text("ui_texture_hue_saturation")))

        self._hue        = _GradSliderRow(ui_text("ui_texture_hue"),        -180, 180, 0, _GradSliderRow.HUE_CSS)
        self._saturation = _GradSliderRow(ui_text("ui_texture_saturation"),  -100, 100, 0, _sat_gradient_css(0))
        self._lightness  = _GradSliderRow(ui_text("ui_texture_lightness"),   -100, 100, 0, _GradSliderRow.LIGHT_CSS)

        for control, key in ((self._brightness, 'brightness'), (self._contrast, 'contrast'),
                             (self._sharpness, 'sharpness'), (self._hue, 'hue'),
                             (self._saturation, 'saturation'), (self._lightness, 'lightness')):
            control.setToolTip(ui_text('texture_adjust_' + key))

        for sl in (self._hue, self._saturation, self._lightness):
            sl.value_changed.connect(self._on_slider_changed)
            edit_lay.addWidget(sl)

        # Colorize checkbox
        colorize_row = QHBoxLayout()
        colorize_row.setSpacing(6)
        self._colorize_chk = QCheckBox(ui_text("ui_texture_colorize"))
        self._colorize_chk.setFont(ui_font(TypeSize.BODY))
        self._colorize_chk.setStyleSheet(ss_check())
        self._colorize_chk.stateChanged.connect(self._on_slider_changed)
        edit_lay.addWidget(self._colorize_chk)

        self._color_swatch = QPushButton()
        self._color_swatch.setFixedSize(32, 24)
        self._color_swatch.setToolTip(ui_text("ui_texture_choose_color"))
        self._color_swatch.clicked.connect(self._choose_color)
        colorize_row.addWidget(self._color_swatch)

        self._hex_edit = QLineEdit(DEFAULT_COLORIZE_HEX)
        self._hex_edit.setValidator(QRegularExpressionValidator(QRegularExpression('#?[0-9a-fA-F]{6}'), self._hex_edit))
        self._hex_edit.setMaximumWidth(92)
        configure_input(self._hex_edit, height=Size.CONTROL, monospace=True)
        self._hex_edit.editingFinished.connect(self._apply_hex_edit)
        colorize_row.addWidget(self._hex_edit)

        pick_btn = _icon_button("fa6s.eye-dropper", ui_text("ui_texture_pick_color"), inline_picker=True)
        pick_btn.clicked.connect(self.sig_pick_color)
        colorize_row.addWidget(pick_btn)
        colorize_row.addStretch()
        edit_lay.addLayout(colorize_row)
        self.set_colorize_hex(DEFAULT_COLORIZE_HEX, update_sliders=False)

        # Flip / Rotate row
        frow = configure_layout(QVBoxLayout(), LayoutRole.FIELD)
        for lbl, icon_name, sig in (
            (ui_text("ui_texture_flip_h"), "fa6s.arrows-left-right", self.sig_flip_h),
            (ui_text("ui_texture_flip_v"), "fa6s.arrows-up-down", self.sig_flip_v),
        ):
            b = QPushButton(lbl)
            b.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
            b.setIconSize(QSize(12, 12))
            configure_button(b)
            b.clicked.connect(sig)
            frow.addWidget(b)
        edit_lay.addLayout(frow)

        rrow = QHBoxLayout()
        self._rotation_row = rrow
        rrow.setSpacing(Size.GAP_SM)
        for deg, lbl, icon_name in (
            (90, "90°", "fa6s.rotate-right"),
            (180, "180°", "fa6s.rotate"),
            (270, "270°", "fa6s.rotate-left"),
        ):
            b = QPushButton(lbl)
            b.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
            b.setIconSize(QSize(12, 12))
            configure_button(b)
            b.clicked.connect(lambda _, d=deg: self.sig_rotate.emit(d))
            rrow.addWidget(b)
        edit_lay.addLayout(rrow)

        # Add Text (Quick Edits shortcut)
        add_text_btn = QPushButton(ui_text("ui_texture_add_text"))
        add_text_btn.setIcon(qta.icon("fa6s.font", color=P.get("button_text", P["text_main"])))
        add_text_btn.setIconSize(QSize(12, 12))
        configure_button(add_text_btn)
        add_text_btn.clicked.connect(self.sig_add_text)
        edit_lay.addWidget(add_text_btn)

        # Apply / Reset
        ar_row = configure_layout(QVBoxLayout(), LayoutRole.FIELD)
        self._apply_btn = QPushButton(ui_text("ui_texture_apply"))
        self._apply_btn.setIcon(qta.icon("fa6s.check", color=P.get("button_text", P["text_main"])))
        self._apply_btn.setIconSize(QSize(12, 12))
        configure_button(self._apply_btn, accent=True)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._emit_apply)
        ar_row.addWidget(self._apply_btn)

        reset_btn = QPushButton(ui_text("ui_texture_reset"))
        reset_btn.setIcon(qta.icon("fa6s.rotate-left", color=P.get("button_text", P["text_main"])))
        reset_btn.setIconSize(QSize(12, 12))
        configure_button(reset_btn)
        reset_btn.clicked.connect(self._reset_sliders)
        ar_row.addWidget(reset_btn)
        reset_btn.hide()
        edit_lay.addLayout(ar_row)
        self._rebuild_mips = QCheckBox(ui_text('texture_rebuild_mips'))
        self._rebuild_mips.setChecked(True)
        self._rebuild_mips.setStyleSheet(ss_check())
        self._rebuild_mips.setToolTip(ui_text('texture_rebuild_hint'))
        edit_lay.addWidget(self._rebuild_mips)
        impact = QLabel(ui_text('texture_edit_impact'))
        impact.setWordWrap(True)
        impact.setStyleSheet(ss_dim_label())
        edit_lay.addWidget(impact)
        self._edit_card = edit_card
        lay.addWidget(edit_card)

        # Operations
        ops_card, ops_lay = self._card(inner, ui_text("ui_texture_operations"), "fa6s.file-export")

        for lbl, icon_name, sig, acc in (
            (ui_text("ui_texture_export_dds"), "fa6s.file-export", self.sig_export_dds, False),
            (ui_text("ui_texture_export_png"), "fa6s.image", self.sig_export_png, False),
            (ui_text("ui_texture_export_all_2"), "fa6s.folder-open", self.sig_export_all, False),
            (ui_text("ui_texture_replace"), "fa6s.repeat", self.sig_replace, False),
            (ui_text("ui_texture_port_from_xfbin_2"), "fa6s.file-import", self.sig_port, False),
        ):
            b = QPushButton(lbl)
            b.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
            b.setIconSize(QSize(12, 12))
            configure_button(b, accent=acc)
            b.clicked.connect(sig)
            if sig in (self.sig_export_all, self.sig_port):
                self._document_buttons.append(b)
            else:
                self._entry_buttons.append(b)
            ops_lay.addWidget(b)
        lay.addWidget(ops_card)

        lay.addStretch()
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        root.addWidget(scroll)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(16)   # ~1 frame — smooth live preview
        self._preview_timer.timeout.connect(self._emit_apply_preview)
        self._pending_entry: TextureEntry | None = None
        self._resetting = False
        self.set_entry(None)

    # Helpers
    def set_panel_width(self, width: int):
        width = max(260, min(self.WIDTH, int(width)))
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self._rotation_row.setDirection(QHBoxLayout.Direction.TopToBottom if width < 300 else QHBoxLayout.Direction.LeftToRight)
        fit_scroll_page(self._scroll)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_scroll'):
            fit_scroll_page(self._scroll)

    def _card(self, parent, title: str, icon_name: str):
        card, layout = make_editor_card(parent)
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        add_editor_card_title(layout, title, icon_name)
        return card, layout

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(ui_font(TypeSize.CODE, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(0, 6, 0, 0)
        return lbl

    def _info_row(self, key: str, val: str) -> QWidget:
        w   = QWidget()
        w.setStyleSheet(ss_transparent())
        row = QHBoxLayout(w)
        row.setContentsMargins(*Insets.NONE)
        row.setSpacing(6)
        klbl = QLabel(key + ":")
        klbl.setFont(ui_font(TypeSize.LABEL))
        klbl.setFixedWidth(92)
        klbl.setWordWrap(True)
        klbl.setStyleSheet(ss_dim_label())
        vlbl = QLabel(val)
        vlbl.setFont(mono_font(TypeSize.LABEL))
        vlbl.setStyleSheet(ss_main_label())
        vlbl.setWordWrap(True)
        vlbl.setMinimumWidth(0)
        vlbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(klbl)
        row.addWidget(vlbl, 1)
        w._val = vlbl
        return w

    # Public API
    def set_entry(self, entry: TextureEntry | None):
        self._pending_entry = entry
        for control in (*self._entry_buttons, self._name_edit, self._path_edit):
            control.setEnabled(entry is not None)
        for control in self._document_buttons:
            control.setEnabled(self._document_loaded)
        self._edit_card.setEnabled(entry is not None and entry_editable(entry))
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
        self._fmt_lbl._val.setText(entry.format_name)
        self._fmt_lbl._val.setToolTip(ui_text("ui_texture_value_id_value", p0=entry.format_name, p1=entry.pixel_format))
        self._mip_lbl._val.setText(str(entry.mipmap_count))
        self._apply_btn.setEnabled(entry.pil_image is not None)
        self._rename_btn.setEnabled(True)

    def set_document_loaded(self, loaded):
        self._document_loaded = loaded
        for control in self._document_buttons:
            control.setEnabled(loaded)

    def _emit_rename(self):
        name = self._name_edit.text().strip()
        path = self._path_edit.text().strip()
        if name:
            self.sig_rename.emit(name, path)

    def _choose_color(self):
        current = QColor(self._hex_edit.text())
        color = QColorDialog.getColor(
            current if current.isValid() else QColor(DEFAULT_COLORIZE_HEX),
            self,
            ui_text("ui_texture_choose_color"),
        )
        if color.isValid():
            self.set_colorize_hex(color.name().upper())

    def _apply_hex_edit(self):
        if self._hex_edit.hasAcceptableInput():
            self.set_colorize_hex(self._hex_edit.text())

    def set_colorize_hex(self, hex_color: str, *, update_sliders: bool = True):
        normalized = _normalize_hex(hex_color)
        if normalized is None:
            normalized = DEFAULT_COLORIZE_HEX
        self._hex_edit.blockSignals(True)
        self._hex_edit.setText(normalized)
        self._hex_edit.blockSignals(False)
        self._color_swatch.setStyleSheet(
            f"QPushButton {{ background: {normalized}; border: 1px solid {P['border']}; "
            "border-radius: 4px; }"
        )
        if update_sliders:
            import colorsys
            r, g, b = (v / 255.0 for v in _hex_to_rgb(normalized))
            hue, sat, _val = colorsys.rgb_to_hsv(r, g, b)
            self._hue._slider.setValue(int(round(hue * 360 - 180)))
            self._saturation._slider.setValue(int(round(max(-100, min(100, (sat - 0.5) * 200)))))
            self._colorize_chk.setChecked(True)
            self._on_slider_changed(0)

    def get_adjustments(self, *, commit=False) -> dict:
        if commit:
            for row in (self._brightness, self._contrast, self._sharpness,
                        self._hue, self._saturation, self._lightness):
                row.input.interpretText()
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
        if getattr(self, '_resetting', False):
            return
        # Keep saturation gradient in sync with the current hue
        self._saturation.set_gradient(_sat_gradient_css(self._hue.value))
        self._preview_timer.start()

    def _emit_apply_preview(self):
        self.sig_apply_edits.emit({'preview': True, **self.get_adjustments()})

    def _emit_apply(self):
        self.sig_apply_edits.emit({'preview': False, **self.get_adjustments(commit=True)})

    def _reset_sliders(self, *_):
        self.reset_adjustments()
        self.sig_reset_edits.emit()

    def reset_adjustments(self):
        self._resetting = True
        for sl in (self._brightness, self._contrast, self._sharpness,
                   self._hue, self._saturation, self._lightness):
            sl.reset()
        self._colorize_chk.setChecked(False)
        self.set_colorize_hex(DEFAULT_COLORIZE_HEX, update_sliders=False)
        self._preview_timer.stop()
        self._resetting = False


# Port dialog
class _PortDialog(QDialog):
    def __init__(self, entries: list[TextureEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle(ui_text("ui_texture_port_textures"))
        self.setMinimumSize(480, 500)
        self.setStyleSheet(ss_dialog())
        self._entries = entries
        self._selected: list[TextureEntry] = []

        lay = QVBoxLayout(self)
        configure_layout(lay, LayoutRole.PAGE)

        hdr = QLabel(ui_text("ui_texture_select_textures_to_port_into_the_current_xfbin"))
        hdr.setFont(ui_font(TypeSize.CODE))
        hdr.setStyleSheet(ss_field_label())
        lay.addWidget(hdr)

        filt = QLineEdit()
        configure_search(filt)
        filt.textChanged.connect(self._filter)
        lay.addWidget(filt)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setFont(mono_font(TypeSize.BODY))
        self._list.setStyleSheet(ss_listwidget())
        self._populate(entries)
        lay.addWidget(self._list, 1)

        # Buttons
        brow = QHBoxLayout()
        sel_all = QPushButton(ui_text("ui_texture_select_all"))
        configure_button(sel_all)
        sel_all.clicked.connect(self._list.selectAll)
        brow.addWidget(sel_all)
        brow.addStretch()

        ok_btn = QPushButton(ui_text("ui_texture_port_selected"))
        configure_button(ok_btn, accent=True)
        ok_btn.clicked.connect(self._accept)
        brow.addWidget(ok_btn)

        cancel_btn = QPushButton(ui_text("ui_texture_cancel"))
        configure_button(cancel_btn)
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


class _BatchReplaceDialog(QDialog):
    """Choose replacement sources and preview every safe filename match."""

    def __init__(self, all_entries, checked_entries, start_dir, parent=None):
        super().__init__(parent)
        self._all_entries = list(all_entries)
        self._checked_entries = list(checked_entries)
        self._start_dir = start_dir
        self._paths = []
        self._matches = []
        self.setWindowTitle(ui_text("ui_texture_batch_replace_title"))
        self.resize(780, 540)
        self.setStyleSheet(ss_dialog())

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(Size.CARD_GAP)

        intro = QLabel(ui_text("ui_texture_batch_replace_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet(ss_dim_label())
        root.addWidget(intro)

        source_row = QHBoxLayout()
        source_row.setSpacing(6)
        folder_btn = QPushButton(ui_text("ui_texture_choose_folder"))
        configure_button(folder_btn, accent=True)
        folder_btn.clicked.connect(self._choose_folder)
        source_row.addWidget(folder_btn)

        files_btn = QPushButton(ui_text("ui_texture_choose_files"))
        configure_button(files_btn)
        files_btn.clicked.connect(self._choose_files)
        source_row.addWidget(files_btn)

        self._source_lbl = QLabel(ui_text("ui_texture_no_replacement_source"))
        self._source_lbl.setStyleSheet(ss_dim_label())
        source_row.addWidget(self._source_lbl, 1)
        root.addLayout(source_row)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(Size.GAP)
        scope_lbl = QLabel(ui_text("ui_texture_batch_replace_scope"))
        scope_lbl.setStyleSheet(ss_field_label())
        scope_row.addWidget(scope_lbl)


        self._checked_radio = QRadioButton(
            ui_text("ui_texture_checked_textures_value", p0=len(self._checked_entries))
        )
        self._checked_radio.setStyleSheet(ss_radio())
        self._checked_radio.setEnabled(bool(self._checked_entries))
        self._checked_radio.setChecked(bool(self._checked_entries))
        self._checked_radio.toggled.connect(self._refresh_preview)
        scope_row.addWidget(self._checked_radio)

        self._all_radio = QRadioButton(ui_text("ui_texture_all_matched_textures"))
        self._all_radio.setStyleSheet(ss_radio())
        self._all_radio.setChecked(not self._checked_entries)
        self._all_radio.toggled.connect(self._refresh_preview)
        scope_row.addWidget(self._all_radio)
        scope_row.addStretch()
        root.addLayout(scope_row)

        self._summary = QLabel("")
        self._summary.setStyleSheet(ss_dim_label())
        root.addWidget(self._summary)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels((
            ui_text("ui_texture_batch_status"),
            ui_text("ui_texture_batch_texture"),
            ui_text("ui_texture_batch_replacement_file"),
        ))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        configure_table(self._table)
        root.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(ui_text("ui_texture_cancel"))
        configure_button(cancel)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._replace_btn = QPushButton(ui_text("ui_texture_replace_matched_textures"))
        configure_button(self._replace_btn, accent=True)
        self._replace_btn.setEnabled(False)
        self._replace_btn.clicked.connect(self.accept)
        buttons.addWidget(self._replace_btn)
        root.addLayout(buttons)

        self._refresh_preview()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, ui_text("ui_texture_choose_replacement_folder"), self._start_dir
        )
        if not folder:
            return
        self._paths = [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name))
        ]
        self._source_lbl.setText(folder)
        self._refresh_preview()

    def _choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            ui_text("ui_texture_choose_replacement_textures"),
            self._start_dir,
            "All Files (*)",
        )
        if not paths:
            return
        self._paths = paths
        self._source_lbl.setText(ui_text("ui_texture_files_selected_value", p0=len(paths)))
        self._refresh_preview()

    def _targets(self):
        return self._checked_entries if self._checked_radio.isChecked() else self._all_entries

    def _refresh_preview(self):
        self._matches, unsupported = match_texture_files(self._targets(), self._paths)
        self._table.setRowCount(0)
        labels = {
            "matched": ui_text("ui_texture_batch_matched"),
            "missing": ui_text("ui_texture_batch_missing"),
            "duplicate": ui_text("ui_texture_batch_duplicate"),
        }
        colors = {
            "matched": "#48C9B0",
            "missing": P["text_dim"],
            "duplicate": "#F39C12",
        }
        counts = {"matched": 0, "missing": 0, "duplicate": 0}
        for match in self._matches:
            counts[match.status] += 1
            if match.status == "duplicate":
                source = "; ".join(os.path.basename(p) for p in match.candidates)
            elif match.source_path:
                source = os.path.basename(match.source_path)
            else:
                source = ui_text("ui_texture_batch_not_found")
            self._append_row(
                labels[match.status],
                match.entry.name or "<unnamed>",
                source,
                colors[match.status],
            )
        for path in unsupported:
            self._append_row(
                ui_text("ui_texture_batch_unsupported"),
                "-",
                os.path.basename(path),
                "#E74C3C",
            )
        self._summary.setText(ui_text(
            "ui_texture_batch_summary",
            matched=counts["matched"],
            missing=counts["missing"],
            duplicate=counts["duplicate"],
            unsupported=len(unsupported),
        ))
        self._replace_btn.setEnabled(counts["matched"] > 0)

    def _append_row(self, status, texture, source, color):
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, value in enumerate((status, texture, source)):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setForeground(QColor(color))
            self._table.setItem(row, col, item)

    def matched_replacements(self):
        return [
            (m.entry, m.source_path)
            for m in self._matches
            if m.status == "matched"
        ]


# Export-all worker
class _ExportSignals(QObject):
    progress = pyqtSignal(int)
    done     = pyqtSignal(int, str)   # count, errors


class _ExportWorker(QRunnable):
    def __init__(self, entries: list[TextureEntry], folder: str, fmt: str, signals, cancel):
        super().__init__()
        self._entries = entries
        self._folder  = folder
        self._fmt     = fmt   # 'dds' or 'png'
        self.signals, self.cancel = signals, cancel

    def run(self):
        ok = 0
        errs = []
        used = set()
        for i, e in enumerate(self._entries):
            if self.cancel.is_set():
                break
            try:
                if self._fmt == 'dds':
                    data = export_entry_dds(e)
                    ext  = '.dds'
                else:
                    data = export_entry_png(e)
                    ext  = '.png'
                if data:
                    out = os.path.join(self._folder, export_filename(e.name, ext, used))
                    with open(out, 'wb') as f:
                        f.write(data)
                    ok += 1
                else:
                    errs.append(e.name)
            except Exception as ex:
                errs.append(f"{e.name}: {ex}")
            self.signals.progress.emit(i + 1)
        self.signals.done.emit(ok, '\n'.join(errs[:5]) if errs else '')


# Main Texture Editor widget
class _AdjustmentSignals(QObject):
    finished = pyqtSignal(int, object, str)


class _AdjustmentJob(QRunnable):
    def __init__(self, token, image, adjustments, signals):
        super().__init__()
        self.token, self.image, self.adjustments, self.signals = token, image, adjustments, signals

    def run(self):
        try:
            image = _apply_adjustments(self.image, self.adjustments)
            self.signals.finished.emit(self.token, image, '')
        except Exception as exc:
            self.signals.finished.emit(self.token, None, str(exc))


class _TextureLoadSignals(QObject):
    finished = pyqtSignal(int, str, object, object, str)


class _TextureLoadJob(QRunnable):
    def __init__(self, token, path, signals):
        super().__init__()
        self.token, self.path, self.signals = token, path, signals

    def run(self):
        try:
            xfbin, entries = load_xfbin(self.path, decode_images=False)
            self.signals.finished.emit(self.token, self.path, xfbin, entries, '')
        except Exception as exc:
            self.signals.finished.emit(self.token, self.path, None, None, str(exc))


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
        self._last_compact_shell = None
        self._history = EditorHistory(limit=80)
        self._history_revision = 0
        self._undo_btn: QPushButton | None = None
        self._redo_btn: QPushButton | None = None
        self._baseline = {}
        self._preview_image = None
        self._preview_token = 0
        self._preview_running = False
        self._preview_pending = None
        self._preview_signals = _AdjustmentSignals()
        self._preview_signals.finished.connect(self._preview_finished)
        self._load_token = 0
        self._load_signals = _TextureLoadSignals()
        self._load_signals.finished.connect(self._load_finished)
        self._export_state = None

        self._build_ui()
        install_file_actions(self, self._save_btn, native=self._save_xfbin_as, existing_button=getattr(self, "_saveas_btn", None))
        install_editor_chrome(self)

    # UI construction
    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        # A wide-layout minimum must not prevent the resize event that switches
        # to the compact layout. Child controls retain their normal constraints.
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(Size.COMPACT_BREAKPOINT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        open_btn = QPushButton(ui_text("btn_open_file"))
        self._open_btn = open_btn
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(self._open_xfbin)
        open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(ui_text("btn_save_file"))
        configure_button(self._save_btn, accent=True)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_xfbin)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(ui_text("ui_btladjprm_no_file_loaded"))
        self._file_label.setMinimumWidth(0)
        self._file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label, 1)

        self._status_lbl = QLabel("")
        self._status_lbl.setMinimumWidth(0)
        self._status_lbl.setMaximumWidth(320)
        self._status_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._status_lbl.setFont(ui_font(TypeSize.BODY))
        self._status_lbl.setStyleSheet(ss_dim_label())
        top_layout.addWidget(self._status_lbl)

        self._undo_btn = _icon_button("fa6s.arrow-rotate-left", ui_text("ui_texture_undo"))
        self._undo_btn.clicked.connect(self._undo)
        self._undo_btn.setProperty("designAction", 'undo')
        self._undo_btn.setEnabled(False)
        top_layout.addWidget(self._undo_btn)

        self._redo_btn = _icon_button("fa6s.arrow-rotate-right", ui_text("ui_texture_redo"))
        self._redo_btn.clicked.connect(self._redo)
        self._redo_btn.setProperty("designAction", 'redo')
        self._redo_btn.setEnabled(False)
        top_layout.addWidget(self._redo_btn)
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        self._workspace = main
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        self._list_frame = EditorSidebar()


        list_layout = self._list_frame.content_layout


        self._grid = _TextureList()
        self._grid.texture_selected.connect(self._on_select)
        self._grid.sig_new.connect(self._new_texture)
        self._grid.sig_duplicate.connect(self._duplicate_texture)
        self._grid.sig_delete.connect(self._delete_texture)
        self._grid.sig_batch_replace.connect(self._batch_replace)
        self._grid.sig_export_checked_png.connect(self._export_checked_png)
        list_layout.addWidget(self._grid)
        main_layout.addWidget(self._list_frame)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        content = QWidget()
        content.setStyleSheet(ss_bg_dark())
        content_layout = QHBoxLayout(content)
        configure_layout(content_layout, LayoutRole.ROOT)

        self._preview = _PreviewPanel()
        self._preview.level_changed.connect(lambda _: self._show_preview(self._preview_image))
        self._preview.face_changed.connect(lambda _: self._show_preview(self._preview_image))
        self._preview.setMinimumWidth(300)
        content_layout.addWidget(self._preview, 1)

        right_divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


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
        self._right.sig_pick_color.connect(lambda: self._preview.set_color_pick_enabled(True))
        self._preview.color_picked.connect(self._right.set_colorize_hex)
        self._inspector_pane = EditorSidebarPane(self._right, self, edge='right', label='texture_inspector')
        content_layout.addWidget(self._inspector_pane)

        main_layout.addWidget(content, 1)
        root.addWidget(main, 1)
        self._apply_responsive_shell()

    def _is_compact_shell(self) -> bool:
        return self.width() < 920

    def _apply_responsive_shell(self):
        compact = self._is_compact_shell()
        if compact == self._last_compact_shell:
            return
        self._last_compact_shell = compact
        if compact:
            self._list_frame.setFixedWidth(236)
            self._preview.setMinimumWidth(210)
            self._right.set_panel_width(286)
            self._status_lbl.setMaximumWidth(240)
        else:
            self._list_frame.setFixedWidth(276)
            self._preview.setMinimumWidth(300)
            self._right.set_panel_width(_RightPanel.WIDTH)
            self._status_lbl.setMaximumWidth(360)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_shell()

    def closeEvent(self, event):
        self._right._preview_timer.stop()
        self._preview_token += 1
        self._load_token += 1
        self._preview_pending = None
        if self._export_state:
            self._export_state[3].set()
        super().closeEvent(event)

    # Open / Save
    def _open_xfbin(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("xfa_btn_open"), _texture_open_dir(), "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        if self._unsaved or any(self._right.get_adjustments().values()) or (self._cur_entry is not None and (
                self._right._name_edit.text().strip(), self._right._path_edit.text().strip()) != (
                    self._cur_entry.name, self._cur_entry.file_path)):
            choice = QMessageBox.question(self, ui_text('ui_texture_save_as'), ui_text('texture_unsaved_open'),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Save:
                self._save_xfbin()
                if self._unsaved or any(self._right.get_adjustments().values()):
                    return
        create_backup_on_open(path)
        self._status(ui_text("ui_effect_loading"))
        self._load_token += 1
        self._open_btn.setEnabled(False)
        self._workspace.setEnabled(False)
        QThreadPool.globalInstance().start(_TextureLoadJob(self._load_token, path, self._load_signals))

    def _load_finished(self, token, path, xfbin, entries, error):
        if token != self._load_token:
            return
        self._open_btn.setEnabled(True)
        self._workspace.setEnabled(True)
        if error:
            self._status(error, error=True)
            QMessageBox.critical(self, ui_text('ui_charviewer_load_error'), error)
            return
        self._accept_loaded(path, xfbin, entries)

    def _do_load(self, path: str):
        try:
            xfbin, entries = load_xfbin(path, decode_images=False)
        except Exception as exc:
            self._status(f"Error loading: {exc}", error=True)
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(exc))
            return
        self._accept_loaded(path, xfbin, entries)

    def _accept_loaded(self, path, xfbin, entries):
        self._xfbin      = xfbin
        self._entries    = entries
        self._xfbin_path = path
        self._cur_entry  = None
        self._unsaved    = False
        import uuid
        self._baseline = {}
        for entry in entries:
            entry.chunk._texture_identity = uuid.uuid4().hex
            snapshot = copy.copy(entry)
            snapshot.chunk = copy.deepcopy(entry.chunk)
            self._baseline[entry.chunk._texture_identity] = snapshot
        self._preview_token += 1
        self._preview_pending = None
        self._right.reset_adjustments()
        self._history.clear()
        self._update_history_buttons()

        self._grid.load(entries)
        self._grid.set_file_loaded(True)
        self._right.set_document_loaded(True)
        self._preview.show_image(None)
        self._right.set_entry(None)
        self._save_btn.setEnabled(True)

        fname = os.path.basename(path)
        set_file_label(self._file_label, path)
        n_tex = len(entries)
        self._status(f"Loaded  {fname}  —  {n_tex} texture{'s' if n_tex != 1 else ''}")
        if entries:
            self._grid.select_entry(entries[0])

    def _save_xfbin(self):
        if self._xfbin is None or self._xfbin_path is None:
            return
        if not self._flush_adjustments():
            return
        try:
            save_xfbin(self._xfbin, self._xfbin_path)
            self._unsaved = False
            set_file_label(self._file_label, self._xfbin_path)
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
        if not self._flush_adjustments():
            return
        try:
            save_xfbin(self._xfbin, path)
            self._xfbin_path = path
            self._unsaved    = False
            set_file_label(self._file_label, path)
            self._status(f"Saved  {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(exc))

    def _mark_dirty(self):
        self._unsaved = True
        if self._xfbin_path:
            set_file_label(self._file_label, self._xfbin_path, dirty=True)
        self._update_history_buttons()

    def _update_history_buttons(self):
        if self._undo_btn is not None:
            self._undo_btn.setEnabled(self._history.can_undo())
        if self._redo_btn is not None:
            self._redo_btn.setEnabled(self._history.can_redo())

    def _push_history(self):
        if self._xfbin is None:
            return
        # NuccChunk equality compares names/paths, not pixels. A revision keeps
        # distinct image edits from being discarded by generic history dedup.
        self._history.push((self._history_revision, self._xfbin.pages))
        self._history_revision += 1
        self._update_history_buttons()

    def _current_entry_key(self):
        if self._cur_entry is None:
            return None
        return (self._cur_entry.name, self._cur_entry.file_path)

    def _restore_history_state(self, pages, preferred_key=None):
        if self._xfbin is None:
            return
        self._right.reset_adjustments()
        self._cur_entry = None
        self._preview_token += 1
        self._preview_pending = None
        self._xfbin.pages = copy.deepcopy(pages)
        self._entries = refresh_texture_entries(self._xfbin, decode_images=False)
        self._grid.load(self._entries)
        self._grid.set_file_loaded(True)

        target = None
        if preferred_key is not None:
            target = next(
                (e for e in self._entries if (e.name, e.file_path) == preferred_key),
                None,
            )
        if target is None and self._entries:
            target = self._entries[0]

        if target is not None:
            self._grid.select_entry(target)
        else:
            self._cur_entry = None
            self._orig_pil = None
            self._preview.show_image(None)
            self._right.set_entry(None)
        self._unsaved = True
        if self._xfbin_path:
            set_file_label(self._file_label, self._xfbin_path, dirty=True)
        self._update_history_buttons()

    def _undo(self):
        if self._xfbin is None:
            return
        if any(self._right.get_adjustments().values()):
            self._right.reset_adjustments()
            self._reset_edits()
            return
        state = self._history.undo((self._history_revision, self._xfbin.pages))
        if state is None:
            return
        self._history_revision = state[0]
        self._restore_history_state(state[1], self._current_entry_key())
        self._status(ui_text("ui_texture_undo_done"))

    def _redo(self):
        if self._xfbin is None:
            return
        state = self._history.redo((self._history_revision, self._xfbin.pages))
        if state is None:
            return
        self._history_revision = state[0]
        self._restore_history_state(state[1], self._current_entry_key())
        self._status(ui_text("ui_texture_redo_done"))

    def _reload_entries(self, select_entry: TextureEntry | None = None):
        if self._xfbin is None:
            return
        self._entries = refresh_texture_entries(self._xfbin, decode_images=False)
        self._grid.load(self._entries)
        self._grid.set_file_loaded(True)

        if select_entry is not None:
            match = self._find_matching_entry(select_entry)
            if match is not None:
                self._grid.select_entry(match)
                return

        self._cur_entry = None
        self._orig_pil = None
        self._preview.show_image(None)
        self._right.set_entry(None)

    def _find_matching_entry(self, target: TextureEntry) -> TextureEntry | None:
        for entry in self._entries:
            if entry.chunk is target.chunk:
                return entry
        for entry in self._entries:
            if entry.name == target.name and entry.file_path == target.file_path:
                return entry
        return None

    # Selection
    def _on_select(self, entry: TextureEntry):
        if entry is self._cur_entry:
            return
        if not self._flush_adjustments():
            self._grid._select(self._cur_entry, emit=False)
            return
        self._preview_token += 1
        self._preview_pending = None
        self._right.reset_adjustments()
        self._cur_entry = entry
        self._orig_pil  = entry.pil_image.copy() if entry.pil_image else None
        self._right.set_entry(entry)
        self._preview.set_levels(entry.width, entry.height, entry.mipmap_count)
        textures = getattr(getattr(entry.chunk, 'nut', None), 'textures', ())
        self._preview.set_faces(6 if textures and getattr(textures[0], 'is_cube_map', False) else 0)
        self._show_preview(entry.pil_image)
        self._preview.surface.view.fit()

    def _show_preview(self, img: Image.Image | None):
        if self._cur_entry is None:
            self._preview.show_image(None)
            return
        e = self._cur_entry
        self._preview_image = img
        self._preview.set_levels(e.width, e.height, e.mipmap_count)
        level = self._preview.level.currentData() or 0
        face = self._preview.face.currentData() or 0
        original_entry = self._baseline.get(getattr(e.chunk, '_texture_identity', None))
        original = entry_image(original_entry, level, face) if original_entry else None
        if level or face:
            img = entry_image(e, level, face)
        info = f"{e.name}  |  {e.format_name}  |  {e.size_str}  |  {e.mipmap_count} mip"
        if img is None:
            info = ui_text('texture_unavailable_level')
        self._preview.show_image(img, info, original=original)

    def _flush_adjustments(self):
        if self._cur_entry is None:
            return True
        if not self._right._hex_edit.hasAcceptableInput():
            QMessageBox.warning(self, ui_text('ui_texture_choose_color'), ui_text('texture_invalid_color'))
            self._right._hex_edit.setFocus()
            return False
        name, path = self._right._name_edit.text().strip(), self._right._path_edit.text().strip()
        if (name, path) != (self._cur_entry.name, self._cur_entry.file_path):
            if not self._rename(name, path):
                return False
        adjustments = self._right.get_adjustments(commit=True)
        if any(adjustments.values()):
            return self._apply_edits({'preview': False, **adjustments})
        return True

    def _preview_finished(self, token, image, error):
        self._preview_running = False
        if token == self._preview_token:
            if error:
                self._status(error, error=True)
            else:
                self._show_preview(image)
        pending, self._preview_pending = self._preview_pending, None
        if pending is not None:
            self._start_preview(*pending)

    def _start_preview(self, token, image, adjustments):
        if self._preview_running:
            self._preview_pending = (token, image, adjustments)
            return
        self._preview_running = True
        QThreadPool.globalInstance().start(_AdjustmentJob(token, image, adjustments, self._preview_signals))

    # Live quick-edit preview
    def _apply_edits(self, adj: dict):
        if self._cur_entry is None or self._orig_pil is None:
            return False
        if not entry_editable(self._cur_entry):
            return False
        self._preview_token += 1

        if adj.get('preview', True):
            self._start_preview(self._preview_token, self._orig_pil, dict(adj))
            return True
        self._preview_pending = None
        if not any(value for key, value in adj.items() if key != 'preview'):
            return True
        try:
            img = _apply_adjustments(self._orig_pil, adj)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_texture_apply_error'), str(exc))
            return False

        # Permanent apply
        self._push_history()
        old_format = self._cur_entry.pixel_format
        err = apply_pil_edits_to_entry(self._cur_entry, img, rebuild_mips=self._right._rebuild_mips.isChecked())
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_apply_error"), err)
            return False
        self._orig_pil = img.copy()
        self._right.reset_adjustments()
        self._right.set_entry(self._cur_entry)
        self._grid.refresh_active_thumb()
        self._show_preview(img)
        fmt_note = ""
        if old_format != 17:
            fmt_note = ui_text("ui_texture_converted_to_rgba8888")
        self._status(f"Edits applied to  {self._cur_entry.name}{fmt_note}")
        self._mark_dirty()
        return True

    def _reset_edits(self):
        if self._cur_entry is None or self._orig_pil is None:
            return
        self._preview_token += 1
        self._preview_pending = None
        self._show_preview(self._orig_pil)

    # Flip / Rotate
    def _flip_h(self):
        if self._orig_pil is None or not self._flush_adjustments():
            return
        img = ImageOps.mirror(self._orig_pil)
        self._commit_edit(img)

    def _flip_v(self):
        if self._orig_pil is None or not self._flush_adjustments():
            return
        img = ImageOps.flip(self._orig_pil)
        self._commit_edit(img)

    def _rotate(self, deg: int):
        if self._orig_pil is None or not self._flush_adjustments():
            return
        img = self._orig_pil.rotate(-deg, expand=True)
        self._commit_edit(img)

    def _commit_edit(self, img: Image.Image):
        if self._cur_entry is None:
            return
        self._push_history()
        self._preview_token += 1
        self._preview_pending = None
        err = apply_pil_edits_to_entry(self._cur_entry, img, rebuild_mips=self._right._rebuild_mips.isChecked())
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_apply_error"), err)
            return
        self._orig_pil = img.copy()
        self._right.reset_adjustments()
        self._grid.refresh_active_thumb()
        self._right.set_entry(self._cur_entry)
        self._show_preview(img)
        self._mark_dirty()

    # Export single
    def _export_dds(self):
        if self._cur_entry is None:
            return
        if not self._flush_adjustments():
            return
        try:
            data = export_entry_dds(self._cur_entry)
        except ValueError as exc:
            QMessageBox.warning(self, ui_text('ui_texture_export'), str(exc))
            return
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
        if not self._flush_adjustments():
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
        dlg.setStyleSheet(ss_dialog())
        lay = QVBoxLayout(dlg)
        lay.setSpacing(Size.CARD_GAP)
        lbl = QLabel(ui_text("ui_texture_export_format"))
        lbl.setFont(ui_font(TypeSize.CODE))
        lbl.setStyleSheet(ss_field_label())
        lay.addWidget(lbl)
        btn_row = QHBoxLayout()
        for fmt in ('png', 'dds'):
            b = QPushButton(fmt.upper())
            configure_button(b, accent=fmt == 'png')
            b.clicked.connect(lambda _, f=fmt, d=dlg: (d.done(0), self._run_export_all(folder, f)))
            btn_row.addWidget(b)
        cancel = QPushButton(ui_text("ui_texture_cancel"))
        configure_button(cancel)
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        lay.addLayout(btn_row)
        dlg.exec()

    def _run_export_all(self, folder: str, fmt: str):
        self._run_export_entries(self._entries, folder, fmt)

    def _run_export_entries(self, entries: list[TextureEntry], folder: str, fmt: str):
        if self._export_state is not None or not self._flush_adjustments():
            return
        total = len(entries)
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

        signals, cancel = _ExportSignals(), threading.Event()
        # Copy wrappers/chunks so later editing cannot race an ongoing export.
        snapshot = copy.deepcopy(entries)
        worker = _ExportWorker(snapshot, folder, fmt, signals, cancel)
        self._export_state = (worker, signals, prog, cancel, folder)
        signals.progress.connect(prog.setValue)
        signals.done.connect(self._export_finished)
        prog.canceled.connect(cancel.set)
        prog.show()
        QThreadPool.globalInstance().start(worker)

    def _export_checked_png(self):
        entries = self._grid.checked_entries()
        if not entries:
            QMessageBox.information(
                self,
                ui_text("ui_texture_export_checked_png_title"),
                ui_text("ui_texture_check_at_least_one"),
            )
            return
        folder = QFileDialog.getExistingDirectory(
            self, ui_text("ui_texture_export_checked_choose_folder")
        )
        if folder:
            self._run_export_entries(entries, folder, "png")

    def _export_finished(self, ok, errs):
        if self._export_state is None:
            return
        worker, signals, prog, cancel, folder = self._export_state
        self._export_state = None
        prog.close()
        prog.deleteLater()
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
            game_files_dialog_dir(os.path.dirname(self._xfbin_path or '')),
            "Texture Files (*.dds *.png *.jpg *.jpeg *.bmp *.tga *.nut);;All Files (*)"
        )
        if not path:
            return
        if not self._flush_adjustments():
            return
        self._push_history()
        err = replace_texture_from_file(self._cur_entry, path)
        if err:
            QMessageBox.critical(self, ui_text("ui_texture_replace_error"), err)
            return
        self._orig_pil = self._cur_entry.pil_image.copy() if self._cur_entry.pil_image else None
        self._preview_token += 1
        self._preview_pending = None
        self._right.reset_adjustments()
        self._grid.refresh_active_thumb()
        self._right.set_entry(self._cur_entry)
        self._show_preview(self._cur_entry.pil_image)
        self._mark_dirty()
        self._status(f"Replaced  {self._cur_entry.name}  ←  {os.path.basename(path)}")

    def _batch_replace(self):
        if not self._entries:
            return
        dlg = _BatchReplaceDialog(
            self._entries,
            self._grid.checked_entries(),
            game_files_dialog_dir(os.path.dirname(self._xfbin_path or "")),
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._flush_adjustments():
            return
        replacements = dlg.matched_replacements()
        if replacements:
            self._push_history()
        replaced = 0
        failures = []
        for entry, path in replacements:
            err = replace_texture_from_file(entry, path)
            if err:
                failures.append(f"{entry.name}: {err}")
                continue
            replaced += 1
            self._grid._refresh_row(entry)

        if replaced:
            self._preview_token += 1
            self._preview_pending = None
            self._right.reset_adjustments()
            self._mark_dirty()
            if self._cur_entry is not None:
                self._orig_pil = (
                    self._cur_entry.pil_image.copy()
                    if self._cur_entry.pil_image else None
                )
                self._right.set_entry(self._cur_entry)
                self._show_preview(self._cur_entry.pil_image)
            self._status(ui_text("ui_texture_batch_replaced_value", p0=replaced))

        if failures:
            QMessageBox.warning(
                self,
                ui_text("ui_texture_batch_replace_title"),
                ui_text(
                    "ui_texture_batch_failures_value",
                    replaced=replaced,
                    failures="\n".join(failures[:10]),
                ),
            )

    # Port
    def _port(self):
        if self._xfbin is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_texture_port_from_xfbin"),
            game_files_dialog_dir(os.path.dirname(self._xfbin_path or '')),
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
        if not self._flush_adjustments():
            return

        self._push_history()
        added = port_entries_into_xfbin(self._xfbin, selected)
        self._reload_entries()
        self._mark_dirty()
        self._status(f"Ported {added} texture{'s' if added != 1 else ''}  ←  {os.path.basename(path)}")

    # Add / Duplicate / Delete
    def _new_texture(self):
        if self._xfbin is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_texture_new_texture"),
            game_files_dialog_dir(os.path.dirname(self._xfbin_path or '')),
            "Texture Files (*.dds *.png *.jpg *.jpeg *.bmp *.tga *.nut);;All Files (*)"
        )
        if not path:
            return
        if not self._flush_adjustments():
            return
        try:
            self._push_history()
            template = self._cur_entry or (self._entries[0] if self._entries else None)
            new_entry = add_texture_from_file(self._xfbin, path, template)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_texture_add_error"), str(exc))
            return
        self._reload_entries(new_entry)
        self._mark_dirty()
        self._status(f"Added  {new_entry.name}  <-  {os.path.basename(path)}")

    def _duplicate_texture(self):
        if self._xfbin is None or self._cur_entry is None:
            return
        if not self._flush_adjustments():
            return
        old_name = self._cur_entry.name
        try:
            self._push_history()
            new_entry = duplicate_texture_entry(self._xfbin, self._cur_entry)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_texture_duplicate_error"), str(exc))
            return
        self._reload_entries(new_entry)
        self._mark_dirty()
        self._status(f"Duplicated  {old_name}  ->  {new_entry.name}")

    def _delete_texture(self):
        if self._xfbin is None or self._cur_entry is None:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(
                self,
                ui_text("dlg_title_warning"),
                ui_text("ui_texture_cannot_delete_last_texture"),
            )
            return

        entry = self._cur_entry
        old_idx = self._entries.index(entry) if entry in self._entries else 0
        result = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_texture_delete_texture_value", p0=entry.name),
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        if not self._flush_adjustments():
            return
        self._push_history()
        if not delete_texture_entry(self._xfbin, entry):
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_texture_delete_failed"))
            return

        self._entries = refresh_texture_entries(self._xfbin, decode_images=False)
        next_entry = self._entries[min(old_idx, len(self._entries) - 1)] if self._entries else None
        self._reload_entries(next_entry)
        self._mark_dirty()
        self._status(f"Deleted  {entry.name}")

    # Copy name
    def _copy_name(self):
        if self._cur_entry is None:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._cur_entry.name)
        self._status(f'Copied  \u201c{self._cur_entry.name}\u201d  to clipboard')

    def _rename(self, name: str, path: str):
        if self._cur_entry is None:
            return False
        if not name or '\0' in name or '\0' in path:
            QMessageBox.warning(self, ui_text('ui_texture_rename'), ui_text('texture_invalid_name'))
            return False
        if (name, path) == (self._cur_entry.name, self._cur_entry.file_path):
            return True
        if any(e is not self._cur_entry and (e.name, e.file_path) == (name, path) for e in self._entries):
            QMessageBox.warning(self, ui_text('ui_texture_rename'), ui_text('texture_name_conflict'))
            return False
        old_name = self._cur_entry.name
        self._push_history()
        self._cur_entry.name      = name
        self._cur_entry.file_path = path
        # Propagate to the underlying XFBIN chunk
        if self._cur_entry.chunk is not None:
            self._cur_entry.chunk.name     = name
            self._cur_entry.chunk.filePath = path
        self._grid._refresh_row(self._cur_entry)
        self._right.set_entry(self._cur_entry)
        self._mark_dirty()
        self._status(f'Renamed  \u201c{old_name}\u201d  \u2192  \u201c{name}\u201d')
        return True

    # Add Text Overlay
    def _add_text(self):
        if self._cur_entry is None or self._orig_pil is None:
            QMessageBox.information(self, ui_text("ui_texture_add_text_2"), ui_text("ui_texture_open_a_texture_first"))
            return
        if not self._flush_adjustments():
            return
        dlg = _TextOverlayDialog(self._orig_pil.copy(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        result = dlg.get_result()
        if result is None:
            return
        self._commit_edit(result)
        self._status(f"Text baked into  {self._cur_entry.name}")

    # Status bar
    def _status(self, msg: str, error: bool = False):
        self._status_lbl.setStyleSheet(ss_error_label() if error else ss_dim_label())
        self._status_lbl.setText(msg)


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
        self.setStyleSheet(ss_dialog())
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
        configure_layout(root, LayoutRole.ROOT)

        # Left: preview
        preview_wrap = QWidget()
        preview_wrap.setStyleSheet(ss_bg_dark())
        pl = QVBoxLayout(preview_wrap)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(Size.GAP_SM)

        pv_hdr = QHBoxLayout(); pv_hdr.setSpacing(Size.GAP)
        pv_lbl = QLabel(ui_text("ui_texture_preview"))
        pv_lbl.setFont(ui_font(TypeSize.BODY, QFont.Weight.Bold))
        pv_lbl.setStyleSheet(ss_accent_label())
        pv_hdr.addWidget(pv_lbl)
        drag_hint = QLabel(ui_text("ui_texture_drag_to_reposition_text"))
        drag_hint.setFont(ui_font(TypeSize.HINT))
        drag_hint.setStyleSheet(ss_dim_label())
        pv_hdr.addWidget(drag_hint)
        pv_hdr.addStretch()
        pl.addLayout(pv_hdr)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_scroll.setStyleSheet(ss_scrollarea_card())
        self._preview_lbl = _DraggablePreview()
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet(ss_transparent())
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
        ctrl_scroll.setStyleSheet(ss_scrollarea_panel_edge())
        ctrl = QWidget()
        ctrl.setStyleSheet(ss_bg_panel())
        cl = QVBoxLayout(ctrl)
        configure_layout(cl, LayoutRole.PAGE)

        # Text input
        cl.addWidget(self._sec(ui_text("ui_galleryartparam_text")))
        from PyQt6.QtWidgets import QPlainTextEdit
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText(ui_text("ui_texture_enter_text_ctrl_enter_new_line"))
        self._text_edit.setFixedHeight(80)
        configure_textedit(self._text_edit)
        self._text_edit.textChanged.connect(self._kick)
        cl.addWidget(self._text_edit)

        # Font
        cl.addWidget(self._sec(ui_text("ui_texture_font")))

        from PyQt6.QtWidgets import QFontComboBox
        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont("Arial"))
        configure_input(self._font_combo)
        self._font_combo.currentFontChanged.connect(self._kick)
        cl.addWidget(self._font_combo)

        # Size + Bold + Italic row
        srow = QHBoxLayout(); srow.setSpacing(6)
        from PyQt6.QtWidgets import QSpinBox
        size_lbl = QLabel(ui_text("ui_texture_size"))
        size_lbl.setFont(ui_font(TypeSize.BODY))
        size_lbl.setStyleSheet(ss_dim_label())
        srow.addWidget(size_lbl)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 512)
        self._size_spin.setValue(36)
        self._size_spin.setFixedWidth(64)
        configure_input(self._size_spin, monospace=True)
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

        for lbl, attr, lo, hi, default in (
            ("X",  '_shadow_x', -30, 30, 3),
            ("Y",  '_shadow_y', -30, 30, 3),
        ):
            sl = _SliderRow(lbl, lo, hi, default)
            sl.value_changed.connect(self._kick)
            setattr(self, attr + '_slider', sl)
            cl.addWidget(sl)

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
        anchor_lbl = QLabel(ui_text("ui_texture_anchor"))
        anchor_lbl.setStyleSheet(ss_field_label())
        cl.addWidget(anchor_lbl)
        ag_widget = QWidget()
        ag_widget.setStyleSheet(ss_transparent())
        ag_layout = QGridLayout(ag_widget)
        ag_layout.setContentsMargins(*Insets.NONE)
        ag_layout.setSpacing(3)
        self._anchor_group = QButtonGroup(self)
        self._anchor_btns: dict[str, QPushButton] = {}
        for i, (label, anc) in enumerate(self._ANCHOR_OPTS):
            btn = QPushButton(label.split()[0])
            btn.setCheckable(True)
            btn.setFixedSize(46, 28)
            configure_button(btn, toggle=True)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, a=anc: self._on_anchor(a))
            self._anchor_group.addButton(btn)
            self._anchor_btns[anc] = btn
            ag_layout.addWidget(btn, i // 3, i % 3)
        self._anchor_btns['mm'].setChecked(True)
        self._current_anchor = 'mm'
        cl.addWidget(ag_widget)

        # Alignment row
        align_row = QHBoxLayout(); align_row.setSpacing(Size.GAP_SM)
        self._align_group = QButtonGroup(self)
        for symbol, val in ((ui_text("ui_texture_l"), 'left'), (ui_text("ui_texture_c"), 'center'), (ui_text("ui_texture_r"), 'right')):
            btn = QPushButton(symbol)
            btn.setCheckable(True)
            btn.setFixedSize(42, 26)
            configure_button(btn, toggle=True)
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

        btn_row = QHBoxLayout(); btn_row.setSpacing(Size.GAP)
        ok_btn = QPushButton(ui_text("ui_texture_apply_to_texture"))
        configure_button(ok_btn, accent=True, height=Size.CONTROL)
        ok_btn.clicked.connect(self._accept)
        btn_row.addWidget(ok_btn, 1)

        cancel_btn = QPushButton(ui_text("ui_texture_cancel"))
        configure_button(cancel_btn, height=Size.CONTROL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        cl.addLayout(btn_row)

        ctrl_scroll.setWidget(ctrl)
        root.addWidget(ctrl_scroll)

    # Small helpers
    @staticmethod
    def _sec(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(ui_font(TypeSize.BODY, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_accent_label())
        return lbl

    @staticmethod
    def _toggle_btn(label: str, weight, italic: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFixedSize(30, 28)
        f = ui_font(TypeSize.CODE, weight)
        f.setItalic(italic)
        configure_button(btn, toggle=True)
        return btn

    def _color_picker_btn(self, label: str, default: tuple, callback) -> tuple:
        """Returns (QWidget, setter_fn) where the widget shows a color swatch + label."""
        w   = QWidget(); w.setStyleSheet(ss_transparent())
        row = QHBoxLayout(w)
        row.setContentsMargins(*Insets.NONE); row.setSpacing(6)

        lbl = QLabel(label + ":")
        lbl.setFont(ui_font(TypeSize.BODY))
        lbl.setStyleSheet(ss_dim_label())
        row.addWidget(lbl)

        swatch = QPushButton()
        swatch.setFixedSize(56, 22)
        swatch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        swatch.setStyleSheet(_swatch_style(default))
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
            self._color_btn[0]._swatch.setStyleSheet(_swatch_style(self._color))
            self._kick()

    def _pick_outline_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(*self._outline_color), self, ui_text("ui_texture_outline_color"))
        if c.isValid():
            self._outline_color = (c.red(), c.green(), c.blue())
            self._outline_btn[0]._swatch.setStyleSheet(_swatch_style(self._outline_color))
            self._kick()

    def _pick_shadow_color(self):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(*self._shadow_color), self, ui_text("ui_texture_shadow_color"))
        if c.isValid():
            self._shadow_color = (c.red(), c.green(), c.blue())
            self._shadow_btn[0]._swatch.setStyleSheet(_swatch_style(self._shadow_color))
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
