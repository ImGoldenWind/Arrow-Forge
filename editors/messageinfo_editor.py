"""editors/messageinfo_editor.py – Game Text Editor (messageInfo.bin.xfbin)."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea, QTextEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from parsers.messageinfo_parser import (
    parse_messageinfo_xfbin, save_messageinfo_xfbin,
)
from core.translations import ui_text


_CHAR_NAMES: dict[int, str] = {
    -1: ui_text("ui_messageinfo_system"),
    1:  ui_text("ui_messageinfo_guide_characters"),
    2:  ui_text("ui_messageinfo_unknown"),
    3:  ui_text("char_0bao01"),
    4:  ui_text("char_1dio01"),
    5:  ui_text("char_1jnt01"),
    6:  ui_text("char_1sdw01"),
    7:  ui_text("char_1zpl01"),
    8:  ui_text("char_2csr01"),
    9:  ui_text("char_2esd01"),
    10: ui_text("char_2jsp01"),
    11: ui_text("char_2krs01"),
    12: ui_text("char_2lsa01"),
    13: ui_text("ui_messageinfo_wammu"),
    14: ui_text("char_3abd01"),
    15: "DIO",
    16: ui_text("char_3hhs01"),
    17: ui_text("char_3igy01"),
    18: ui_text("ui_messageinfo_old_joseph"),
    19: ui_text("char_3jtr01"),
    20: ui_text("char_3kki01"),
    21: ui_text("char_3mra01"),
    22: ui_text("char_3pln01"),
    23: ui_text("char_3psp01"),
    24: ui_text("ui_messageinfo_vanilla_ice"),
    25: ui_text("ui_messageinfo_josuke_higashikata"),
    26: ui_text("ui_messageinfo_jotaro_kujo_4"),
    27: ui_text("char_4kir01"),
    28: ui_text("char_4koi01"),
    29: ui_text("char_4kwk01"),
    30: ui_text("ui_messageinfo_okuyasu_nijumura"),
    31: ui_text("char_4oti01"),
    32: ui_text("char_4rhn01"),
    33: ui_text("char_4sgc01"),
    34: ui_text("char_4ykk01"),
    35: ui_text("char_5bct01"),
    36: ui_text("char_5dvl01"),
    37: ui_text("ui_messageinfo_pannacota_fugo"),
    38: ui_text("char_5gac01"),
    39: ui_text("char_5grn01"),
    40: ui_text("char_5mst01"),
    41: ui_text("char_5nrc01"),
    42: ui_text("ui_messageinfo_prosciutto_and_pesci"),
    43: ui_text("ui_messageinfo_trish_uno"),
    44: ui_text("char_6ans01"),
    45: ui_text("char_6elm01"),
    46: ui_text("char_6fit01"),
    47: ui_text("ui_messageinfo_jolyne_kujo"),
    48: ui_text("ui_messageinfo_enrico_pucci_white_snake"),
    49: ui_text("char_7dio01"),
    50: ui_text("char_7jir01"),
    51: ui_text("char_7jny01"),
    52: ui_text("char_7vtn01"),
    53: ui_text("char_8jsk01"),
    56: ui_text("ui_messageinfo_misc"),
    57: ui_text("ui_messageinfo_misc"),
    58: ui_text("char_6wet01"),
    59: ui_text("char_6wet01"),
    60: ui_text("ui_messageinfo_rissoto_nero"),
    61: ui_text("ui_messageinfo_rissoto_nero"),
    62: ui_text("ui_messageinfo_final_pucci"),
    63: ui_text("ui_messageinfo_final_pucci"),
    64: ui_text("char_2shm01"),
    65: ui_text("char_2shm01"),
    66: ui_text("ui_messageinfo_keicho_nijumura"),
    67: ui_text("ui_messageinfo_keicho_nijumura"),
    68: ui_text("ui_messageinfo_alternative_diego_brando"),
    69: ui_text("ui_messageinfo_alternative_diego_brando"),
    70: ui_text("char_5abc01"),
    71: ui_text("char_5abc01"),
    72: ui_text("char_4fgm01"),
    73: ui_text("char_4fgm01"),
    74: ui_text("char_8wou01"),
    75: ui_text("char_8wou01"),
}


def _char_label(char_id: int) -> str:
    name = _CHAR_NAMES.get(char_id)
    return name if name else f"ID {char_id}"


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class _FocusLineEdit(QLineEdit):
    """QLineEdit that calls a callback when it receives focus."""
    def __init__(self, focus_cb, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._focus_cb = focus_cb

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._focus_cb()


class _FocusTextEdit(QTextEdit):
    """QTextEdit that calls a callback when it receives focus."""
    def __init__(self, focus_cb, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._focus_cb = focus_cb

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._focus_cb()


class MessageInfoEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath: str | None = None
        self._original_data: bytearray | None = None
        self._version: int = 1001
        self._entries: list[dict] = []
        self._orig_entries: list[dict] = []

        self._current_char_id: int | None = None
        self._char_buttons: list[tuple] = []      # (QPushButton, char_id)
        self._selected_entry_idx: int | None = None
        self._card_widgets: list[tuple] = []       # (entry_idx, QFrame)

        # Pagination state for right panel
        self._all_char_entries: list[tuple] = []  # full (idx, entry) list for current char
        self._loaded_count: int = 0
        self._cards_layout = None                  # layout to append more cards into
        self._load_more_btn: QPushButton | None = None

        # Debounce for right-panel entry search
        self._entry_search_timer = QTimer()
        self._entry_search_timer.setSingleShot(True)
        self._entry_search_timer.setInterval(250)
        self._entry_search_timer.timeout.connect(self._do_entry_search)

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar — identical structure to CharacterStatsEditor
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("ui_btladjprm_no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {P['mid']};")
        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(ui_text("ui_damageeff_search"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        # Action buttons — same layout as CharacterStatsEditor
        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(ui_text("ui_messageinfo_add"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._on_add_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(ui_text("btn_dup_short"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._on_dup_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(ui_text("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._on_delete_entry)
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

        # Scrollable character list
        self._char_scroll = QScrollArea()
        self._char_scroll.setWidgetResizable(True)
        self._char_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._char_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self._char_list_widget = QWidget()
        self._char_list_widget.setStyleSheet("background-color: transparent;")
        self._char_list_layout = QVBoxLayout(self._char_list_widget)
        self._char_list_layout.setContentsMargins(0, 0, 0, 0)
        self._char_list_layout.setSpacing(1)
        self._char_list_layout.addStretch()
        self._char_scroll.setWidget(self._char_list_widget)
        list_vlayout.addWidget(self._char_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Right panel container (header + scrollable cards)
        right_container = QWidget()
        right_container.setStyleSheet(f"background-color: {P['bg_dark']};")
        right_vlayout = QVBoxLayout(right_container)
        right_vlayout.setContentsMargins(0, 0, 0, 0)
        right_vlayout.setSpacing(0)

        # Persistent header: character title + entry search
        right_header = QFrame()
        right_header.setFixedHeight(46)
        right_header.setStyleSheet(f"background-color: {P['bg_panel']};")
        rh_layout = QHBoxLayout(right_header)
        rh_layout.setContentsMargins(16, 8, 12, 8)
        rh_layout.setSpacing(10)

        self._right_title_lbl = QLabel("")
        self._right_title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._right_title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        rh_layout.addWidget(self._right_title_lbl, 1)

        self._entry_search = QLineEdit()
        self._entry_search.setPlaceholderText(ui_text("ui_messageinfo_search_entries"))
        self._entry_search.setFixedHeight(30)
        self._entry_search.setFixedWidth(220)
        self._entry_search.setFont(QFont("Segoe UI", 10))
        self._entry_search.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 8px; border-radius: 4px; }}"
            f"QLineEdit:focus {{ border: 1px solid {P['accent']}; }}"
        )
        self._entry_search.textChanged.connect(lambda _: self._entry_search_timer.start())
        rh_layout.addWidget(self._entry_search)

        right_vlayout.addWidget(right_header)

        rh_sep = QFrame()
        rh_sep.setFixedHeight(1)
        rh_sep.setStyleSheet(f"background-color: {P['mid']};")
        right_vlayout.addWidget(rh_sep)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {P['bg_dark']}; border: none; }}"
        )
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        self._show_placeholder(ui_text("ui_btladjprm_no_file_loaded"))

        right_vlayout.addWidget(self._editor_scroll, 1)
        main_layout.addWidget(right_container, 1)
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._card_widgets = []
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    # Character list (left panel)

    def _get_char_groups(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for i, e in enumerate(self._entries):
            groups.setdefault(e["char_id"], []).append(i)
        return dict(sorted(groups.items()))

    def _populate_char_list(self, search: str = ""):
        _clear_layout(self._char_list_layout)
        self._char_buttons = []
        self._char_list_layout.addStretch()

        s = search.lower().strip()
        for char_id, indices in self._get_char_groups().items():
            if s:
                if s not in _char_label(char_id).lower() and s not in str(char_id):
                    continue

            btn = self._make_char_button(char_id, len(indices))
            self._char_list_layout.insertWidget(self._char_list_layout.count() - 1, btn)
            self._char_buttons.append((btn, char_id))

        self._update_char_button_styles()

    def _make_char_button(self, char_id: int, count: int) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border-radius: 6px; "
            f"text-align: left; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )

        inner = QVBoxLayout(btn)
        inner.setContentsMargins(10, 3, 10, 3)
        inner.setSpacing(0)

        name_lbl = QLabel(_char_label(char_id))
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(name_lbl)

        count_lbl = QLabel(ui_text("ui_messageinfo_value_entries", p0=count))
        count_lbl.setFont(QFont("Consolas", 11))
        count_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        count_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(count_lbl)

        btn.clicked.connect(lambda checked=False, cid=char_id: self._select_char(cid))
        return btn

    def _update_char_button_styles(self):
        for btn, cid in self._char_buttons:
            if cid == self._current_char_id:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {P['bg_card']}; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }} "
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }} "
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )

    def _filter_list(self):
        self._populate_char_list(self._search_entry.text())

    def _do_entry_search(self):
        """Scroll the right panel to the first entry matching the search bar."""
        s = self._entry_search.text().lower().strip()
        if not s or not self._all_char_entries:
            return
        for idx, entry in self._all_char_entries:
            if s in entry["message"].lower() or s in f"{entry['crc32_id']:08x}":
                self._scroll_to_entry(idx)
                return

    def _select_char(self, char_id: int):
        self._current_char_id = char_id
        self._selected_entry_idx = None
        self._dup_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._entry_search.clear()
        self._update_char_button_styles()
        self._build_entries_panel(char_id)

    # Entries panel (right panel)

    _PAGE_SIZE = 100

    def _build_entries_panel(self, char_id: int):
        _clear_layout(self._editor_layout)
        self._card_widgets = []
        self._load_more_btn = None
        self._cards_layout = None
        self._all_char_entries = []
        self._loaded_count = 0

        self._right_title_lbl.setText(_char_label(char_id))

        char_entries = [(i, self._entries[i]) for i in range(len(self._entries))
                        if self._entries[i]["char_id"] == char_id]

        if not char_entries:
            lbl = QLabel(ui_text("ui_messageinfo_no_entries_for_this_character"))
            lbl.setFont(QFont("Segoe UI", 13))
            lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._editor_layout.addStretch()
            self._editor_layout.addWidget(lbl)
            self._editor_layout.addStretch()
            return

        self._all_char_entries = char_entries

        container = QWidget()
        container.setStyleSheet(f"background-color: {P['bg_dark']};")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 4, 16, 16)
        container_layout.setSpacing(8)
        self._cards_layout = container_layout

        self._editor_layout.addWidget(container)
        self._editor_layout.addStretch()

        self._render_next_page()

    def _render_next_page(self):
        if self._cards_layout is None:
            return
        start = self._loaded_count
        end = min(start + self._PAGE_SIZE, len(self._all_char_entries))

        # Remove old "Load more" button before appending new cards
        if self._load_more_btn is not None:
            self._cards_layout.removeWidget(self._load_more_btn)
            self._load_more_btn.deleteLater()
            self._load_more_btn = None

        for pos in range(start, end):
            entry_idx, entry = self._all_char_entries[pos]
            card = self._make_entry_card(entry_idx, entry)
            self._cards_layout.addWidget(card)
            self._card_widgets.append((entry_idx, card))

        self._loaded_count = end
        remaining = len(self._all_char_entries) - end

        if remaining > 0:
            batch = min(remaining, self._PAGE_SIZE)
            self._load_more_btn = QPushButton(
                ui_text("ui_messageinfo_load_value_more_value_remaining", p0=batch, p1=remaining)
            )
            self._load_more_btn.setFixedHeight(34)
            self._load_more_btn.setFont(QFont("Segoe UI", 10))
            self._load_more_btn.setStyleSheet(ss_btn())
            self._load_more_btn.clicked.connect(self._render_next_page)
            self._cards_layout.addWidget(self._load_more_btn)

    def _make_entry_card(self, entry_idx: int, entry: dict) -> QFrame:
        card = QFrame()
        card.setObjectName(ui_text("ui_messageinfo_entrycard"))
        card.setStyleSheet(
            f"QFrame#entryCard {{ background-color: {P['bg_panel']}; border-radius: 8px; "
            f"border: 1px solid {P['border']}; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(6)

        def on_select(idx=entry_idx, c=card):
            self._select_card(idx, c)

        # Fields row
        fields_w = QWidget()
        fields_w.setStyleSheet("background: transparent;")
        fields_layout = QGridLayout(fields_w)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setHorizontalSpacing(12)
        fields_layout.setVerticalSpacing(4)
        fields_layout.setColumnStretch(0, 2)
        fields_layout.setColumnStretch(1, 1)
        fields_layout.setColumnStretch(2, 1)
        fields_layout.setColumnStretch(3, 1)

        def make_field(label_text, value_str, col, read_only=False, accent=False):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(lbl)
            fg = P['accent'] if accent else P['text_main']
            if read_only:
                e = QLineEdit(value_str)
                e.setReadOnly(True)
            else:
                e = _FocusLineEdit(on_select, value_str)
            e.setFixedHeight(28)
            e.setFont(QFont("Consolas", 12))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {fg}; padding: 2px 6px; border-radius: 4px; }}"
            )
            fl.addWidget(e)
            fields_layout.addWidget(f, 0, col)
            return e

        e_crc  = make_field(ui_text("ui_messageinfo_crc32_id"), f"{entry['crc32_id']:08X}", 0, accent=True)
        e_char = make_field(ui_text("ui_assist_char_id"),  str(entry["char_id"]),       1)
        e_cue  = make_field(ui_text("ui_messageinfo_cue_id"),   str(entry["cue_id"]),        2)
        type_str = ui_text("ui_messageinfo_reference") if entry["is_ref"] == 1 else ui_text("ui_mainmodeparam_normal")
        make_field(ui_text("ui_dlcinfoparam_type"), type_str, 3, read_only=True)

        card_layout.addWidget(fields_w)

        # Ref CRC32 row — show for reference entries or when non-zero
        e_ref = None
        if entry["is_ref"] == 1 or entry.get("ref_crc32", 0):
            ref_w = QWidget()
            ref_w.setStyleSheet("background: transparent;")
            ref_wl = QVBoxLayout(ref_w)
            ref_wl.setContentsMargins(0, 0, 0, 0)
            ref_wl.setSpacing(2)
            ref_lbl = QLabel(ui_text("ui_messageinfo_ref_crc32"))
            ref_lbl.setFont(QFont("Segoe UI", 11))
            ref_lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            ref_wl.addWidget(ref_lbl)
            e_ref = _FocusLineEdit(on_select, f"{entry['ref_crc32']:08X}" if entry.get("ref_crc32") else "00000000")
            e_ref.setFixedHeight(28)
            e_ref.setFont(QFont("Consolas", 12))
            e_ref.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['secondary']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            ref_wl.addWidget(e_ref)
            card_layout.addWidget(ref_w)

        # Message text area
        msg_lbl = QLabel(ui_text("ui_messageinfo_message"))
        msg_lbl.setFont(QFont("Segoe UI", 11))
        msg_lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
        card_layout.addWidget(msg_lbl)

        msg_edit = _FocusTextEdit(on_select)
        msg_edit.setFont(QFont("Segoe UI", 10))
        msg_edit.setStyleSheet(
            f"QTextEdit {{ background-color: {P['bg_card']}; color: {P['text_main']}; "
            f"border: 1px solid {P['border']}; border-radius: 4px; padding: 4px; }}"
            f"QTextEdit:focus {{ border: 1px solid {P['accent']}; }}"
        )
        msg_edit.setPlainText(entry["message"])
        msg_edit.setFixedHeight(72)
        card_layout.addWidget(msg_edit)

        # Auto-save connections
        def _crc_changed(text, idx=entry_idx):
            try:
                self._entries[idx]["crc32_id"] = int(text.strip() or "0", 16) & 0xFFFFFFFF
                self._mark_dirty()
            except ValueError:
                pass

        def _char_changed(text, idx=entry_idx):
            try:
                self._entries[idx]["char_id"] = int(text.strip())
                self._mark_dirty()
            except ValueError:
                pass

        def _cue_changed(text, idx=entry_idx):
            try:
                self._entries[idx]["cue_id"] = int(text.strip())
                self._mark_dirty()
            except ValueError:
                pass

        def _ref_changed(text, idx=entry_idx):
            try:
                self._entries[idx]["ref_crc32"] = int(text.strip() or "0", 16) & 0xFFFFFFFF
                self._mark_dirty()
            except ValueError:
                pass

        def _msg_changed(idx=entry_idx):
            self._entries[idx]["message"] = msg_edit.toPlainText()
            self._mark_dirty()

        e_crc.textChanged.connect(_crc_changed)
        e_char.textChanged.connect(_char_changed)
        e_cue.textChanged.connect(_cue_changed)
        if e_ref is not None:
            e_ref.textChanged.connect(_ref_changed)
        msg_edit.textChanged.connect(_msg_changed)

        # Per-card action buttons
        btn_row = QWidget()
        btn_row.setStyleSheet("background: transparent;")
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 4, 0, 0)
        btn_row_layout.setSpacing(4)

        _btn_font = QFont("Segoe UI", 9)

        card_add_btn = QPushButton(ui_text("ui_messageinfo_add"))
        card_add_btn.setFixedHeight(24)
        card_add_btn.setFont(_btn_font)
        card_add_btn.setStyleSheet(ss_btn())
        card_add_btn.clicked.connect(lambda checked=False, idx=entry_idx: self._card_add_entry(idx))
        btn_row_layout.addWidget(card_add_btn)

        card_dup_btn = QPushButton(ui_text("btn_dup_short"))
        card_dup_btn.setFixedHeight(24)
        card_dup_btn.setFont(_btn_font)
        card_dup_btn.setStyleSheet(ss_btn())
        card_dup_btn.clicked.connect(lambda checked=False, idx=entry_idx: self._card_dup_entry(idx))
        btn_row_layout.addWidget(card_dup_btn)

        card_del_btn = QPushButton(ui_text("btn_delete"))
        card_del_btn.setFixedHeight(24)
        card_del_btn.setFont(_btn_font)
        card_del_btn.setStyleSheet(ss_btn(danger=True))
        card_del_btn.clicked.connect(lambda checked=False, idx=entry_idx: self._card_delete_entry(idx))
        btn_row_layout.addWidget(card_del_btn)

        btn_row_layout.addStretch()
        card_layout.addWidget(btn_row)

        card.mousePressEvent = lambda ev, idx=entry_idx, c=card: self._select_card(idx, c)
        return card

    def _select_card(self, entry_idx: int, card: QFrame):
        for _, c in self._card_widgets:
            c.setStyleSheet(
                f"QFrame#entryCard {{ background-color: {P['bg_panel']}; border-radius: 8px; "
                f"border: 1px solid {P['border']}; }}"
            )
        self._selected_entry_idx = entry_idx
        card.setStyleSheet(
            f"QFrame#entryCard {{ background-color: {P['bg_card']}; border-radius: 8px; "
            f"border: 2px solid {P['accent']}; }}"
        )
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

    # Left panel CRUD (operates on character groups)

    def _next_free_char_id(self) -> int:
        existing = {e["char_id"] for e in self._entries}
        cid = 0
        while cid in existing:
            cid += 1
        return cid

    def _on_add_entry(self):
        """Add a new character group to the left panel."""
        new_id = self._next_free_char_id()
        new_entry = {
            "crc32_id": 0,
            "unk1": 0, "unk2": 0, "unk3": 0,
            "message": "",
            "ref_crc32": 0,
            "is_ref": -1,
            "char_id": new_id,
            "cue_id": -1,
            "unk6": -1,
            "unk7": 0,
        }
        self._entries.append(new_entry)
        self._orig_entries.append(dict(new_entry))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._select_char(new_id)

    def _on_dup_entry(self):
        """Duplicate current character group into a new char_id."""
        if self._current_char_id is None:
            return
        src_id = self._current_char_id
        src_entries = [e for e in self._entries if e["char_id"] == src_id]
        if not src_entries:
            return
        new_id = self._next_free_char_id()
        for e in src_entries:
            dup = copy.deepcopy(e)
            dup["char_id"] = new_id
            self._entries.append(dup)
            self._orig_entries.append(dict(dup))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._select_char(new_id)

    def _on_delete_entry(self):
        """Delete all entries for the current character group."""
        if self._current_char_id is None:
            return
        char_id = self._current_char_id
        count = sum(1 for e in self._entries if e["char_id"] == char_id)
        ans = QMessageBox.question(
            self, ui_text("ui_messageinfo_confirm"),
            ui_text("ui_messageinfo_delete_character_value_and_all_value_entries", p0=_char_label(char_id), p1=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        indices = sorted(
            [i for i, e in enumerate(self._entries) if e["char_id"] == char_id],
            reverse=True,
        )
        for i in indices:
            del self._entries[i]
            if i < len(self._orig_entries):
                del self._orig_entries[i]
        self._current_char_id = None
        self._selected_entry_idx = None
        self._dup_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        if self._char_buttons:
            self._select_char(self._char_buttons[0][1])
        else:
            self._show_placeholder(ui_text("ui_messageinfo_select_a_character"))

    # Per-card CRUD (operates on individual entries)

    def _scroll_to_entry(self, global_idx: int):
        """Load pages as needed and scroll the right panel to the given entry."""
        char_pos = next(
            (pos for pos, (idx, _) in enumerate(self._all_char_entries) if idx == global_idx),
            None,
        )
        if char_pos is None:
            return
        while self._loaded_count <= char_pos and self._loaded_count < len(self._all_char_entries):
            self._render_next_page()
        if char_pos < len(self._card_widgets):
            _, card = self._card_widgets[char_pos]
            QTimer.singleShot(60, lambda c=card: self._editor_scroll.ensureWidgetVisible(c))

    def _card_add_entry(self, after_idx: int):
        """Insert a new blank entry after the card at after_idx."""
        char_id = self._entries[after_idx]["char_id"]
        new_entry = {
            "crc32_id": 0,
            "unk1": 0, "unk2": 0, "unk3": 0,
            "message": "",
            "ref_crc32": 0,
            "is_ref": -1,
            "char_id": char_id,
            "cue_id": -1,
            "unk6": -1,
            "unk7": 0,
        }
        insert_pos = after_idx + 1
        self._entries.insert(insert_pos, new_entry)
        self._orig_entries.insert(insert_pos, dict(new_entry))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._build_entries_panel(char_id)
        self._scroll_to_entry(insert_pos)

    def _card_dup_entry(self, entry_idx: int):
        """Duplicate the entry at entry_idx and insert it after."""
        src = self._entries[entry_idx]
        char_id = src["char_id"]
        dup = copy.deepcopy(src)
        insert_pos = entry_idx + 1
        self._entries.insert(insert_pos, dup)
        self._orig_entries.insert(insert_pos, copy.deepcopy(dup))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._build_entries_panel(char_id)
        self._scroll_to_entry(insert_pos)

    def _card_delete_entry(self, entry_idx: int):
        """Delete the entry at entry_idx."""
        char_id = self._entries[entry_idx]["char_id"]
        ans = QMessageBox.question(
            self, ui_text("ui_messageinfo_confirm"), ui_text("ui_messageinfo_delete_this_entry"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        del self._entries[entry_idx]
        if entry_idx < len(self._orig_entries):
            del self._orig_entries[entry_idx]
        if self._selected_entry_idx == entry_idx:
            self._selected_entry_idx = None
            self._dup_btn.setEnabled(False)
            self._del_btn.setEnabled(False)
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        if char_id in self._get_char_groups():
            self._build_entries_panel(char_id)
        else:
            self._current_char_id = None
            self._show_placeholder(ui_text("ui_messageinfo_select_a_character"))
            self._update_char_button_styles()

    # Dirty state

    def _mark_dirty(self):
        self._btn_save.setEnabled(True)
        name = os.path.basename(self._filepath) if self._filepath else ""
        self._file_lbl.setText(ui_text("ui_effect_value", p0=name))
        self._file_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")

    # File operations

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_messageinfo_open_messageinfo_bin_xfbin"), "",
            "XFBIN Files (*.xfbin);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, filepath: str):
        try:
            data, version, entries = parse_messageinfo_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return

        self._filepath = filepath
        self._original_data = data
        self._version = version
        self._entries = entries
        self._orig_entries = [dict(e) for e in entries]
        self._current_char_id = None
        self._selected_entry_idx = None

        self._file_lbl.setText(os.path.basename(filepath))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._btn_save.setEnabled(True)
        self._add_btn.setEnabled(True)

        self._populate_char_list()
        groups = self._get_char_groups()
        if groups:
            self._select_char(next(iter(groups)))
        else:
            self._show_placeholder(ui_text("ui_assist_no_entries_found"))

    def _on_save(self):
        if not self._filepath or self._original_data is None:
            return
        try:
            save_messageinfo_xfbin(
                self._filepath, self._original_data, self._version, self._entries
            )
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), ui_text("ui_assist_failed_to_save_value", p0=exc))
            return
        self._orig_entries = [dict(e) for e in self._entries]
        self._file_lbl.setText(os.path.basename(self._filepath))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
