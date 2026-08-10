"""editors/messageinfo_editor.py – Game Text Editor (messageInfo.bin.xfbin)."""

import os
import copy
import re
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea, QTextEdit, QSizePolicy, QTableView, QAbstractItemView,
    QHeaderView, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_bg_dark, ss_bg_panel, ss_btn, ss_accent_sep, ss_dim_label,
    ss_file_label, ss_main_label, ss_input, ss_table, ss_textedit, ss_progressbar,
    ss_scrollarea_transparent, ss_field_label, ss_search, ss_sep,
    ss_sidebar_btn, ss_sidebar_frame, ss_transparent,
    make_editor_card, make_editor_field_shell, add_editor_card_title, make_empty_state,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonBar, SkeletonListRow
from core.messageinfo_id_map import MessageInfoIdMap
from core.messageinfo_memory_scanner import (
    list_processes,
    scan_process_strings,
)
from parsers.messageinfo_parser import (
    parse_messageinfo_xfbin, save_messageinfo_xfbin,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


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


_ALL_STRINGS = "__all_strings__"
_TEXT_REF_RE = re.compile(r"<text\s+([A-Za-z0-9_./:-]+)\b", re.IGNORECASE)


def _char_label(char_id: int) -> str:
    name = _CHAR_NAMES.get(char_id)
    return name if name else f"ID {char_id}"


def _scope_label(scope) -> str:
    return ui_text("ui_messageinfo_all_strings") if scope == _ALL_STRINGS else _char_label(scope)


def _truncate(text: str, limit: int = 28) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            w = item.widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _message_text_id(message: str) -> str:
    match = _TEXT_REF_RE.search(message or "")
    return match.group(1) if match else ""


def _entry_string_id(entry: dict, id_map: MessageInfoIdMap) -> str:
    direct = _message_text_id(entry.get("message", ""))
    if direct:
        return direct
    values = id_map.resolve(int(entry.get("crc32_id", 0)))
    return values[0] if values else ""


def _entry_string_display(entry: dict, id_map: MessageInfoIdMap) -> str:
    direct = _message_text_id(entry.get("message", ""))
    if direct:
        return direct
    return id_map.display(int(entry.get("crc32_id", 0)))


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


class _MessageInfoTableModel(QAbstractTableModel):
    _HEADERS = (
        "ui_messageinfo_string_id",
        "ui_messageinfo_crc32_id",
        "ui_assist_char_id",
        "ui_messageinfo_cue_id",
        "ui_dlcinfoparam_type",
        "ui_messageinfo_ref_crc32",
        "ui_messageinfo_message",
    )

    def __init__(self, entries: list[dict], indices: list[int], id_map: MessageInfoIdMap, parent=None):
        super().__init__(parent)
        self._entries = entries
        self._indices = indices
        self._id_map = id_map

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._indices)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        if 0 <= section < len(self._HEADERS):
            return ui_text(self._HEADERS[section])
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._indices):
            return None
        entry_idx = self._indices[index.row()]
        entry = self._entries[entry_idx]

        if role == Qt.ItemDataRole.UserRole:
            return entry_idx
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        col = index.column()
        if col == 0:
            return _entry_string_display(entry, self._id_map)
        if col == 1:
            return f"{entry['crc32_id']:08X}"
        if col == 2:
            return str(entry["char_id"])
        if col == 3:
            return str(entry["cue_id"])
        if col == 4:
            return ui_text("ui_messageinfo_reference") if entry["is_ref"] == 1 else ui_text("ui_mainmodeparam_normal")
        if col == 5:
            return f"{entry['ref_crc32']:08X}" if entry.get("ref_crc32") else ""
        if col == 6:
            return entry["message"].replace("\n", " ")
        return None

    def refresh_all(self):
        if not self._indices:
            return
        left = self.index(0, 0)
        right = self.index(len(self._indices) - 1, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole])

    def entry_index(self, row: int) -> int | None:
        if 0 <= row < len(self._indices):
            return self._indices[row]
        return None

    def row_for_entry(self, entry_idx: int) -> int:
        try:
            return self._indices.index(entry_idx)
        except ValueError:
            return -1

    def refresh_entry(self, entry_idx: int):
        row = self.row_for_entry(entry_idx)
        if row < 0:
            return
        left = self.index(row, 0)
        right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole])


class _MessageInfoFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._needle = ""

    def set_filter_text(self, text: str):
        self._needle = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._needle:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        entry_idx = model.entry_index(source_row)
        if entry_idx is None:
            return True
        entry = model._entries[entry_idx]
        type_text = ui_text("ui_messageinfo_reference") if entry["is_ref"] == 1 else ui_text("ui_mainmodeparam_normal")
        string_ids = " ".join((
            _message_text_id(entry.get("message", "")),
            *model._id_map.resolve(entry["crc32_id"]),
        )).lower()
        haystack = " ".join((
            string_ids,
            f"{entry['crc32_id']:08x}",
            str(entry["char_id"]),
            _char_label(entry["char_id"]).lower(),
            str(entry["cue_id"]),
            f"{entry.get('ref_crc32', 0):08x}",
            type_text.lower(),
            entry["message"].lower(),
        ))
        return self._needle in haystack


class MessageInfoEditor(QWidget):
    _load_done_signal = pyqtSignal(str, object, int, object)
    _load_error_signal = pyqtSignal(str)
    _scan_done_signal = pyqtSignal(object, int)
    _scan_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        self._filepath: str | None = None
        self._original_data: bytearray | None = None
        self._version: int = 1001
        self._entries: list[dict] = []
        self._orig_entries: list[dict] = []
        self._id_map = MessageInfoIdMap()
        self._id_map.load()

        self._current_char_id = None
        self._char_buttons: list[tuple] = []      # (QPushButton, char_id)
        self._selected_entry_idx: int | None = None
        self._table_model: _MessageInfoTableModel | None = None
        self._proxy_model: _MessageInfoFilterProxy | None = None
        self._entries_table: QTableView | None = None
        self._loading_detail = False
        self._detail_widgets: list[QWidget] = []
        self._scan_running = False
        self._capture_active = False
        self._detail_columns = 0
        self._last_compact = None
        self._resize_rebuild_timer = QTimer(self)
        self._resize_rebuild_timer.setSingleShot(True)
        self._resize_rebuild_timer.setInterval(80)
        self._resize_rebuild_timer.timeout.connect(self._rebuild_current_scope_for_width)

        # Debounce for right-panel entry search
        self._entry_search_timer = QTimer(self)
        self._entry_search_timer.setSingleShot(True)
        self._entry_search_timer.setInterval(250)
        self._entry_search_timer.timeout.connect(self._do_entry_search)
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(6000)
        self._capture_timer.timeout.connect(self._scan_now)

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)
        self._scan_done_signal.connect(self._on_scan_done)
        self._scan_error_signal.connect(self._on_scan_error)

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        # Toolbar — identical structure to CharacterStatsEditor
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
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
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl, 1)

        self._process_combo = QComboBox()
        self._process_combo.setFixedHeight(TOOLBAR_BTN_H)
        self._process_combo.setFixedWidth(160)
        self._process_combo.setMinimumWidth(0)
        self._process_combo.setFont(QFont("Segoe UI", 9))
        self._process_combo.setStyleSheet(ss_input())
        self._process_combo.currentIndexChanged.connect(lambda _idx: self._update_capture_buttons())
        tl.addWidget(self._process_combo)

        self._btn_refresh_processes = QPushButton(ui_text("ui_messageinfo_refresh_processes"))
        self._btn_refresh_processes.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_refresh_processes.setFixedWidth(82)
        self._btn_refresh_processes.setFont(QFont("Segoe UI", 9))
        self._btn_refresh_processes.setStyleSheet(ss_btn())
        self._btn_refresh_processes.clicked.connect(self._refresh_processes)
        tl.addWidget(self._btn_refresh_processes)

        self._btn_scan_now = QPushButton(ui_text("ui_messageinfo_scan_now"))
        self._btn_scan_now.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_scan_now.setFixedWidth(92)
        self._btn_scan_now.setFont(QFont("Segoe UI", 9))
        self._btn_scan_now.setStyleSheet(ss_btn())
        self._btn_scan_now.clicked.connect(self._scan_now)
        tl.addWidget(self._btn_scan_now)

        self._btn_start_capture = QPushButton(ui_text("ui_messageinfo_start_capture"))
        self._btn_start_capture.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_start_capture.setFixedWidth(126)
        self._btn_start_capture.setFont(QFont("Segoe UI", 9))
        self._btn_start_capture.setStyleSheet(ss_btn(accent=True))
        self._btn_start_capture.clicked.connect(self._start_capture)
        tl.addWidget(self._btn_start_capture)

        self._btn_stop_capture = QPushButton(ui_text("ui_messageinfo_stop_capture"))
        self._btn_stop_capture.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_stop_capture.setFixedWidth(58)
        self._btn_stop_capture.setFont(QFont("Segoe UI", 9))
        self._btn_stop_capture.setStyleSheet(ss_btn())
        self._btn_stop_capture.clicked.connect(self._stop_capture)
        tl.addWidget(self._btn_stop_capture)

        self._capture_status = QLabel("")
        self._capture_status.setFont(QFont("Consolas", 10))
        self._capture_status.setMinimumWidth(0)
        self._capture_status.setMaximumWidth(190)
        self._capture_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._capture_status.setStyleSheet(ss_dim_label())
        tl.addWidget(self._capture_status)

        root.addWidget(top)
        self._refresh_processes()
        self._update_capture_buttons()
        self._update_capture_status()

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(276)
        list_frame.setStyleSheet(ss_sidebar_frame())
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(ui_text("ui_damageeff_search"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        # Action buttons — same layout as CharacterStatsEditor
        actions_frame = QWidget()
        actions_frame.setStyleSheet(ss_transparent())
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
        self._char_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._char_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._char_list_widget = QWidget()
        self._char_list_widget.setMinimumWidth(0)
        self._char_list_widget.setStyleSheet(ss_transparent())
        self._char_list_layout = QVBoxLayout(self._char_list_widget)
        self._char_list_layout.setContentsMargins(0, 0, 0, 0)
        self._char_list_layout.setSpacing(1)
        self._char_list_layout.addStretch()
        self._char_scroll.setWidget(self._char_list_widget)
        list_vlayout.addWidget(self._char_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        # Right panel container (header + virtualized table/detail editor)
        right_container = QWidget()
        right_container.setStyleSheet(ss_bg_dark())
        right_vlayout = QVBoxLayout(right_container)
        right_vlayout.setContentsMargins(0, 0, 0, 0)
        right_vlayout.setSpacing(0)

        # Persistent header: character title + entry search
        right_header = QFrame()
        right_header.setFixedHeight(46)
        right_header.setStyleSheet(ss_bg_panel())
        rh_layout = QHBoxLayout(right_header)
        rh_layout.setContentsMargins(16, 8, 12, 8)
        rh_layout.setSpacing(10)

        self._right_title_lbl = QLabel("")
        self._right_title_lbl.setMinimumWidth(0)
        self._right_title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._right_title_lbl.setStyleSheet(ss_main_label())
        rh_layout.addWidget(self._right_title_lbl, 1)

        self._entry_search = QLineEdit()
        self._entry_search.setPlaceholderText(ui_text("ui_messageinfo_search_entries"))
        self._entry_search.setFixedHeight(30)
        self._entry_search.setFixedWidth(220)
        self._entry_search.setFont(QFont("Segoe UI", 10))
        self._entry_search.setStyleSheet(ss_search())
        self._entry_search.textChanged.connect(lambda _: self._entry_search_timer.start())
        rh_layout.addWidget(self._entry_search)

        right_vlayout.addWidget(right_header)

        rh_sep = QFrame()
        rh_sep.setFixedHeight(1)
        rh_sep.setStyleSheet(ss_sep())
        right_vlayout.addWidget(rh_sep)

        self._editor_widget = QWidget()
        self._editor_widget.setMinimumWidth(0)
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._show_placeholder(ui_text("ui_messageinfo_open_a_messageinfo_bin_xfbin_file_to_begin_editing"))

        right_vlayout.addWidget(self._editor_widget, 1)
        main_layout.addWidget(right_container, 1)
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._entries_table = None
        self._table_model = None
        self._proxy_model = None
        self._detail_widgets = []
        title = ui_text("no_file_loaded") if self._filepath is None else ui_text("ui_model_viewer_select_item")
        card = make_empty_state(
            self._editor_widget,
            title=title,
            text=text,
            icon_name="fa6s.message",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _right_content_width(self) -> int:
        return max(0, self._editor_widget.viewport().width() if hasattr(self._editor_widget, "viewport") else self._editor_widget.width())

    def _is_compact_editor(self) -> bool:
        return self._right_content_width() < 760

    def _field_columns(self) -> int:
        width = self._right_content_width()
        if width < 580:
            return 1
        if width < 820:
            return 2
        if width < 1080:
            return 3
        return 6

    def _prep_card(self, card: QWidget, *, max_width: int = 1120):
        card.setMinimumWidth(0)
        card.setMaximumWidth(max_width)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def _prep_field_widget(self, widget: QWidget, min_width: int = 130):
        widget.setMinimumWidth(min_width)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _rebuild_current_scope_for_width(self):
        if self._current_char_id is None or not self._entries:
            return
        cols = self._field_columns()
        compact = self._is_compact_editor()
        if cols == self._detail_columns and compact == self._last_compact:
            return
        selected = self._selected_entry_idx
        self._build_entries_panel(self._current_char_id, select_idx=selected)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._entries and self._current_char_id is not None:
            self._resize_rebuild_timer.start()

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
        all_label = ui_text("ui_messageinfo_all_strings")
        if not s or s in all_label.lower():
            btn = self._make_char_button(_ALL_STRINGS, len(self._entries))
            self._char_list_layout.insertWidget(self._char_list_layout.count() - 1, btn)
            self._char_buttons.append((btn, _ALL_STRINGS))

        for char_id, indices in self._get_char_groups().items():
            if s:
                if s not in _char_label(char_id).lower() and s not in str(char_id):
                    continue

            btn = self._make_char_button(char_id, len(indices))
            self._char_list_layout.insertWidget(self._char_list_layout.count() - 1, btn)
            self._char_buttons.append((btn, char_id))

        self._update_char_button_styles()

    def _make_char_button(self, char_id, count: int) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(50)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=False))

        inner = QVBoxLayout(btn)
        inner.setContentsMargins(10, 5, 10, 5)
        inner.setSpacing(0)

        full_name = _scope_label(char_id)
        name_lbl = QLabel(_truncate(full_name, 25))
        name_lbl.setToolTip(full_name)
        name_lbl.setMinimumWidth(0)
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(name_lbl)

        count_lbl = QLabel(ui_text("ui_messageinfo_value_entries", p0=count))
        count_lbl.setFont(QFont("Consolas", 11))
        count_lbl.setStyleSheet(ss_dim_label())
        count_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(count_lbl)

        btn.clicked.connect(lambda checked=False, cid=char_id: self._select_char(cid))
        return btn

    def _update_char_button_styles(self):
        for btn, cid in self._char_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(cid == self._current_char_id)))

    def _filter_list(self):
        self._populate_char_list(self._search_entry.text())

    def _do_entry_search(self):
        """Filter the virtualized entry table without creating extra widgets."""
        if self._proxy_model is None:
            return
        self._proxy_model.set_filter_text(self._entry_search.text())
        self._select_first_visible_row()

    def _select_char(self, char_id):
        self._current_char_id = char_id
        self._selected_entry_idx = None
        self._dup_btn.setEnabled(char_id != _ALL_STRINGS)
        self._del_btn.setEnabled(char_id != _ALL_STRINGS)
        self._entry_search.clear()
        self._update_char_button_styles()
        self._build_entries_panel(char_id)

    # Virtualized entries panel (overrides the legacy paged-card renderer above)

    def _entry_indices_for_scope(self, scope) -> list[int]:
        if scope == _ALL_STRINGS:
            return list(range(len(self._entries)))
        return [i for i, entry in enumerate(self._entries) if entry["char_id"] == scope]

    def _build_entries_panel(self, scope, select_idx: int | None = None):
        _clear_layout(self._editor_layout)
        self._selected_entry_idx = None
        self._detail_widgets = []
        self._detail_columns = self._field_columns()
        self._last_compact = self._is_compact_editor()
        scope_title = _scope_label(scope)
        self._right_title_lbl.setText(scope_title)
        self._right_title_lbl.setToolTip(scope_title)

        indices = self._entry_indices_for_scope(scope)
        if not indices:
            self._show_empty_entries_message()
            return

        panel = QWidget()
        panel.setMinimumWidth(0)
        panel.setStyleSheet(ss_transparent())
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)

        self._table_model = _MessageInfoTableModel(self._entries, indices, self._id_map, self)
        self._proxy_model = _MessageInfoFilterProxy(self)
        self._proxy_model.setSourceModel(self._table_model)
        self._proxy_model.set_filter_text(self._entry_search.text())

        table_card, table_layout = make_editor_card(panel, margins=(12, 10, 12, 12), spacing=8)
        table_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table_card.setMinimumHeight(230)
        table_card.setMaximumWidth(1120)
        add_editor_card_title(
            table_layout,
            scope_title,
            "fa6s.table-list",
            ui_text("ui_messageinfo_value_entries", p0=len(indices)),
        )

        self._entries_table = QTableView(table_card)
        self._entries_table.setModel(self._proxy_model)
        self._entries_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._entries_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._entries_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._entries_table.setAlternatingRowColors(False)
        self._entries_table.setShowGrid(False)
        self._entries_table.setSortingEnabled(False)
        self._entries_table.verticalHeader().setVisible(False)
        self._entries_table.verticalHeader().setDefaultSectionSize(28)
        self._entries_table.horizontalHeader().setStretchLastSection(True)
        for col in range(6):
            self._entries_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._entries_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._entries_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._entries_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._entries_table.setMinimumHeight(150 if self._last_compact else 210)
        self._entries_table.setStyleSheet(ss_table())
        self._entries_table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        table_layout.addWidget(self._entries_table, 1)
        panel_layout.addWidget(table_card, 1)

        panel_layout.addWidget(self._make_detail_panel(panel), 0)
        self._editor_layout.addWidget(panel, 1)

        if select_idx is not None:
            self._select_entry_in_table(select_idx)
        else:
            self._select_first_visible_row()

    def _show_empty_entries_message(self):
        self._entries_table = None
        self._table_model = None
        self._proxy_model = None
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("ui_messageinfo_message"),
            text=ui_text("ui_messageinfo_no_entries_for_this_character"),
            icon_name="fa6s.message",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _make_detail_panel(self, parent=None) -> QFrame:
        detail, layout = make_editor_card(parent, margins=(14, 12, 14, 12), spacing=9)
        self._prep_card(detail)
        add_editor_card_title(layout, ui_text("ui_messageinfo_message"), "fa6s.message", ui_text("ui_messageinfo_string_id"))

        fields = QWidget(detail)
        fields.setMinimumWidth(0)
        fields.setStyleSheet(ss_transparent())
        fields_layout = QGridLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setHorizontalSpacing(10)
        fields_layout.setVerticalSpacing(6)

        cols = max(1, self._detail_columns or self._field_columns())

        def make_field(label_text: str, idx: int, read_only: bool = False) -> QLineEdit:
            box, box_layout, _label, _hint = make_editor_field_shell(
                label_text,
                label_font_size=10,
                spacing=2,
            )
            self._prep_field_widget(box)
            edit = QLineEdit(box)
            edit.setFixedHeight(28)
            edit.setFont(QFont("Consolas", 11))
            edit.setReadOnly(read_only)
            edit.setStyleSheet(ss_input())
            edit.setMinimumWidth(0)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            box_layout.addWidget(edit)
            row = idx // cols
            col = idx % cols
            fields_layout.addWidget(box, row, col)
            fields_layout.setColumnStretch(col, 1)
            self._detail_widgets.append(edit)
            return edit

        self._detail_string = make_field(ui_text("ui_messageinfo_string_id"), 0)
        self._detail_crc = make_field(ui_text("ui_messageinfo_crc32_id"), 1)
        self._detail_char = make_field(ui_text("ui_assist_char_id"), 2)
        self._detail_cue = make_field(ui_text("ui_messageinfo_cue_id"), 3)
        self._detail_type = make_field(ui_text("ui_dlcinfoparam_type"), 4, read_only=True)
        self._detail_ref = make_field(ui_text("ui_messageinfo_ref_crc32"), 5)
        layout.addWidget(fields)

        msg_lbl = QLabel(ui_text("ui_messageinfo_message"), detail)
        msg_lbl.setFont(QFont("Segoe UI", 10))
        msg_lbl.setStyleSheet(ss_field_label())
        layout.addWidget(msg_lbl)

        self._detail_message = QTextEdit(detail)
        self._detail_message.setFont(QFont("Segoe UI", 10))
        self._detail_message.setFixedHeight(104 if self._last_compact else 92)
        self._detail_message.setMinimumWidth(0)
        self._detail_message.setStyleSheet(ss_textedit())
        layout.addWidget(self._detail_message)
        self._detail_widgets.append(self._detail_message)

        btn_row = QWidget(detail)
        btn_row.setStyleSheet(ss_transparent())
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)

        self._detail_add_btn = QPushButton(ui_text("ui_messageinfo_add"), btn_row)
        self._detail_add_btn.setFixedHeight(26)
        self._detail_add_btn.setStyleSheet(ss_btn())
        self._detail_add_btn.clicked.connect(self._detail_add_entry)
        btn_layout.addWidget(self._detail_add_btn)

        self._detail_dup_btn = QPushButton(ui_text("btn_dup_short"), btn_row)
        self._detail_dup_btn.setFixedHeight(26)
        self._detail_dup_btn.setStyleSheet(ss_btn())
        self._detail_dup_btn.clicked.connect(self._detail_dup_entry)
        btn_layout.addWidget(self._detail_dup_btn)

        self._detail_del_btn = QPushButton(ui_text("btn_delete"), btn_row)
        self._detail_del_btn.setFixedHeight(26)
        self._detail_del_btn.setStyleSheet(ss_btn(danger=True))
        self._detail_del_btn.clicked.connect(self._detail_delete_entry)
        btn_layout.addWidget(self._detail_del_btn)

        btn_layout.addStretch()
        layout.addWidget(btn_row)
        self._detail_widgets.extend((self._detail_add_btn, self._detail_dup_btn, self._detail_del_btn))

        self._detail_string.editingFinished.connect(self._apply_detail_string_id)
        self._detail_crc.editingFinished.connect(self._apply_detail_fields)
        self._detail_char.editingFinished.connect(self._apply_detail_fields)
        self._detail_cue.editingFinished.connect(self._apply_detail_fields)
        self._detail_ref.editingFinished.connect(self._apply_detail_fields)
        self._detail_message.textChanged.connect(self._apply_detail_message)
        self._set_detail_enabled(False)
        return detail

    def _set_detail_enabled(self, enabled: bool):
        for widget in self._detail_widgets:
            widget.setEnabled(enabled)
        if not enabled and hasattr(self, "_detail_message"):
            self._loading_detail = True
            self._detail_string.clear()
            self._detail_crc.clear()
            self._detail_char.clear()
            self._detail_cue.clear()
            self._detail_type.clear()
            self._detail_ref.clear()
            self._detail_message.setPlainText(ui_text("ui_messageinfo_select_an_entry"))
            self._loading_detail = False

    def _on_table_selection_changed(self):
        if self._entries_table is None or self._proxy_model is None:
            return
        rows = self._entries_table.selectionModel().selectedRows()
        if not rows:
            self._selected_entry_idx = None
            self._set_detail_enabled(False)
            return
        source_index = self._proxy_model.mapToSource(rows[0])
        entry_idx = self._table_model.entry_index(source_index.row()) if self._table_model else None
        if entry_idx is None:
            self._selected_entry_idx = None
            self._set_detail_enabled(False)
            return
        self._load_detail(entry_idx)

    def _load_detail(self, entry_idx: int):
        entry = self._entries[entry_idx]
        self._selected_entry_idx = entry_idx
        self._loading_detail = True
        self._detail_string.setText(self._selected_entry_string_id(entry))
        self._detail_crc.setText(f"{entry['crc32_id']:08X}")
        self._detail_char.setText(str(entry["char_id"]))
        self._detail_cue.setText(str(entry["cue_id"]))
        self._detail_type.setText(
            ui_text("ui_messageinfo_reference") if entry["is_ref"] == 1 else ui_text("ui_mainmodeparam_normal")
        )
        self._detail_ref.setText(f"{entry['ref_crc32']:08X}" if entry.get("ref_crc32") else "00000000")
        self._detail_message.setPlainText(entry["message"])
        for edit in (
            self._detail_string, self._detail_crc, self._detail_char,
            self._detail_cue, self._detail_type, self._detail_ref,
        ):
            edit.setCursorPosition(0)
        self._loading_detail = False
        self._set_detail_enabled(True)

    def _select_first_visible_row(self):
        if self._entries_table is None or self._proxy_model is None:
            return
        if self._proxy_model.rowCount() <= 0:
            self._selected_entry_idx = None
            self._set_detail_enabled(False)
            return
        index = self._proxy_model.index(0, 0)
        self._entries_table.selectRow(0)
        self._entries_table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        self._on_table_selection_changed()

    def _select_entry_in_table(self, entry_idx: int):
        if self._entries_table is None or self._proxy_model is None or self._table_model is None:
            return
        source_row = self._table_model.row_for_entry(entry_idx)
        if source_row < 0:
            self._select_first_visible_row()
            return
        proxy_index = self._proxy_model.mapFromSource(self._table_model.index(source_row, 0))
        if not proxy_index.isValid():
            self._select_first_visible_row()
            return
        self._entries_table.selectRow(proxy_index.row())
        self._entries_table.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._on_table_selection_changed()

    def _refresh_entry_row(self, entry_idx: int):
        if self._table_model is not None:
            self._table_model.refresh_entry(entry_idx)

    def _primary_string_id(self, crc: int) -> str:
        values = self._id_map.resolve(crc)
        return values[0] if values else ""

    def _selected_entry_string_id(self, entry: dict) -> str:
        return _entry_string_id(entry, self._id_map)

    def _apply_detail_string_id(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return
        string_id = self._detail_string.text().strip()
        if not string_id:
            return
        idx = self._selected_entry_idx
        entry = self._entries[idx]
        crc, _changed = self._id_map.add_string(string_id)
        entry["crc32_id"] = crc
        if _message_text_id(entry.get("message", "")):
            entry["message"] = _TEXT_REF_RE.sub(f"<text {string_id}", entry["message"], count=1)
        self._loading_detail = True
        self._detail_crc.setText(f"{crc:08X}")
        self._detail_string.setText(self._selected_entry_string_id(entry))
        self._detail_message.setPlainText(entry["message"])
        self._loading_detail = False
        self._mark_dirty()
        self._refresh_id_map_views(selected_idx=idx)

    def _apply_detail_fields(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return
        idx = self._selected_entry_idx
        entry = self._entries[idx]
        old_char = entry["char_id"]
        try:
            entry["crc32_id"] = int(self._detail_crc.text().strip() or "0", 16) & 0xFFFFFFFF
            entry["char_id"] = int(self._detail_char.text().strip() or "0")
            entry["cue_id"] = int(self._detail_cue.text().strip() or "0")
            entry["ref_crc32"] = int(self._detail_ref.text().strip() or "0", 16) & 0xFFFFFFFF
        except ValueError:
            self._load_detail(idx)
            return
        self._loading_detail = True
        self._detail_string.setText(self._selected_entry_string_id(entry))
        self._loading_detail = False
        self._mark_dirty()
        self._refresh_entry_row(idx)
        if entry["char_id"] != old_char:
            self._populate_char_list(self._search_entry.text())

    def _apply_detail_message(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return
        idx = self._selected_entry_idx
        self._entries[idx]["message"] = self._detail_message.toPlainText()
        self._mark_dirty()
        self._refresh_entry_row(idx)

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
        if self._current_char_id is None or self._current_char_id == _ALL_STRINGS:
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
        if self._current_char_id is None or self._current_char_id == _ALL_STRINGS:
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

    def _detail_add_entry(self):
        if self._selected_entry_idx is None:
            return
        self._card_add_entry(self._selected_entry_idx)

    def _detail_dup_entry(self):
        if self._selected_entry_idx is None:
            return
        self._card_dup_entry(self._selected_entry_idx)

    def _detail_delete_entry(self):
        if self._selected_entry_idx is None:
            return
        self._card_delete_entry(self._selected_entry_idx)

    def _card_add_entry(self, after_idx: int):
        """Insert a new blank entry after the selected table row."""
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
        self._build_entries_panel(self._current_char_id, select_idx=insert_pos)

    def _card_dup_entry(self, entry_idx: int):
        """Duplicate the selected table row."""
        dup = copy.deepcopy(self._entries[entry_idx])
        insert_pos = entry_idx + 1
        self._entries.insert(insert_pos, dup)
        self._orig_entries.insert(insert_pos, copy.deepcopy(dup))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._build_entries_panel(self._current_char_id, select_idx=insert_pos)

    def _card_delete_entry(self, entry_idx: int):
        """Delete the selected table row."""
        char_id = self._entries[entry_idx]["char_id"]
        ans = QMessageBox.question(
            self, ui_text("ui_messageinfo_confirm"), ui_text("ui_messageinfo_delete_this_entry"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        next_select = entry_idx if entry_idx + 1 < len(self._entries) else entry_idx - 1
        del self._entries[entry_idx]
        if entry_idx < len(self._orig_entries):
            del self._orig_entries[entry_idx]

        self._selected_entry_idx = None
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())

        if not self._entries:
            self._current_char_id = None
            self._show_placeholder(ui_text("ui_messageinfo_select_a_character"))
            self._update_char_button_styles()
            return

        if self._current_char_id != _ALL_STRINGS and char_id not in self._get_char_groups():
            self._current_char_id = _ALL_STRINGS
            self._update_char_button_styles()
        if next_select >= len(self._entries):
            next_select = len(self._entries) - 1
        self._build_entries_panel(self._current_char_id, select_idx=max(0, next_select))

    # Live String ID capture

    def _refresh_processes(self):
        selected_pid = self._process_combo.currentData() if hasattr(self, "_process_combo") else None
        self._process_combo.blockSignals(True)
        self._process_combo.clear()
        self._process_combo.addItem(ui_text("ui_messageinfo_select_process"), None)
        processes = list_processes()
        if processes:
            for process in processes:
                self._process_combo.addItem(process.label, process.pid)
            if selected_pid is not None:
                index = self._process_combo.findData(selected_pid)
                if index >= 0:
                    self._process_combo.setCurrentIndex(index)
            else:
                for index, process in enumerate(processes, start=1):
                    if process.name.lower() == "asbr.exe":
                        self._process_combo.setCurrentIndex(index)
                        break
        else:
            self._process_combo.setItemText(0, ui_text("ui_messageinfo_no_processes"))
        self._process_combo.blockSignals(False)
        self._update_capture_buttons()

    def _selected_process_pid(self) -> int | None:
        pid = self._process_combo.currentData()
        try:
            return int(pid) if pid is not None else None
        except (TypeError, ValueError):
            return None

    def _start_capture(self):
        if self._selected_process_pid() is None:
            self._scan_error_signal.emit(ui_text("ui_messageinfo_select_process_first"))
            return
        self._capture_active = True
        self._capture_timer.start()
        self._update_capture_buttons()
        self._scan_now()

    def _stop_capture(self):
        self._capture_active = False
        self._capture_timer.stop()
        self._update_capture_buttons()
        self._update_capture_status()

    def _scan_now(self):
        if self._scan_running:
            return
        pid = self._selected_process_pid()
        if pid is None:
            self._scan_error_signal.emit(ui_text("ui_messageinfo_select_process_first"))
            return
        self._scan_running = True
        self._update_capture_buttons()
        self._capture_status.setText(ui_text("ui_messageinfo_capture_scanning"))

        def worker():
            try:
                result = scan_process_strings(pid)
                changed = self._id_map.merge_strings(result.strings)
            except Exception as exc:
                self._scan_error_signal.emit(str(exc))
                return
            self._scan_done_signal.emit(result, changed)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, result, changed: int):
        self._scan_running = False
        self._update_capture_buttons()
        self._refresh_id_map_views()
        self._capture_status.setText(
            ui_text(
                "ui_messageinfo_capture_done",
                p0=changed,
                p1=len(result.strings),
                p2=self._id_map.count(),
                p3=self._matched_entry_count(),
            )
        )

    def _on_scan_error(self, msg: str):
        self._scan_running = False
        self._capture_active = False
        self._capture_timer.stop()
        self._update_capture_buttons()
        self._update_capture_status(error=msg)
        QMessageBox.warning(self, ui_text("ui_messageinfo_capture_error"), msg)

    def _update_capture_buttons(self):
        pid_selected = self._selected_process_pid() is not None if hasattr(self, "_process_combo") else False
        self._btn_refresh_processes.setEnabled(not self._scan_running)
        self._btn_scan_now.setEnabled(pid_selected and not self._scan_running)
        self._btn_start_capture.setEnabled(pid_selected and not self._capture_active)
        self._btn_stop_capture.setEnabled(self._capture_active)

    def _update_capture_status(self, error: str = ""):
        if error:
            self._capture_status.setText(ui_text("ui_messageinfo_capture_error_short"))
            self._capture_status.setToolTip(error)
            return
        self._capture_status.setToolTip("")
        state = ui_text("ui_messageinfo_capture_active") if self._capture_active else ui_text("ui_messageinfo_capture_idle")
        self._capture_status.setText(
            ui_text(
                "ui_messageinfo_capture_status",
                p0=self._id_map.count(),
                p1=self._matched_entry_count(),
                p2=state,
            )
        )

    def _matched_entry_count(self) -> int:
        return sum(
            1
            for entry in self._entries
            if _message_text_id(entry.get("message", "")) or self._id_map.resolve(int(entry.get("crc32_id", 0)))
        )

    def _import_inline_text_ids(self) -> int:
        string_ids = {
            _message_text_id(entry.get("message", ""))
            for entry in self._entries
        }
        string_ids.discard("")
        return self._id_map.merge_strings(string_ids)

    def _refresh_id_map_views(self, selected_idx: int | None = None):
        if self._table_model is not None:
            self._table_model.refresh_all()
        if self._proxy_model is not None:
            self._proxy_model.set_filter_text(self._entry_search.text())
        if selected_idx is None:
            selected_idx = self._selected_entry_idx
        if selected_idx is not None and hasattr(self, "_detail_string") and 0 <= selected_idx < len(self._entries):
            entry = self._entries[selected_idx]
            if not self._detail_string.hasFocus():
                self._loading_detail = True
                self._detail_string.setText(self._selected_entry_string_id(entry))
                self._loading_detail = False
        self._update_capture_status()

    # Dirty state

    def _mark_dirty(self):
        self._btn_save.setEnabled(True)
        set_file_label(self._file_lbl, self._filepath, dirty=True)

    # File operations

    def _show_char_skeleton(self):
        _clear_layout(self._char_list_layout)
        self._char_buttons = []
        for _ in range(12):
            self._char_list_layout.addWidget(SkeletonListRow())
        self._char_list_layout.addStretch()

    def _show_editor_skeleton(self):
        _clear_layout(self._editor_layout)
        self._entries_table = None
        self._table_model = None
        self._proxy_model = None

        shell = QWidget()
        shell.setMinimumWidth(0)
        shell.setStyleSheet(ss_bg_dark())
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(12, 10, 12, 12)
        shell_layout.setSpacing(8)

        progress = QProgressBar(shell)
        progress.setRange(0, 0)
        progress.setFixedHeight(14)
        progress.setTextVisible(False)
        progress.setStyleSheet(ss_progressbar())
        shell_layout.addWidget(progress)

        table_shell, table_layout = make_editor_card(shell, margins=(12, 12, 12, 12), spacing=8)
        for _ in range(12):
            table_layout.addWidget(SkeletonBar(table_shell, height=18, corner_radius=4))
        shell_layout.addWidget(table_shell, 1)

        detail_shell, detail_layout = make_editor_card(shell, margins=(12, 12, 12, 12), spacing=8)
        detail_layout.addWidget(SkeletonBar(detail_shell, height=28, corner_radius=4))
        detail_layout.addWidget(SkeletonBar(detail_shell, height=92, corner_radius=4))
        shell_layout.addWidget(detail_shell)

        self._editor_layout.addWidget(shell, 1)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_messageinfo_open_messageinfo_bin_xfbin"), game_files_dialog_dir(target_patterns="messageInfo.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, filepath: str):
        create_backup_on_open(filepath)
        set_file_label_empty(self._file_lbl, ui_text("loading"))
        self._btn_open.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._dup_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._entry_search.clear()
        self._right_title_lbl.setText("")
        self._show_char_skeleton()
        self._show_editor_skeleton()

        def worker():
            try:
                data, version, entries = parse_messageinfo_xfbin(filepath)
            except Exception as exc:
                self._load_error_signal.emit(str(exc))
                return
            self._load_done_signal.emit(filepath, data, version, entries)

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_error(self, msg: str):
        self._btn_open.setEnabled(True)
        self._btn_save.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._dup_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._filepath = None
        self._original_data = None
        self._entries = []
        self._orig_entries = []
        self._current_char_id = None
        self._selected_entry_idx = None
        _clear_layout(self._char_list_layout)
        self._char_list_layout.addStretch()
        set_file_label_empty(self._file_lbl, ui_text("no_file_loaded"))
        self._show_placeholder(ui_text("ui_messageinfo_open_a_messageinfo_bin_xfbin_file_to_begin_editing"))
        QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=msg))

    def _on_load_done(self, filepath: str, data, version: int, entries):
        self._filepath = filepath
        self._original_data = data
        self._version = version
        self._entries = entries
        self._orig_entries = [dict(e) for e in entries]
        self._current_char_id = None
        self._selected_entry_idx = None
        self._import_inline_text_ids()

        self._btn_open.setEnabled(True)
        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._add_btn.setEnabled(True)

        self._populate_char_list()
        if self._entries:
            self._select_char(_ALL_STRINGS)
        else:
            self._show_placeholder(ui_text("ui_assist_no_entries_found"))
        self._update_capture_status()

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
        set_file_label(self._file_lbl, self._filepath)
