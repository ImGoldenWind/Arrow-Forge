"""Card-based editor for SoundTestParam.bin.xfbin.

Each entry defines one track or voice line in the in-game Sound Test menu.
"""

import copy
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
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
    QVBoxLayout,
    QWidget,
)

from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    make_empty_state,
    make_editor_grid_card,
    make_editor_field_shell,
    ss_bg_dark,
    ss_bg_panel,
    ss_accent_sep,
    ss_btn,
    ss_dim_label,
    ss_field_label,
    ss_file_label,
    ss_file_label_loaded,
    ss_input,
    ss_panel,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_sep,
    ss_search,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_main_label,
    ss_transparent,
)
from parsers.soundtestparam_parser import (
    make_default_entry,
    parse_soundtestparam_xfbin,
    save_soundtestparam_xfbin,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


_UNLOCK_LABELS = {
    1: ui_text("ui_soundtestparam_1_default"),
    4: ui_text("ui_soundtestparam_4_shop"),
    6: ui_text("ui_soundtestparam_6_character"),
}


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


class SoundTestParamEditor(QWidget):
    """Embedded Sound Test editor styled like CharacterStatsEditor."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QWidget] = {}
        self._dirty = False
        self._block_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3

        self._build_ui()

    def _tr(self, key: str, fallback: str, **kwargs) -> str:
        text = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if text == key else text

    # UI construction

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

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._do_open)
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("ui_btladjprm_no_file_loaded")))
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

        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(ss_sidebar_frame())
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(8, 8, 8, 4)
        list_layout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        list_layout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet(ss_transparent())
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._do_add)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._do_dup)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._do_del)
        actions_layout.addWidget(self._del_btn, 1)

        list_layout.addWidget(actions_frame)

        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())

        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        list_layout.addWidget(self._entry_scroll)

        main_layout.addWidget(list_frame)

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
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)
        self._show_placeholder(ui_text("ui_soundtestparam_open_a_soundtestparam_xfbin_file_to_begin_editing"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # File I/O

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_soundtestparam_open_soundtestparam"),
            game_files_dialog_dir(target_patterns=("SoundTestParam.xfbin", "SoundTestParam.bin.xfbin")),
            "XFBIN files (*.xfbin);;All files (*.*)",
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        self._file_label.setText(self._tr("loading", ui_text("loading")))
        try:
            raw, version, entries = parse_soundtestparam_xfbin(path)
        except Exception as exc:
            self._filepath = None
            self._raw_data = None
            self._entries = []
            self._current_idx = None
            self._file_label.setText(self._tr("no_file_loaded", ui_text("ui_btladjprm_no_file_loaded")))
            self._file_label.setStyleSheet(ss_file_label())
            self._clear_entry_list()
            self._show_placeholder(ui_text("ui_soundtestparam_open_a_soundtestparam_xfbin_file_to_begin_editing"))
            QMessageBox.critical(
                self,
                self._tr("dlg_title_error", ui_text("dlg_title_error")),
                self._tr("msg_load_error", ui_text("msg_load_error"), error=exc),
            )
            return

        self._filepath = path
        self._raw_data = raw
        self._version = version
        self._entries = entries
        self._current_idx = None
        self._dirty = False

        self._file_label.setText(os.path.basename(path))
        self._file_label.setStyleSheet(ss_file_label_loaded())
        self._btn_save.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(bool(entries))
        self._del_btn.setEnabled(bool(entries))
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_soundtestparam_no_entries"))

    def _do_save(self):
        if not self._filepath or self._raw_data is None:
            return
        self._apply_current_entry()
        try:
            save_soundtestparam_xfbin(
                self._filepath,
                self._raw_data,
                self._version,
                self._entries,
            )
            self._dirty = False
            self._file_label.setText(os.path.basename(self._filepath))
            self._file_label.setStyleSheet(ss_file_label_loaded())
        except Exception as exc:
            QMessageBox.critical(
                self,
                self._tr("dlg_title_error", ui_text("dlg_title_error")),
                self._tr("msg_save_error", ui_text("msg_save_error"), error=exc),
            )

    # Left entry list

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self):
        self._clear_entry_list()
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()
        self._update_action_state()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_idx))

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        title_text = self._entry_title(idx)
        subtitle_text = self._entry_subtitle(entry)

        name_lbl = QLabel(_truncate(title_text, 24))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        name_lbl.setToolTip(title_text)
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        id_lbl = QLabel(_truncate(subtitle_text, 28))
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(ss_dim_label())
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        id_lbl.setToolTip(subtitle_text)
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(id_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _entry_title(self, idx: int) -> str:
        return f"Entry {idx:04d}"

    def _entry_subtitle(self, entry: dict) -> str:
        bgm_id = entry.get("bgm_id", "").strip() or "<empty>"
        chara = entry.get("chara_code", "").strip() or "<none>"
        return f"{bgm_id} / {chara}"

    def _filter_list(self):
        query = self._search_entry.text().lower().strip()
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join(
                [
                    self._entry_title(idx),
                    entry.get("bgm_id", ""),
                    entry.get("chara_code", ""),
                    entry.get("sound_str1", ""),
                    entry.get("sound_str2", ""),
                ]
            ).lower()
            btn.setVisible(not query or query in haystack)

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        self._apply_current_entry()
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)
        self._update_action_state()

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 2:
                title_text = self._entry_title(idx)
                subtitle_text = self._entry_subtitle(self._entries[idx])
                labels[0].setText(_truncate(title_text, 24))
                labels[0].setToolTip(title_text)
                labels[1].setText(_truncate(subtitle_text, 28))
                labels[1].setToolTip(subtitle_text)
            break
        self._filter_list()

    def _update_action_state(self):
        loaded = self._raw_data is not None
        has_selection = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        self._btn_save.setEnabled(loaded)
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(loaded and has_selection)
        self._del_btn.setEnabled(loaded and has_selection)

    # Right editor

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

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        entry = self._entries[idx]
        self._block_detail = True
        self._last_compact = self._is_compact_editor()
        subtitle = _truncate(self._entry_subtitle(entry), 54 if self._last_compact else 92)

        hdr, hdr_layout = make_editor_grid_card(
            self._editor_widget,
            title=self._entry_title(idx),
            icon_name="fa6s.music",
            subtitle=subtitle,
            grid_margins=(0, 2, 0, 0),
            vertical_spacing=8,
        )
        self._prep_card(hdr)
        self._active_grid_columns = 3

        self._add_field(hdr_layout, 0, 0, "bgm_id", "BGM_ID", entry.get("bgm_id", ""), maxlen=64, big=True)
        self._add_field(hdr_layout, 0, 1, "chara_code", ui_text("ui_soundtestparam_characode"), entry.get("chara_code", ""), maxlen=32, big=True)
        self._add_spin_field(hdr_layout, 0, 2, "index", ui_text("ui_dictionaryparam_index"), int(entry.get("index", 0)), 0, 0x7FFFFFFF, big=True)
        self._editor_layout.addWidget(hdr)

        self._add_section(ui_text("ui_soundtestparam_audio_cues"))
        cue = self._make_card()
        cue_grid = self._card_grid(cue)
        self._add_field(
            cue_grid,
            0,
            0,
            "sound_str1",
            ui_text("ui_soundtestparam_soundstr1"),
            entry.get("sound_str1", ""),
            maxlen=64,
            hint=ui_text("ui_soundtestparam_audio_cue_for_title_cursor_playback"),
            max_columns=2,
        )
        self._add_field(
            cue_grid,
            0,
            1,
            "sound_str2",
            ui_text("ui_soundtestparam_soundstr2"),
            entry.get("sound_str2", ""),
            maxlen=64,
            hint=ui_text("ui_soundtestparam_audio_cue_for_hover_selection_playback"),
            max_columns=2,
        )
        self._editor_layout.addWidget(cue)

        self._add_section(ui_text("ui_soundtestparam_unlock_pricing"))
        unlock = self._make_card()
        unlock_grid = self._card_grid(unlock)
        self._active_grid_columns = 3
        self._add_unlock_field(unlock_grid, 0, 0, int(entry.get("unlock_cond", 1)))
        self._add_spin_field(
            unlock_grid,
            0,
            1,
            "menu_index",
            ui_text("ui_soundtestparam_menuindex"),
            int(entry.get("menu_index", 1)),
            0,
            0xFFFF,
            hint=ui_text("ui_soundtestparam_display_group_section_index_in_the_sound_test_menu"),
        )
        self._add_spin_field(
            unlock_grid,
            0,
            2,
            "price",
            ui_text("ui_customcardparam_price"),
            int(entry.get("price", 1000)),
            0,
            0x7FFFFFFF,
            hint=ui_text("ui_soundtestparam_shop_price_in_g"),
        )
        self._editor_layout.addWidget(unlock)

        self._add_section(ui_text("ui_soundtestparam_reserved_fields"))
        reserved = self._make_card()
        reserved_grid = self._card_grid(reserved)
        self._add_field(reserved_grid, 0, 0, "unk1", "unk1", entry.get("unk1", ""), maxlen=64)
        self._add_field(reserved_grid, 0, 1, "unk2", "unk2", entry.get("unk2", ""), maxlen=64)
        self._add_field(reserved_grid, 0, 2, "unk3", "unk3", entry.get("unk3", ""), maxlen=64)
        self._editor_layout.addWidget(reserved)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

        self._block_detail = False

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _grid_columns(self, max_columns: int) -> int:
        width = self._editor_scroll.viewport().width()
        if width < 780:
            return 1
        if width < 1080:
            return min(2, max_columns)
        return max_columns

    def _field_position(self, row: int, col: int, max_columns: int) -> tuple[int, int]:
        columns = self._grid_columns(max_columns)
        logical_index = row * max_columns + col
        return divmod(logical_index, columns)

    def _prep_card(self, card: QFrame):
        card.setMinimumWidth(0)
        card.setMaximumWidth(980)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=section_title,
            icon_name="fa6s.music",
            vertical_spacing=10,
        )
        self._prep_card(card)
        card._editor_grid = grid
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        return card._editor_grid

    def _field_shell(self, label: str, hint: str = "") -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label, hint)
        return frame, layout

    def _add_field(
        self,
        grid: QGridLayout,
        row: int,
        col: int,
        key: str,
        label: str,
        value: str,
        maxlen: int = 64,
        hint: str = "",
        big: bool = False,
        max_columns: int | None = None,
    ):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setMaxLength(maxlen)
        edit.setFixedHeight(36 if big else 30)
        edit.setFont(QFont("Consolas", 16 if big else 13))
        edit.setStyleSheet(ss_input())
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.textChanged.connect(lambda _text, k=key: self._on_field_changed(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        mapped_row, mapped_col = self._field_position(row, col, max_columns or self._active_grid_columns)
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = edit

    def _add_spin_field(
        self,
        grid: QGridLayout,
        row: int,
        col: int,
        key: str,
        label: str,
        value: int,
        min_value: int,
        max_value: int,
        hint: str = "",
        big: bool = False,
        max_columns: int | None = None,
    ):
        frame, layout = self._field_shell(label, hint)
        spin = QSpinBox()
        spin.setRange(min_value, max_value)
        spin.setFixedHeight(36 if big else 30)
        spin.setFont(QFont("Consolas", 16 if big else 13))
        spin.setStyleSheet(ss_input())
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setValue(value)
        spin.setMinimumWidth(0)
        spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        spin.valueChanged.connect(lambda _value, k=key: self._on_field_changed(k))
        layout.addWidget(spin)
        self._prep_field_widget(frame, spin)
        mapped_row, mapped_col = self._field_position(row, col, max_columns or self._active_grid_columns)
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = spin

    def _add_unlock_field(self, grid: QGridLayout, row: int, col: int, value: int, max_columns: int | None = None):
        frame, layout = self._field_shell(
            ui_text("ui_soundtestparam_unlockcond"),
            ui_text("ui_soundtestparam_1_default_4_shop_6_character_specific"),
        )
        combo = QComboBox()
        for unlock_value, label in _UNLOCK_LABELS.items():
            combo.addItem(label, unlock_value)
        combo.setFixedHeight(30)
        combo.setFont(QFont("Segoe UI", 12))
        combo.setStyleSheet(ss_input())
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                break
        combo.currentIndexChanged.connect(lambda _idx: self._on_field_changed("unlock_cond"))
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        mapped_row, mapped_col = self._field_position(row, col, max_columns or self._active_grid_columns)
        grid.addWidget(frame, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields["unlock_cond"] = combo

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx is None or self._block_detail:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._build_editor(self._current_idx)

    def _on_field_changed(self, key: str):
        if self._block_detail or self._current_idx is None:
            return
        self._apply_field(key)
        self._dirty = True
        if key in {"bgm_id", "chara_code"}:
            self._refresh_entry_button(self._current_idx)

    def _apply_field(self, key: str):
        if self._current_idx is None or self._current_idx >= len(self._entries):
            return
        widget = self._fields.get(key)
        if widget is None:
            return
        entry = self._entries[self._current_idx]
        try:
            if isinstance(widget, QLineEdit):
                entry[key] = widget.text().strip()
            elif isinstance(widget, QSpinBox):
                entry[key] = int(widget.value())
            elif isinstance(widget, QComboBox):
                entry[key] = int(widget.currentData())
        except (TypeError, ValueError):
            pass

    def _apply_current_entry(self):
        if self._current_idx is None:
            return
        for key in list(self._fields.keys()):
            self._apply_field(key)
        self._refresh_entry_button(self._current_idx)

    # Add / Duplicate / Delete

    def _do_add(self):
        if self._raw_data is None:
            return
        self._apply_current_entry()
        self._entries.append(make_default_entry())
        self._dirty = True
        new_idx = len(self._entries) - 1
        self._populate_list()
        self._select_entry(new_idx)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        self._apply_current_entry()
        new_entry = copy.deepcopy(self._entries[self._current_idx])
        self._entries.insert(self._current_idx + 1, new_entry)
        self._dirty = True
        new_idx = self._current_idx + 1
        self._populate_list()
        self._select_entry(new_idx)

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        name = self._entry_subtitle(entry)
        reply = QMessageBox.question(
            self,
            self._tr("dlg_title_confirm_delete", ui_text("dlg_title_confirm_delete")),
            self._tr("msg_confirm_delete_item", ui_text("msg_confirm_delete_item"), name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        removed_idx = self._current_idx
        self._entries.pop(removed_idx)
        self._dirty = True
        self._current_idx = None
        self._populate_list()

        if self._entries:
            self._select_entry(min(removed_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_soundtestparam_no_entries"))
            self._update_action_state()
