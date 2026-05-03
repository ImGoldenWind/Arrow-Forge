import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFileDialog, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_search, ss_file_label, ss_sidebar_btn,
    ss_scrollarea, ss_scrollarea_transparent, ss_panel, ss_section_label,
    ss_field_label, ss_dim_label, ss_placeholder, TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.galleryartparam_parser import (
    parse_galleryartparam_xfbin,
    save_galleryartparam_xfbin,
    make_default_entry,
    UNLOCK_LABELS,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


_PART_NAMES = {
    0: ui_text("ui_galleryartparam_no_part_special"),
    1: ui_text("ui_galleryartparam_phantom_blood"),
    2: ui_text("ui_galleryartparam_battle_tendency"),
    3: ui_text("ui_galleryartparam_stardust_crusaders"),
    4: ui_text("ui_galleryartparam_diamond_is_unbreakable"),
    5: ui_text("ui_galleryartparam_golden_wind"),
    6: ui_text("ui_galleryartparam_stone_ocean"),
    7: ui_text("ui_galleryartparam_steel_ball_run"),
    8: ui_text("ui_galleryartparam_jojolion"),
}


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class GalleryArtParamEditor(QWidget):
    """Embedded editor for GalleryArtParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._filter_text = ""
        self._current_index: int | None = None
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._fields: dict[str, QLineEdit] = {}
        self._loading_detail = False

        self._build_ui()

    def _tr(self, key, fallback):
        value = self._t(key)
        return fallback if value == key else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._do_open)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._do_save)
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))
        self._lbl_file.setFont(QFont("Consolas", 12))
        self._lbl_file.setStyleSheet(ss_file_label())
        tl.addWidget(self._lbl_file)
        tl.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        main = QWidget()
        main_l = QHBoxLayout(main)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 8, 8, 4)
        sl.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._on_filter_changed)
        sl.addWidget(self._search)

        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)
        btn_font = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(btn_font)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._do_add)
        al.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(btn_font)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._do_dup)
        al.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(btn_font)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._do_del)
        al.addWidget(self._btn_del, 1)

        sl.addWidget(actions)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sl.addWidget(self._list_scroll, 1)
        main_l.addWidget(sidebar)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_l.addWidget(divider)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_galleryartparam_open_a_galleryartparam_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(ss_placeholder())
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    def _clear_entry_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()

    def _visible_indices(self):
        text = self._filter_text.lower().strip()
        result = []
        for i, e in enumerate(self._entries):
            haystack = " ".join((
                e.get("art_id", ""),
                e.get("art_name", ""),
                e.get("chara_code", ""),
                e.get("art_string1", ""),
                e.get("art_string2", ""),
                e.get("icon_name", ""),
                str(e.get("part", "")),
                str(e.get("dlc_id", "")),
            )).lower()
            if not text or text in haystack:
                result.append(i)
        return result

    def _populate_list(self, preserve_selection: int | None = None):
        self._clear_entry_list()
        self._entry_buttons = []
        visible = self._visible_indices()

        for i in visible:
            btn = self._make_entry_button(i)
            self._list_layout.insertWidget(self._list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, i))

        if preserve_selection is not None and preserve_selection in visible:
            self._select_entry(preserve_selection)
        elif self._current_index in visible:
            self._select_entry(self._current_index)
        elif visible:
            self._select_entry(visible[0])
        else:
            self._current_index = None
            self._set_detail_buttons(False)
            self._show_placeholder(ui_text("ui_galleryartparam_select_a_gallery_entry_to_edit"))

    def _make_entry_button(self, idx):
        e = self._entries[idx]
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_index)))

        bl = QVBoxLayout(btn)
        bl.setContentsMargins(10, 3, 10, 3)
        bl.setSpacing(0)

        title = QLabel(ui_text("ui_customcardparam_entry_value_2", p0=idx))
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(title)

        subtitle = QLabel(ui_text("ui_customcardparam_value_value", p0=e.get('art_id', ''), p1=e.get('chara_code', '')))
        subtitle.setFont(QFont("Consolas", 11))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bl.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _set_detail_buttons(self, has_selection):
        self._btn_dup.setEnabled(has_selection)
        self._btn_del.setEnabled(has_selection)

    def _select_entry(self, idx):
        if idx < 0 or idx >= len(self._entries):
            return
        self._current_index = idx
        self._set_detail_buttons(True)
        for btn, i in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(i == idx)))
        self._build_editor(idx)

    def _build_editor(self, idx):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        e = self._entries[idx]

        hdr = QFrame()
        hdr.setStyleSheet(ss_panel())
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(8)

        title = QLabel(ui_text("ui_customcardparam_entry_value", p0=idx))
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        hl.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self._add_field(grid, 0, 0, "art_id", ui_text("ui_galleryartparam_art_id"), e.get("art_id", ""), wide=True)
        self._add_field(grid, 0, 1, "chara_code", ui_text("ui_galleryartparam_chara_code"), e.get("chara_code", ""))
        self._add_field(grid, 0, 2, "index", ui_text("ui_dictionaryparam_index"), e.get("index", 0))
        hl.addLayout(grid)
        self._editor_layout.addWidget(hdr)

        self._add_section(ui_text("ui_galleryartparam_text"))
        self._add_card_grid([
            ("art_string1", ui_text("ui_galleryartparam_art_string_1"), e.get("art_string1", "")),
            ("art_string2", ui_text("ui_galleryartparam_art_string_2"), e.get("art_string2", "")),
        ], columns=2)

        self._add_section(ui_text("ui_galleryartparam_asset_paths"))
        self._add_card_grid([
            ("icon_path", ui_text("ui_galleryartparam_icon_path"), e.get("icon_path", "")),
            ("icon_name", ui_text("ui_galleryartparam_icon_name"), e.get("icon_name", "")),
            ("art_path", ui_text("ui_galleryartparam_art_path"), e.get("art_path", "")),
            ("art_name", ui_text("ui_galleryartparam_art_name"), e.get("art_name", "")),
        ], columns=2)

        self._add_section(ui_text("ui_galleryartparam_game_logic"))
        self._add_card_grid([
            ("part", self._label_with_hint(ui_text("ui_customcardparam_part"), _PART_NAMES, e.get("part", 0)), e.get("part", 0)),
            ("unlock_cond", self._label_with_hint(ui_text("ui_galleryartparam_unlock_cond"), UNLOCK_LABELS, e.get("unlock_cond", 6)), e.get("unlock_cond", 6)),
            ("menu_index", ui_text("ui_galleryartparam_menu_index"), e.get("menu_index", 1)),
            ("price", ui_text("ui_customcardparam_price"), e.get("price", 0)),
            ("dlc_id", ui_text("ui_charviewer_dlc_id"), e.get("dlc_id", 0)),
            ("patch", ui_text("ui_customcardparam_patch"), e.get("patch", 0)),
        ], columns=3)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def _label_with_hint(self, label, names, value):
        hint = names.get(value)
        return f"{label} ({hint})" if hint else label

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    def _add_card_grid(self, fields, columns=3):
        card = QFrame()
        card.setStyleSheet(ss_panel())
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        for i, (key, label, value) in enumerate(fields):
            row, col = divmod(i, columns)
            self._add_field(grid, row, col, key, label, value)

        main = QVBoxLayout(card)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(inner)
        self._editor_layout.addWidget(card)

    def _add_field(self, grid, row, col, key, label, value, wide=False):
        f = QWidget()
        f.setStyleSheet("background: transparent;")
        fl = QVBoxLayout(f)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        fl.addWidget(lbl)

        le = QLineEdit()
        le.setText(str(value))
        le.setFixedHeight(30 if not wide else 36)
        le.setFont(QFont("Consolas", 13 if not wide else 16))
        le.setStyleSheet(ss_input())
        le.textChanged.connect(lambda text, k=key: self._on_field_changed(k, text))
        fl.addWidget(le)

        grid.addWidget(f, row, col)
        grid.setColumnStretch(col, 1)
        self._fields[key] = le

    def _on_field_changed(self, key, text):
        if self._loading_detail or self._current_index is None:
            return
        e = self._entries[self._current_index]
        try:
            if key in {"part", "dlc_id", "patch", "unlock_cond", "menu_index", "price", "index"}:
                e[key] = int(text.strip() or "0")
            else:
                e[key] = text.strip()
        except ValueError:
            return

        self._mark_dirty()
        if key in {"art_id", "chara_code"}:
            self._refresh_current_button()

    def _refresh_current_button(self):
        if self._current_index is None:
            return
        e = self._entries[self._current_index]
        for btn, i in self._entry_buttons:
            if i == self._current_index:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(ui_text("ui_customcardparam_entry_value_2", p0=i))
                    labels[1].setText(ui_text("ui_customcardparam_value_value", p0=e.get('art_id', ''), p1=e.get('chara_code', '')))
                break

    def _on_filter_changed(self):
        self._filter_text = self._search.text()
        self._populate_list(preserve_selection=self._current_index)

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(self._filepath is not None)
        set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_galleryartparam_open_galleryartparam"),
            game_files_dialog_dir(os.path.expanduser("~"), ("GalleryArtParam.xfbin", "GalleryArtParam.bin.xfbin")),
            "XFBIN files (*.xfbin);;All files (*)",
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_galleryartparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_customizedefaultparam_failed_to_load_file_value", p0=exc))
            return

        self._filepath = path
        self._raw_data = raw
        self._version = version
        self._entries = entries
        self._dirty = False
        self._current_index = None
        self._btn_add.setEnabled(True)
        self._btn_save.setEnabled(False)
        set_file_label(self._lbl_file, path)
        self._search.setText("")
        self._filter_text = ""
        self._populate_list()

    def _do_save(self):
        if not self._filepath or self._raw_data is None:
            return
        try:
            save_galleryartparam_xfbin(self._filepath, self._raw_data, self._version, self._entries)
            with open(self._filepath, "rb") as fh:
                self._raw_data = bytearray(fh.read())
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._lbl_file, self._filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_customizedefaultparam_save_failed"), str(exc))

    def _do_add(self):
        if self._raw_data is None:
            return
        self._entries.append(make_default_entry(len(self._entries)))
        self._mark_dirty()
        self._populate_list(preserve_selection=len(self._entries) - 1)

    def _do_dup(self):
        if self._current_index is None:
            return
        new_e = copy.deepcopy(self._entries[self._current_index])
        self._entries.insert(self._current_index + 1, new_e)
        self._mark_dirty()
        self._populate_list(preserve_selection=self._current_index + 1)

    def _do_del(self):
        if self._current_index is None:
            return
        e = self._entries[self._current_index]
        reply = QMessageBox.question(
            self, ui_text("ui_customizedefaultparam_delete_entry"),
            ui_text("ui_dlcinfoparam_delete_entry_value_value_value", p0=self._current_index, p1=e.get('art_id', ''), p2=e.get('art_name', '')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        old_idx = self._current_index
        self._entries.pop(old_idx)
        self._mark_dirty()
        new_sel = min(old_idx, len(self._entries) - 1) if self._entries else None
        self._current_index = None
        self._populate_list(preserve_selection=new_sel)
