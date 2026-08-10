import os

from PIL import Image
from PyQt6.QtCore import QRegularExpression, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    add_editor_card_title,
    make_empty_state,
    make_editor_field_shell,
    ss_accent_sep,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_check,
    ss_dim_label,
    ss_field_label,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_search,
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_textedit,
    ss_transparent,
    ss_viewport_panel,
    ss_editor_card,
)
from core.translations import ui_text
from parsers.font_xfbin_parser import (
    ICONFONT_RECORD_SIZE,
    NFH_GLYPH_RECORD_SIZE,
    FontDocument,
    atlas_png_bytes,
    crop_nfh_glyph_image,
    load_font_xfbin,
    replace_nfh_glyph_image,
    replace_nfh_atlas_same_size,
    resolve_icon_string,
    save_font_xfbin,
    set_icon_record_field,
    set_icon_record_hex,
    set_nfh_metadata,
    set_nfh_record_hex,
)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class FontEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._doc: FontDocument | None = None
        self._current_idx: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QLineEdit | QTextEdit] = {}
        self._section_labels: list[QLabel] = []
        self._dirty = False
        self._loading_detail = False
        self._glyph_font_combo: QFontComboBox | None = None
        self._glyph_replacement_edit: QLineEdit | None = None
        self._glyph_size_spin: QSpinBox | None = None
        self._glyph_bold_check: QCheckBox | None = None
        self._glyph_italic_check: QCheckBox | None = None
        self._last_compact = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._rebuild_for_width)

        self._uint32_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)

        self._build_ui()

    def _tr(self, key: str, **kwargs) -> str:
        return self._t(key, **kwargs) if kwargs else self._t(key)

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

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._do_open)
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn())
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(ui_text("no_file_loaded"))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(ss_sidebar_frame())
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 4)
        sidebar_layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_font_search_placeholder"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar_layout.addWidget(self._entry_scroll, 1)
        main_layout.addWidget(sidebar)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(14, 14, 14, 14)
        self._editor_layout.setSpacing(14)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)
        self._show_placeholder(ui_text("ui_font_open_file_to_begin"))

    def _editor_width(self) -> int:
        return max(0, self._editor_scroll.viewport().width() if hasattr(self, "_editor_scroll") else self.width())

    def _is_compact_editor(self) -> bool:
        return self._editor_width() < 760

    def _rebuild_for_width(self):
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        if self._doc is None:
            return
        if self._current_idx is not None:
            self._apply_current_record(show_errors=False)
            self._build_editor(self._current_idx)
        else:
            self._build_overview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._doc is not None:
            self._resize_timer.start()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_font_open_title"),
            game_files_dialog_dir(target_patterns=("*.fnt.xfbin", "xfgame_cmn_*.xfbin", "iconfontParam.bin.xfbin")),
            ui_text("ui_font_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        set_file_label_empty(self._file_label, ui_text("loading"))
        try:
            doc = load_font_xfbin(path)
        except Exception as exc:
            self._doc = None
            self._current_idx = None
            self._dirty = False
            self._clear_entry_list()
            set_file_label_empty(self._file_label, ui_text("no_file_loaded"))
            self._show_placeholder(ui_text("ui_font_open_file_to_begin"))
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._doc = doc
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entry_count():
            self._select_entry(0)
        else:
            self._build_overview()

    def _do_save(self):
        if self._doc is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        try:
            save_font_xfbin(self._doc, self._doc.path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, self._doc.path)
            QMessageBox.information(
                self,
                ui_text("dlg_title_success"),
                ui_text("msg_save_success", path=os.path.basename(self._doc.path)),
            )
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    _save_file = _do_save

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []
        self._section_labels = []

    def _entry_count(self) -> int:
        if self._doc is None:
            return 0
        if self._doc.kind == "nfh_font":
            return len(self._doc.glyph_records)
        return len(self._doc.icon_records)

    def _populate_list(self):
        self._clear_entry_list()
        if self._doc is None:
            return
        last_section = None
        for idx in range(self._entry_count()):
            section = self._entry_section(idx)
            if section and section != last_section:
                label = self._make_section_label(section)
                self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, label)
                self._section_labels.append(label)
                last_section = section
            btn = self._make_entry_button(idx)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _entry_section(self, idx: int) -> str | None:
        if self._doc is None or self._doc.kind != "nfh_font":
            return None
        record = self._doc.glyph_records[idx]
        if not record.has_atlas_rect:
            return ui_text("ui_font_atlas_section_no_bitmap")
        return ui_text("ui_font_atlas_section_title", y=record.atlas_y)

    def _make_section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        label.setStyleSheet(ss_dim_label())
        label.setContentsMargins(8, 8, 8, 2)
        return label

    def _make_entry_button(self, idx: int) -> QPushButton:
        btn = QPushButton()
        is_glyph = bool(self._doc and self._doc.kind == "nfh_font")
        btn.setFixedHeight(34 if is_glyph else 48)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(0)

        title = QLabel(self._entry_title(idx))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title)

        if not is_glyph:
            subtitle = QLabel(self._entry_subtitle(idx))
            subtitle.setFont(QFont("Consolas", 10))
            subtitle.setStyleSheet(ss_dim_label())
            subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int) -> str:
        if self._doc is None:
            return ""
        if self._doc.kind == "nfh_font":
            rec = self._doc.glyph_records[idx]
            if rec.glyph_char == " ":
                return ui_text("ui_font_glyph_space_title")
            if rec.glyph_char:
                return ui_text("ui_font_glyph_title", char=rec.glyph_char)
            return ui_text("ui_font_glyph_nonprinting_title")
        rec = self._doc.icon_records[idx]
        name = resolve_icon_string(self._doc, rec.fields[6])
        return ui_text("ui_font_icon_title", index=idx, name=name or ui_text("ui_font_unresolved"))

    def _entry_subtitle(self, idx: int) -> str:
        if self._doc is None:
            return ""
        if self._doc.kind == "nfh_font":
            words = self._doc.glyph_records[idx].words
            return ui_text("ui_font_glyph_subtitle", p0=f"{words[0]:08X}", p1=f"{words[1]:08X}")
        fields = self._doc.icon_records[idx].fields
        return ui_text("ui_font_icon_subtitle", p0=fields[0], p1=fields[1], p2=f"0x{fields[6]:X}")

    def _filter_list(self):
        query = self._search.text().lower().strip()
        for btn, idx in self._entry_buttons:
            haystack = f"{idx} {self._entry_title(idx)} {self._entry_subtitle(idx)}".lower()
            if self._doc and self._doc.kind == "iconfont_param":
                record = self._doc.icon_records[idx]
                haystack += " " + " ".join(resolve_icon_string(self._doc, value).lower() for value in record.fields)
            btn.setVisible(not query or query in haystack)

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= self._entry_count():
            return
        if not self._apply_current_record(show_errors=True):
            return
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 1:
                labels[0].setText(self._entry_title(idx))
            if len(labels) >= 2:
                labels[1].setText(self._entry_subtitle(idx))
            break
        self._filter_list()

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._loading_detail = True
        if self._doc and self._doc.kind == "nfh_font":
            self._build_glyph_image_card(idx)
            self._build_atlas_card()
        elif self._doc:
            self._build_icon_record_card(idx)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _build_overview(self):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._loading_detail = True
        if self._doc and self._doc.kind == "nfh_font":
            self._build_atlas_card()
        elif self._doc:
            self._show_placeholder(ui_text("ui_font_select_entry_to_begin"))
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _build_atlas_card(self):
        if self._doc is None or self._doc.atlas is None:
            return
        self._add_section(ui_text("ui_font_atlas_preview_title"))
        card = self._make_card()
        layout = self._card_vbox(card)

        preview_frame, preview = self._make_preview_surface(230)
        if self._doc.atlas.pil_image is not None:
            preview.setPixmap(self._pil_to_preview(self._doc.atlas.pil_image, 720, 210))
        else:
            preview.setText(ui_text("ui_font_atlas_preview_unavailable"))
        layout.addWidget(preview_frame)

        actions = QWidget()
        actions.setStyleSheet(ss_transparent())
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 2, 0, 0)
        action_layout.setSpacing(8)

        export_png = self._small_button(ui_text("ui_font_export_png"), self._export_atlas_png, accent=True)
        export_nut = self._small_button(ui_text("ui_font_export_ntp3"), self._export_atlas_ntp3)
        replace_btn = self._small_button(ui_text("ui_font_replace_same_size"), self._replace_atlas)
        action_layout.addWidget(export_png)
        action_layout.addWidget(export_nut)
        action_layout.addWidget(replace_btn)
        action_layout.addStretch()
        layout.addWidget(actions)
        self._editor_layout.addWidget(card)

    def _build_glyph_image_card(self, idx: int):
        assert self._doc is not None
        record = self._doc.glyph_records[idx]
        compact = self._is_compact_editor()
        self._last_compact = compact
        self._add_section(ui_text("ui_font_glyph_preview_title"))
        card = self._make_card()
        layout = self._card_vbox(card)

        body = QWidget()
        body.setStyleSheet(ss_transparent())
        body_layout = QVBoxLayout(body) if compact else QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12 if compact else 22)

        left = QWidget()
        left.setStyleSheet(ss_transparent())
        left.setMinimumWidth(0)
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        preview_frame, preview = self._make_preview_surface(190 if compact else 220)
        crop = crop_nfh_glyph_image(self._doc, idx)
        if crop is not None:
            preview.setPixmap(self._pil_to_preview(crop, 300, 130, upscale=True, max_scale=4))
        else:
            preview.setText(ui_text("ui_font_glyph_preview_unavailable"))
        left_layout.addWidget(preview_frame, 1)

        actions = QWidget()
        actions.setStyleSheet(ss_transparent())
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        export_btn = self._small_button(ui_text("ui_font_export_glyph_png"), self._export_glyph_png, accent=True)
        replace_btn = self._small_button(ui_text("ui_font_replace_glyph_png"), self._replace_glyph_png)
        action_layout.addWidget(export_btn)
        action_layout.addWidget(replace_btn)
        action_layout.addStretch()
        left_layout.addWidget(actions)

        controls = QWidget()
        controls.setStyleSheet(ss_transparent())
        controls.setMinimumWidth(0)
        if compact:
            controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        else:
            controls.setFixedWidth(240)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10 if compact else 14)

        size_frame, size_layout = self._field_shell(ui_text("ui_font_font_size"))
        self._glyph_size_spin = QSpinBox()
        self._glyph_size_spin.setRange(1, 256)
        self._glyph_size_spin.setValue(max(8, record.atlas_height or 32))
        self._glyph_size_spin.setFixedHeight(34)
        self._glyph_size_spin.setMinimumWidth(0)
        self._glyph_size_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glyph_size_spin.setFont(QFont("Consolas", 11))
        self._glyph_size_spin.setStyleSheet(ss_input())
        size_layout.addWidget(self._glyph_size_spin)
        controls_layout.addWidget(size_frame)

        font_frame, font_layout = self._field_shell(ui_text("ui_font_windows_font"))
        self._glyph_font_combo = QFontComboBox()
        self._glyph_font_combo.setFixedHeight(34)
        self._glyph_font_combo.setMinimumWidth(0)
        self._glyph_font_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glyph_font_combo.setFont(QFont("Segoe UI", 10))
        self._glyph_font_combo.setStyleSheet(ss_input())
        font_layout.addWidget(self._glyph_font_combo)
        controls_layout.addWidget(font_frame)

        text_frame, text_layout = self._field_shell(ui_text("ui_font_replacement_text"))
        self._glyph_replacement_edit = QLineEdit()
        self._glyph_replacement_edit.setFixedHeight(34)
        self._glyph_replacement_edit.setMinimumWidth(0)
        self._glyph_replacement_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glyph_replacement_edit.setFont(QFont("Segoe UI", 12))
        self._glyph_replacement_edit.setStyleSheet(ss_input())
        self._glyph_replacement_edit.setPlaceholderText(ui_text("ui_font_replacement_placeholder"))
        self._glyph_replacement_edit.setText(record.glyph_char)
        text_layout.addWidget(self._glyph_replacement_edit)
        controls_layout.addWidget(text_frame)

        check_row = QWidget()
        check_row.setStyleSheet(ss_transparent())
        check_layout = QHBoxLayout(check_row)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.setSpacing(18)

        self._glyph_bold_check = QCheckBox(ui_text("ui_font_bold"))
        self._glyph_bold_check.setFont(QFont("Segoe UI", 10))
        self._glyph_bold_check.setStyleSheet(ss_check())
        check_layout.addWidget(self._glyph_bold_check)

        self._glyph_italic_check = QCheckBox(ui_text("ui_font_italic"))
        self._glyph_italic_check.setFont(QFont("Segoe UI", 10))
        self._glyph_italic_check.setStyleSheet(ss_check())
        check_layout.addWidget(self._glyph_italic_check)
        check_layout.addStretch()
        controls_layout.addWidget(check_row)

        apply_btn = self._small_button(ui_text("ui_font_apply_windows_font"), self._apply_windows_font_to_glyph)
        apply_btn.setFixedHeight(38)
        apply_btn.setMinimumWidth(0)
        apply_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(apply_btn)
        controls_layout.addStretch()

        body_layout.addWidget(left, 1)
        body_layout.addWidget(controls)
        layout.addWidget(body)
        self._editor_layout.addWidget(card)

    def _build_icon_record_card(self, idx: int):
        assert self._doc is not None
        record = self._doc.icon_records[idx]
        fields = record.fields
        self._add_section(ui_text("ui_font_selected_icon"))
        card = self._make_card()
        grid = self._card_grid(card)
        self._add_info(grid, 0, 0, ui_text("ui_font_record_index"), str(record.index))
        self._add_info(grid, 0, 1, ui_text("ui_font_record_offset"), f"0x{record.offset:X}")
        self._add_info(grid, 0, 2, ui_text("ui_font_resolved_name"), resolve_icon_string(self._doc, fields[6]) or ui_text("ui_font_unresolved"))

        for field_idx, value in enumerate(fields):
            self._add_uint_field(
                grid,
                1 + field_idx // 3,
                field_idx % 3,
                f"field_{field_idx}",
                ui_text("ui_font_raw_field", index=field_idx),
                value,
            )
        row = 1 + ((len(fields) + 2) // 3)
        self._add_info(grid, row, 0, ui_text("ui_font_offset_string_6"), resolve_icon_string(self._doc, fields[6]) or ui_text("ui_font_unresolved"))
        self._add_info(grid, row, 1, ui_text("ui_font_offset_string_9"), resolve_icon_string(self._doc, fields[9]) or ui_text("ui_font_unresolved"))
        self._add_info(grid, row, 2, ui_text("ui_font_offset_string_10"), resolve_icon_string(self._doc, fields[10]) or ui_text("ui_font_unresolved"))
        self._add_hex_field(grid, row + 1, 0, "record_hex", ui_text("ui_font_raw_record_hex"), record.hex_text, colspan=3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        self._editor_layout.addWidget(card)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("EditorCard")
        card.setStyleSheet(ss_editor_card())
        card.setMinimumWidth(0)
        card.setMaximumWidth(1120)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        if section_title:
            add_editor_card_title(layout, section_title, "fa6s.font")
        layout.addWidget(inner)
        return grid

    def _card_vbox(self, card: QFrame) -> QVBoxLayout:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        if section_title:
            add_editor_card_title(layout, section_title, "fa6s.font")
        return layout

    def _field_shell(self, label: str) -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label)
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return frame, layout

    def _add_info(self, grid, row: int, col: int, label: str, value: str, colspan: int = 1):
        frame, layout = self._field_shell(label)
        value_widget = QLabel(value)
        value_widget.setMinimumWidth(0)
        value_widget.setWordWrap(True)
        value_widget.setFont(QFont("Consolas", 11))
        value_widget.setStyleSheet(ss_main_label())
        layout.addWidget(value_widget)
        grid.addWidget(frame, row, col, 1, colspan)

    def _add_text_field(self, grid, row: int, col: int, key: str, label: str, value: str):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setFixedHeight(30)
        edit.setMinimumWidth(0)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.setText(value)
        edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row: int, col: int, key: str, label: str, value: int):
        frame, layout = self._field_shell(label)
        edit = QLineEdit()
        edit.setValidator(self._uint32_validator)
        edit.setMaxLength(10)
        edit.setFixedHeight(30)
        edit.setMinimumWidth(0)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.setText(str(int(value)))
        edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(edit)
        grid.addWidget(frame, row, col)
        self._fields[key] = edit

    def _add_hex_field(self, grid, row: int, col: int, key: str, label: str, value: str, colspan: int):
        frame, layout = self._field_shell(label)
        edit = QTextEdit()
        edit.setAcceptRichText(False)
        edit.setFixedHeight(74)
        edit.setMinimumWidth(0)
        edit.setFont(QFont("Consolas", 11))
        edit.setStyleSheet(ss_textedit())
        edit.setText(value)
        edit.textChanged.connect(self._on_field_changed)
        layout.addWidget(edit)
        grid.addWidget(frame, row, col, 1, colspan)
        self._fields[key] = edit

    def _small_button(self, text: str, slot, accent: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(36)
        btn.setMinimumWidth(0)
        btn.setFont(QFont("Segoe UI", 10))
        btn.setStyleSheet(ss_btn(accent=accent))
        btn.clicked.connect(slot)
        return btn

    def _make_preview_surface(self, min_height: int) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setMinimumHeight(min_height)
        frame.setStyleSheet(ss_viewport_panel())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(ss_placeholder())
        layout.addWidget(label, 1)
        return frame, label

    def _on_field_changed(self):
        if not self._loading_detail:
            self._mark_dirty()

    def _apply_current_record(self, show_errors: bool = False) -> bool:
        if self._doc is None:
            return True
        try:
            if self._doc.kind == "nfh_font":
                family_widget = self._fields.get("family")
                style_widget = self._fields.get("style")
                if isinstance(family_widget, QLineEdit) and isinstance(style_widget, QLineEdit):
                    set_nfh_metadata(self._doc, family_widget.text().strip(), style_widget.text().strip())
                if self._current_idx is not None and "record_hex" in self._fields:
                    set_nfh_record_hex(self._doc, self._current_idx, self._hex_text("record_hex"))
            elif self._current_idx is not None:
                record = self._doc.icon_records[self._current_idx]
                raw_hex = self._hex_text("record_hex") if "record_hex" in self._fields else ""
                raw_changed = bool(raw_hex) and self._normal_hex(raw_hex) != self._normal_hex(record.hex_text)
                for field_idx in range(11):
                    widget = self._fields.get(f"field_{field_idx}")
                    if isinstance(widget, QLineEdit):
                        text = widget.text().strip() or "0"
                        value = int(text)
                        set_icon_record_field(self._doc, self._current_idx, field_idx, value)
                if raw_changed:
                    set_icon_record_hex(self._doc, self._current_idx, raw_hex)
            if self._current_idx is not None:
                self._refresh_entry_button(self._current_idx)
            return True
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_apply_error", error=exc))
            return False

    def _hex_text(self, key: str) -> str:
        widget = self._fields.get(key)
        if isinstance(widget, QTextEdit):
            return widget.toPlainText()
        return ""

    def _normal_hex(self, text: str) -> str:
        return "".join(ch for ch in text.strip().upper() if not ch.isspace())

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._doc is not None:
                set_file_label(self._file_label, self._doc.path, dirty=True)
        self._btn_save.setEnabled(self._dirty and self._doc is not None)

    def _export_atlas_png(self):
        if self._doc is None or self._doc.atlas is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_png"),
            os.path.splitext(self._doc.path)[0] + ".png",
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(atlas_png_bytes(self._doc))
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _export_atlas_ntp3(self):
        if self._doc is None or self._doc.atlas is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_ntp3"),
            os.path.splitext(self._doc.path)[0] + ".nut",
            ui_text("ui_font_ntp3_filter"),
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self._doc.atlas.data)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _replace_atlas(self):
        if self._doc is None or self._doc.atlas is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_font_replace_same_size"),
            game_files_dialog_dir(os.path.dirname(self._doc.path)),
            ui_text("ui_font_ntp3_filter"),
        )
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            replace_nfh_atlas_same_size(self._doc, data)
            self._mark_dirty()
            idx = self._current_idx
            if idx is not None:
                self._build_editor(idx)
            else:
                self._build_overview()
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replace_error", error=exc))

    def _export_glyph_png(self):
        if self._doc is None or self._current_idx is None:
            return
        crop = crop_nfh_glyph_image(self._doc, self._current_idx)
        if crop is None:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_glyph_png"),
            os.path.splitext(self._doc.path)[0] + f"_glyph_{self._current_idx}.png",
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            crop.save(path, "PNG")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _replace_glyph_png(self):
        if self._doc is None or self._current_idx is None:
            return
        record = self._doc.glyph_records[self._current_idx]
        if not record.has_atlas_rect:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_font_replace_glyph_png"),
            game_files_dialog_dir(os.path.dirname(self._doc.path)),
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            image = Image.open(path).convert("RGBA")
            replace_nfh_glyph_image(self._doc, self._current_idx, image)
            self._mark_dirty()
            self._build_editor(self._current_idx)
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replace_glyph_error", error=exc))

    def _apply_windows_font_to_glyph(self):
        if self._doc is None or self._current_idx is None:
            return
        record = self._doc.glyph_records[self._current_idx]
        if not record.has_atlas_rect:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        text = self._glyph_replacement_edit.text().strip() if self._glyph_replacement_edit is not None else ""
        if not text:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replacement_empty"))
            return
        try:
            image = self._render_windows_font_glyph(text, record.atlas_width, record.atlas_height)
            replace_nfh_glyph_image(self._doc, self._current_idx, image)
            self._mark_dirty()
            self._build_editor(self._current_idx)
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_render_error", error=exc))

    def _render_windows_font_glyph(self, char: str, width: int, height: int) -> Image.Image:
        if self._glyph_font_combo is None or self._glyph_size_spin is None:
            raise ValueError(ui_text("ui_font_controls_not_ready"))
        qimage = QImage(width, height, QImage.Format.Format_RGBA8888)
        qimage.fill(Qt.GlobalColor.transparent)

        font = QFont(self._glyph_font_combo.currentFont())
        font.setPixelSize(self._glyph_size_spin.value())
        if self._glyph_bold_check is not None:
            font.setBold(self._glyph_bold_check.isChecked())
        if self._glyph_italic_check is not None:
            font.setItalic(self._glyph_italic_check.isChecked())

        painter = QPainter(qimage)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, char)
        painter.end()
        return self._qimage_to_pil(qimage)

    def _qimage_to_pil(self, image: QImage) -> Image.Image:
        qimage = image.convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = qimage.bits()
        ptr.setsize(qimage.bytesPerLine() * qimage.height())
        return Image.frombytes(
            "RGBA",
            (qimage.width(), qimage.height()),
            bytes(ptr),
            "raw",
            "RGBA",
            qimage.bytesPerLine(),
        )

    def _pil_to_preview(self, image, max_width=560, max_height=220, upscale: bool = False, max_scale: int = 8) -> QPixmap:
        img = image.copy()
        if upscale and img.width > 0 and img.height > 0:
            scale = max(1, min(max_width // img.width, max_height // img.height, max_scale))
            if scale > 1:
                img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
        img.thumbnail((max_width, max_height))
        data = img.convert("RGBA").tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
