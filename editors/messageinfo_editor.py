"""editors/messageinfo_editor.py – Game Text Editor (messageInfo.bin.xfbin)."""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_empty_state,
    ss_bg_dark,
    ss_field_label,
    ss_dim_label,
    ss_error_label,
    ss_input_validation,
    ss_main_label,
    ss_progressbar,
    ss_sidebar_btn,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_field,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
    configure_table,
    configure_textedit,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import os
import copy
import re
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea, QTextEdit, QSizePolicy, QTableView, QAbstractItemView,
    QHeaderView, QProgressBar, QComboBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QSignalBlocker
from PyQt6.QtGui import QFont

from core.themes import P
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonBar, SkeletonListRow
from core.messageinfo_id_map import MessageInfoIdMap
from core.movelist_text import MoveListText
from parsers.messageinfo_parser import (
    parse_messageinfo_xfbin, save_messageinfo_xfbin, crc32_of,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


_CHAR_NAMES: dict[int, str] = {
    -1: "ui_messageinfo_system",
    1:  "ui_messageinfo_guide_characters",
    2:  "ui_messageinfo_unknown",
    3:  "char_0bao01",
    4:  "char_1dio01",
    5:  "char_1jnt01",
    6:  "char_1sdw01",
    7:  "char_1zpl01",
    8:  "char_2csr01",
    9:  "char_2esd01",
    10: "char_2jsp01",
    11: "char_2krs01",
    12: "char_2lsa01",
    13: "ui_messageinfo_wammu",
    14: "char_3abd01",
    15: "DIO",
    16: "char_3hhs01",
    17: "char_3igy01",
    18: "ui_messageinfo_old_joseph",
    19: "char_3jtr01",
    20: "char_3kki01",
    21: "char_3mra01",
    22: "char_3pln01",
    23: "char_3psp01",
    24: "ui_messageinfo_vanilla_ice",
    25: "ui_messageinfo_josuke_higashikata",
    26: "ui_messageinfo_jotaro_kujo_4",
    27: "char_4kir01",
    28: "char_4koi01",
    29: "char_4kwk01",
    30: "ui_messageinfo_okuyasu_nijumura",
    31: "char_4oti01",
    32: "char_4rhn01",
    33: "char_4sgc01",
    34: "char_4ykk01",
    35: "char_5bct01",
    36: "char_5dvl01",
    37: "ui_messageinfo_pannacota_fugo",
    38: "char_5gac01",
    39: "char_5grn01",
    40: "char_5mst01",
    41: "char_5nrc01",
    42: "ui_messageinfo_prosciutto_and_pesci",
    43: "ui_messageinfo_trish_uno",
    44: "char_6ans01",
    45: "char_6elm01",
    46: "char_6fit01",
    47: "ui_messageinfo_jolyne_kujo",
    48: "ui_messageinfo_enrico_pucci_white_snake",
    49: "char_7dio01",
    50: "char_7jir01",
    51: "char_7jny01",
    52: "char_7vtn01",
    53: "char_8jsk01",
    56: "ui_messageinfo_misc",
    57: "ui_messageinfo_misc",
    58: "char_6wet01",
    59: "char_6wet01",
    60: "ui_messageinfo_rissoto_nero",
    61: "ui_messageinfo_rissoto_nero",
    62: "ui_messageinfo_final_pucci",
    63: "ui_messageinfo_final_pucci",
    64: "char_2shm01",
    65: "char_2shm01",
    66: "ui_messageinfo_keicho_nijumura",
    67: "ui_messageinfo_keicho_nijumura",
    68: "ui_messageinfo_alternative_diego_brando",
    69: "ui_messageinfo_alternative_diego_brando",
    70: "char_5abc01",
    71: "char_5abc01",
    72: "char_4fgm01",
    73: "char_4fgm01",
    74: "char_8wou01",
    75: "char_8wou01",
}


_ALL_STRINGS = "__all_strings__"
_TEXT_REF_RE = re.compile(r"<text\s+([A-Za-z0-9_./:-]+)\b", re.IGNORECASE)


def _char_label(char_id: int) -> str:
    name = _CHAR_NAMES.get(char_id)
    return ("DIO" if name == "DIO" else ui_text(name)) if name else f"ID {char_id}"


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
    values = id_map.resolve(int(entry.get("crc32_id", 0)))
    return values[0] if len(values) == 1 else ""


def _entry_string_display(entry: dict, id_map: MessageInfoIdMap) -> str:
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
        "game_text_group",
        "ui_messageinfo_cue_id",
        "ui_dlcinfoparam_type",
        "ui_messageinfo_ref_crc32",
        "ui_messageinfo_message",
    )

    def __init__(self, entries: list[dict], indices: list[int], id_map: MessageInfoIdMap, parent=None):
        super().__init__(parent)
        self._entries = entries
        self._lookup = MoveListText()
        self._lookup_table = {row["crc32_id"]: row for row in entries}
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
        if role == Qt.ItemDataRole.ToolTipRole:
            crc = entry.get('ref_crc32', 0) if index.column() == 5 else entry['crc32_id']
            text = self._lookup._resolve(crc, self._lookup_table)
            return '\n'.join(filter(None, (*self._id_map.resolve(crc), text)))
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        col = index.column()
        if col == 0:
            return _entry_string_display(entry, self._id_map) or f"{entry['crc32_id']:08X}"
        if col == 1:
            return f"{entry['crc32_id']:08X}"
        if col == 2:
            return _char_label(entry["char_id"])
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
        self.setDynamicSortFilter(False)

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
        self._pending_string_ids = set()

        self._validation_error = False
        self._current_char_id = None
        self._char_buttons: list[tuple] = []      # (QPushButton, char_id)
        self._selected_entry_idx: int | None = None
        self._table_model: _MessageInfoTableModel | None = None
        self._proxy_model: _MessageInfoFilterProxy | None = None
        self._entries_table: QTableView | None = None
        self._loading_detail = False
        self._detail_widgets: list[QWidget] = []
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

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._on_save(target_path=path))
        install_editor_chrome(self)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        # Toolbar — identical structure to CharacterStatsEditor
        top = EditorToolbar()
        tl = top.content_layout

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        configure_button(self._btn_save, accent=True)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("ui_btladjprm_no_file_loaded"))

        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        configure_file_label(self._file_lbl)
        tl.addWidget(self._file_lbl, 1)

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar
        list_frame = EditorSidebar(width=276)


        list_vlayout = list_frame.content_layout


        self._search_entry = QLineEdit()
        configure_search(self._search_entry)
        self._search_entry.setToolTip(ui_text("game_text_group_search_hint"))
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        group_label = QLabel(ui_text("game_text_groups"))
        group_label.setFont(ui_font(TypeSize.LABEL))
        group_label.setStyleSheet(ss_field_label())
        list_vlayout.addWidget(group_label)

        # Actions here affect the entire group, rather than a selected message.
        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        self._add_btn = QPushButton(ui_text("ui_messageinfo_add"))
        self._add_btn.setEnabled(False)
        configure_button(self._add_btn, height=Size.COMPACT_CONTROL)
        self._add_btn.clicked.connect(self._on_add_entry)
        self._add_btn.setToolTip(ui_text("game_text_group_new_hint"))
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(ui_text("btn_dup_short"))
        self._dup_btn.setEnabled(False)
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.clicked.connect(self._on_dup_entry)
        self._dup_btn.setToolTip(ui_text("game_text_group_duplicate_hint"))
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(ui_text("btn_delete"))
        self._del_btn.setEnabled(False)
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.clicked.connect(self._on_delete_entry)
        self._del_btn.setToolTip(ui_text("game_text_group_delete_hint"))
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

        # Scrollable character list
        self._char_scroll = QScrollArea()


        self._char_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._char_scroll, transparent=True)
        self._char_list_widget = QWidget()
        self._char_list_widget.setMinimumWidth(0)
        self._char_list_widget.setStyleSheet(ss_transparent())
        self._char_list_layout = QVBoxLayout(self._char_list_widget)
        configure_layout(self._char_list_layout, LayoutRole.LIST)
        self._char_list_layout.addStretch()
        self._char_scroll.setWidget(self._char_list_widget)
        list_vlayout.addWidget(self._char_scroll)

        main_layout.addWidget(list_frame)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        # Right panel container (header + virtualized table/detail editor)
        right_container = QWidget()
        right_container.setStyleSheet(ss_bg_dark())
        right_vlayout = QVBoxLayout(right_container)
        configure_layout(right_vlayout, LayoutRole.ROOT)

        # Persistent header: character title + entry search
        right_header = QWidget()


        rh_layout = configure_layout(QHBoxLayout(right_header), LayoutRole.PAGE)


        self._right_title_lbl = QLabel("")
        self._right_title_lbl.setMinimumWidth(0)
        self._right_title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._right_title_lbl.setFont(ui_font(TypeSize.SUBHEADING, QFont.Weight.Bold))
        self._right_title_lbl.setStyleSheet(ss_main_label())
        rh_layout.addWidget(self._right_title_lbl, 1)

        self._entry_search = QLineEdit()
        configure_search(self._entry_search)
        self._entry_search.setMinimumWidth(100)
        self._entry_search.setMaximumWidth(280)
        self._entry_search.setToolTip(ui_text("game_text_search_hint"))
        self._entry_search.textChanged.connect(lambda _: self._entry_search_timer.start())
        rh_layout.addWidget(self._entry_search)

        right_vlayout.addWidget(right_header)

        rh_sep = EditorSeparator()


        right_vlayout.addWidget(rh_sep)

        self._editor_widget = QWidget()
        self._editor_widget.setMinimumWidth(0)
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
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
        if width < 420:
            return 1
        if width < 820:
            return 2
        if width < 1080:
            return 3
        return 6

    def _prep_card(self, card: QWidget, *, max_width: int = 16777215):
        configure_card(card, maximum_width=max_width, vertical_policy=QSizePolicy.Policy.Maximum)

    def _prep_field_widget(self, widget: QWidget, min_width: int = 130):
        configure_field(widget, minimum_width=min_width)

    def _rebuild_current_scope_for_width(self):
        # Reflow the existing controls: focus, invalid input and undo survive.
        if self._entries_table is None or not hasattr(self, '_detail_grid'):
            return
        self._configure_table_columns()
        cols = self._field_columns()
        if cols == self._detail_columns:
            return
        self._detail_columns = cols
        for i, box in enumerate(self._detail_boxes):
            self._detail_grid.removeWidget(box)
            self._detail_grid.addWidget(box, i // cols, i % cols)
        for col in range(6):
            self._detail_grid.setColumnStretch(col, int(col < cols))

    def _configure_table_columns(self):
        compact = self._is_compact_editor()
        if self._entries_table.property('compactColumns') == compact:
            return
        self._entries_table.setProperty('compactColumns', compact)
        self._entries_table.setColumnHidden(2, compact)
        self._entries_table.horizontalHeader().resizeSection(0, 170 if compact else 240)

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
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        inner = btn.content_layout


        full_name = _scope_label(char_id)
        name_lbl = btn.add_title(full_name)
        btn.add_subtitle("" if char_id == _ALL_STRINGS else f"ID {char_id}")
        name_lbl.setToolTip(full_name)


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
        if not self._commit_detail():
            return
        selected = self._selected_entry_idx
        self._proxy_model.set_filter_text(self._entry_search.text())
        self._select_entry_in_table(selected) if selected is not None else self._select_first_visible_row()

    def _select_char(self, char_id):
        if not self._commit_detail():
            return
        self._current_char_id = char_id
        self._selected_entry_idx = None
        self._dup_btn.setEnabled(char_id != _ALL_STRINGS)
        self._del_btn.setEnabled(char_id != _ALL_STRINGS)
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
        configure_layout(panel_layout, LayoutRole.TITLE)

        if self._table_model is not None:
            self._table_model.deleteLater()
        if self._proxy_model is not None:
            self._proxy_model.deleteLater()
        self._table_model = _MessageInfoTableModel(self._entries, indices, self._id_map, self)
        self._proxy_model = _MessageInfoFilterProxy(self)
        self._proxy_model.setSourceModel(self._table_model)
        self._proxy_model.set_filter_text(self._entry_search.text())

        table_card, table_layout = make_editor_card(panel)
        table_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table_card.setMinimumHeight(230)
        table_card.setMaximumWidth(16777215)
        add_editor_card_title(
            table_layout,
            ui_text("game_text_strings"),
            "fa6s.table-list",
            None,
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
        self._entries_table.verticalHeader().setDefaultSectionSize(Size.TABLE_ROW)
        self._entries_table.horizontalHeader().setStretchLastSection(True)
        header = self._entries_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 240)
        header.resizeSection(2, 140)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for col in (1, 3, 4, 5):
            self._entries_table.setColumnHidden(col, True)
        self._entries_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._entries_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._entries_table.setMinimumHeight(150 if self._last_compact else 210)
        configure_table(self._entries_table)
        self._configure_table_columns()
        self._entries_table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        table_layout.addWidget(self._entries_table, 1)
        panel_layout.addWidget(table_card, 1)

        detail_scroll = configure_scrollarea(QScrollArea(panel), transparent=True)
        detail_scroll.setMinimumHeight(220)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_scroll.setWidget(self._make_detail_panel(panel))
        panel_layout.addWidget(detail_scroll, 2)
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
        detail, layout = make_editor_card(parent)
        self._prep_card(detail)
        add_editor_card_title(layout, ui_text("ui_messageinfo_message"), "fa6s.message", ui_text("game_text_edit_hint"))

        fields = QWidget(detail)
        fields.setMinimumWidth(0)
        fields.setStyleSheet(ss_transparent())
        fields_layout = QGridLayout(fields)
        configure_layout(fields_layout, LayoutRole.GRID)
        self._detail_grid = fields_layout
        self._detail_boxes = []

        cols = max(1, self._detail_columns or self._field_columns())

        def make_field(label_text: str, idx: int, read_only: bool = False) -> QLineEdit:
            box, box_layout, _label, _hint = make_editor_field_shell(label_text)
            self._prep_field_widget(box)
            edit = QLineEdit(box)
            edit.setReadOnly(read_only)
            configure_input(edit, monospace=True)
            edit.setMinimumWidth(0)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            box_layout.addWidget(edit)
            row = idx // cols
            col = idx % cols
            fields_layout.addWidget(box, row, col)
            fields_layout.setColumnStretch(col, 1)
            edit.setAccessibleName(label_text)
            self._detail_boxes.append(box)
            self._detail_widgets.append(edit)
            return edit

        self._detail_string = make_field(ui_text("ui_messageinfo_string_id"), 0)
        self._detail_string.setPlaceholderText(ui_text('game_text_unknown_id'))
        self._detail_crc = make_field(ui_text("ui_messageinfo_crc32_id"), 1)
        self._detail_crc.setProperty('messageCRC32', True)
        self._detail_char = make_field(ui_text("game_text_group_id"), 2)
        self._detail_cue = make_field(ui_text("game_text_cue"), 3)
        self._detail_type = make_field(ui_text("ui_dlcinfoparam_type"), 4, read_only=True)
        self._detail_ref = make_field(ui_text("ui_messageinfo_ref_crc32"), 5)
        self._detail_ref.setProperty('messageCRC32', True)
        for key, edit in self._detail_edits().items():
            edit.setToolTip(ui_text('game_text_' + key + '_hint'))
        layout.addWidget(fields)
        self._detail_error = QLabel(detail)
        self._detail_error.setFont(ui_font(TypeSize.BODY))
        self._detail_error.setStyleSheet(ss_error_label())
        self._detail_error.setWordWrap(True)
        self._detail_error.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_error.hide()
        layout.addWidget(self._detail_error)

        msg_lbl = QLabel(ui_text("ui_messageinfo_message"), detail)
        msg_lbl.setFont(ui_font(TypeSize.LABEL))
        msg_lbl.setStyleSheet(ss_field_label())
        layout.addWidget(msg_lbl)

        self._detail_message = QTextEdit(detail)
        self._detail_message.setFixedHeight(110)
        self._detail_message.setAcceptRichText(False)
        self._detail_message.setAccessibleName(ui_text("ui_messageinfo_message"))
        self._detail_message.setToolTip(ui_text("game_text_message_hint"))
        self._detail_message.setMinimumWidth(0)
        configure_textedit(self._detail_message)
        layout.addWidget(self._detail_message)
        self._detail_widgets.append(self._detail_message)
        preview_header = QWidget(detail)
        preview_header_layout = configure_layout(QHBoxLayout(preview_header), LayoutRole.FIELD)
        preview_label = QLabel(ui_text('game_text_preview'), preview_header)
        preview_label.setFont(ui_font(TypeSize.LABEL))
        preview_label.setStyleSheet(ss_field_label())
        preview_label.setWordWrap(True)
        preview_header_layout.addWidget(preview_label, 1)
        self._jump_ref_btn = configure_button(
            QPushButton(ui_text('game_text_jump_reference'), preview_header), height=Size.COMPACT_CONTROL)
        self._jump_ref_btn.clicked.connect(self._jump_reference)
        preview_header_layout.addWidget(self._jump_ref_btn)
        layout.addWidget(preview_header)
        self._detail_preview = QLabel(detail)
        self._detail_preview.setFont(ui_font(TypeSize.BODY))
        self._detail_preview.setStyleSheet(ss_main_label())
        self._detail_preview.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail_preview.setWordWrap(True)
        layout.addWidget(self._detail_preview)

        btn_row = QWidget(detail)
        btn_row.setStyleSheet(ss_transparent())
        btn_layout = QHBoxLayout(btn_row)
        configure_layout(btn_layout, LayoutRole.FIELD)

        self._detail_add_btn = QPushButton(ui_text("ui_messageinfo_add"), btn_row)
        configure_button(self._detail_add_btn, height=Size.COMPACT_CONTROL)
        self._detail_add_btn.clicked.connect(self._detail_add_entry)
        self._detail_add_btn.setProperty("designAction", "new")
        self._detail_add_btn.setToolTip(ui_text("game_text_entry_new_hint"))
        btn_layout.addWidget(self._detail_add_btn)

        self._detail_dup_btn = QPushButton(ui_text("btn_dup_short"), btn_row)
        configure_button(self._detail_dup_btn, height=Size.COMPACT_CONTROL)
        self._detail_dup_btn.clicked.connect(self._detail_dup_entry)
        self._detail_dup_btn.setProperty("designAction", "duplicate")
        self._detail_dup_btn.setToolTip(ui_text("game_text_entry_duplicate_hint"))
        btn_layout.addWidget(self._detail_dup_btn)

        self._detail_del_btn = QPushButton(ui_text("btn_delete"), btn_row)
        configure_button(self._detail_del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._detail_del_btn.clicked.connect(self._detail_delete_entry)
        self._detail_del_btn.setProperty("designAction", "delete")
        self._detail_del_btn.setToolTip(ui_text("game_text_entry_delete_hint"))
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
        self._detail_add_btn.setEnabled(self._original_data is not None)
        self._jump_ref_btn.setEnabled(enabled and self._reference_index() is not None)
        self._detail_ref.setEnabled(enabled and self._selected_entry_idx is not None
                                    and self._entries[self._selected_entry_idx]['is_ref'] == 1)
        if not enabled and hasattr(self, "_detail_message"):
            self._loading_detail = True
            self._detail_string.clear()
            self._detail_crc.clear()
            self._detail_char.clear()
            self._detail_cue.clear()
            self._detail_type.clear()
            self._detail_ref.clear()
            self._detail_message.clear()
            self._detail_preview.setText(ui_text("game_text_no_selection"))
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
        if entry_idx != self._selected_entry_idx and not self._commit_detail():
            with QSignalBlocker(self._entries_table.selectionModel()):
                row = self._table_model.row_for_entry(self._selected_entry_idx)
                previous = self._proxy_model.mapFromSource(self._table_model.index(row, 0))
                self._entries_table.selectRow(previous.row())
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
        self._show_detail_error("")
        self._refresh_preview()

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

    def _refresh_entry_row(self, entry_idx: int):
        if self._table_model is not None:
            self._table_model._lookup_table = {e["crc32_id"]: e for e in self._entries}
            self._table_model.refresh_entry(entry_idx)

    def _primary_string_id(self, crc: int) -> str:
        values = self._id_map.resolve(crc)
        return values[0] if values else ""

    def _selected_entry_string_id(self, entry: dict) -> str:
        return _entry_string_id(entry, self._id_map)

    def _detail_edits(self):
        return dict(string=self._detail_string, crc=self._detail_crc, char=self._detail_char,
                    cue=self._detail_cue, ref=self._detail_ref)

    def _show_detail_error(self, text, edit=None):
        self._validation_error = bool(text)
        self._detail_error.setText(text)
        self._detail_error.setVisible(bool(text))
        for control in self._detail_edits().values():
            control.setStyleSheet(ss_input_validation(control is edit))
        if edit is not None:
            edit.setFocus()

    def _commit_detail(self):
        if self._selected_entry_idx is None or self._entries_table is None or self._loading_detail:
            return True
        return self._apply_detail_string_id() and self._apply_detail_fields()

    def _apply_detail_string_id(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return True
        value = self._detail_string.text().strip()
        entry = self._entries[self._selected_entry_idx]
        if not value or value == self._selected_entry_string_id(entry):
            return True
        if not re.fullmatch(r'[A-Za-z0-9_./:-]+', value):
            self._show_detail_error(ui_text('game_text_invalid_string'), self._detail_string)
            return False
        crc = crc32_of(value)
        if any(i != self._selected_entry_idx and e['crc32_id'] == crc for i, e in enumerate(self._entries)):
            self._show_detail_error(ui_text('game_text_duplicate_crc'), self._detail_string)
            return False
        # A text tag is a reference in the message, never the identity of this row.
        self._id_map.add_string(value, save=False)
        self._pending_string_ids.add(value)
        entry['crc32_id'] = crc
        self._detail_crc.setText(f'{crc:08X}')
        self._show_detail_error('')
        self._mark_dirty()
        self._refresh_entry_row(self._selected_entry_idx)
        return True

    def _apply_detail_fields(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return True
        idx = self._selected_entry_idx
        entry = self._entries[idx]
        values = {}
        for key, edit, base, low, high in (
            ('crc32_id', self._detail_crc, 16, 0, 0xFFFFFFFF),
            ('char_id', self._detail_char, 10, -32768, 32767),
            ('cue_id', self._detail_cue, 10, -32768, 32767),
            ('ref_crc32', self._detail_ref, 16, 0, 0xFFFFFFFF),
        ):
            try:
                value = int(edit.text().strip(), base)
                if not low <= value <= high:
                    raise ValueError()
                if key == 'crc32_id' and value != entry[key] and any(
                        i != idx and e[key] == value for i, e in enumerate(self._entries)):
                    self._show_detail_error(ui_text('game_text_duplicate_crc'), edit)
                    return False
                values[key] = value
            except ValueError:
                self._show_detail_error(ui_text('game_text_invalid_hex' if base == 16 else 'game_text_invalid_int'), edit)
                return False
        changed = any(entry[k] != v for k, v in values.items())
        old_char = entry['char_id']
        entry.update(values)
        self._loading_detail = True
        self._detail_string.setText(self._selected_entry_string_id(entry))
        self._loading_detail = False
        self._show_detail_error('')
        if changed:
            self._mark_dirty()
            self._refresh_entry_row(idx)
            if entry['char_id'] != old_char:
                self._current_char_id = _ALL_STRINGS
                self._populate_char_list(self._search_entry.text())
                QTimer.singleShot(0, lambda: self._build_entries_panel(_ALL_STRINGS, select_idx=idx))
        self._refresh_preview()
        return True

    def _reference_index(self):
        if self._selected_entry_idx is None:
            return None
        entry = self._entries[self._selected_entry_idx]
        crc = entry.get('ref_crc32') if entry['is_ref'] == 1 else None
        matches = [i for i, e in enumerate(self._entries) if e['crc32_id'] == crc]
        return matches[0] if len(matches) == 1 else None

    def _jump_reference(self):
        if not self._commit_detail():
            return
        target = self._reference_index()
        if target is None:
            return
        self._entry_search.clear()
        self._current_char_id = _ALL_STRINGS
        self._update_char_button_styles()
        self._build_entries_panel(_ALL_STRINGS, select_idx=target)

    def _refresh_preview(self):
        if self._selected_entry_idx is None or self._table_model is None:
            return
        entry = self._entries[self._selected_entry_idx]
        text = self._table_model._lookup._resolve(entry['crc32_id'], self._table_model._lookup_table)
        self._detail_preview.setText(text or ui_text('game_text_preview_unresolved'))
        self._jump_ref_btn.setEnabled(self._reference_index() is not None)

    def _apply_detail_message(self):
        if self._loading_detail or self._selected_entry_idx is None:
            return
        idx = self._selected_entry_idx
        value = self._detail_message.toPlainText()
        if value == self._entries[idx]['message']:
            return
        self._entries[idx]['message'] = value
        self._mark_dirty()
        self._refresh_entry_row(idx)
        self._refresh_preview()

    # Left panel CRUD (operates on character groups)

    def _next_free_crc(self):
        existing = {e['crc32_id'] for e in self._entries}
        value = 1
        while value in existing:
            value += 1
        return value

    def _next_free_char_id(self) -> int:
        existing = {e["char_id"] for e in self._entries}
        cid = 0
        while cid in existing:
            cid += 1
        return cid

    def _on_add_entry(self):
        if not self._commit_detail():
            return
        """Add a new character group to the left panel."""
        new_id = self._next_free_char_id()
        self._entry_search.clear()
        self._search_entry.clear()
        new_entry = {
            "crc32_id": self._next_free_crc(),
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
        if not self._commit_detail():
            return
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
            dup["crc32_id"] = self._next_free_crc()
            self._entries.append(dup)
            self._orig_entries.append(dict(dup))
        self._mark_dirty()
        self._populate_char_list(self._search_entry.text())
        self._select_char(new_id)

    def _on_delete_entry(self):
        if not self._commit_detail():
            return
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
        if not self._commit_detail():
            return
        self._entry_search.clear()
        if self._selected_entry_idx is None:
            indices = self._entry_indices_for_scope(self._current_char_id)
            if indices:
                self._card_add_entry(indices[0])
            else:
                self._on_add_entry()
            return
        self._card_add_entry(self._selected_entry_idx)

    def _detail_dup_entry(self):
        if not self._commit_detail():
            return
        if self._selected_entry_idx is None:
            return
        self._entry_search.clear()
        self._card_dup_entry(self._selected_entry_idx)

    def _detail_delete_entry(self):
        if not self._commit_detail():
            return
        if self._selected_entry_idx is None:
            return
        self._card_delete_entry(self._selected_entry_idx)

    def _card_add_entry(self, after_idx: int):
        """Insert a new blank entry after the selected table row."""
        char_id = self._entries[after_idx]["char_id"]
        new_entry = {
            "crc32_id": self._next_free_crc(),
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
        dup["crc32_id"] = self._next_free_crc()
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
        configure_layout(shell_layout, LayoutRole.PAGE)

        progress = QProgressBar(shell)
        progress.setRange(0, 0)
        progress.setFixedHeight(14)
        progress.setTextVisible(False)
        progress.setStyleSheet(ss_progressbar())
        shell_layout.addWidget(progress)

        table_shell, table_layout = make_editor_card(shell)
        for _ in range(12):
            table_layout.addWidget(SkeletonBar(table_shell, height=18, corner_radius=4))
        shell_layout.addWidget(table_shell, 1)

        detail_shell, detail_layout = make_editor_card(shell)
        detail_layout.addWidget(SkeletonBar(detail_shell, height=28, corner_radius=4))
        detail_layout.addWidget(SkeletonBar(detail_shell, height=92, corner_radius=4))
        shell_layout.addWidget(detail_shell)

        self._editor_layout.addWidget(shell, 1)

    def _on_open(self):
        if not self._commit_detail():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_messageinfo_open_messageinfo_bin_xfbin"), game_files_dialog_dir(target_patterns="messageInfo.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, filepath: str):
        if not self._commit_detail():
            return
        create_backup_on_open(filepath)
        self._load_was_dirty = self._entries != self._orig_entries
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
        if self._original_data is not None:
            self._btn_save.setEnabled(True)
            self._add_btn.setEnabled(True)
            set_file_label(self._file_lbl, self._filepath, dirty=getattr(self, '_load_was_dirty', False))
            self._populate_char_list(self._search_entry.text())
            scope = self._current_char_id if self._current_char_id is not None else _ALL_STRINGS
            self._build_entries_panel(scope)
            self._dup_btn.setEnabled(scope != _ALL_STRINGS)
            self._del_btn.setEnabled(scope != _ALL_STRINGS)
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=msg))
            return
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
        self._pending_string_ids.clear()
        self._current_char_id = None
        self._selected_entry_idx = None
        # Reading a document must not rewrite the shared ID catalog.

        self._btn_open.setEnabled(True)
        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._add_btn.setEnabled(True)

        self._entry_search.clear()
        self._search_entry.clear()
        self._populate_char_list()
        if self._entries:
            self._select_char(_ALL_STRINGS)
        else:
            self._show_placeholder(ui_text("ui_assist_no_entries_found"))

    def _on_save(self, target_path=None):
        if not self._commit_detail():
            return False
        save_path = str(target_path or editor_path(self))
        if not save_path or self._original_data is None:
            return
        try:
            save_messageinfo_xfbin(save_path, self._original_data, self._version, self._entries)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_assist_save_error'), ui_text('ui_assist_failed_to_save_value', p0=exc))
            return
        self._orig_entries = [dict(e) for e in self._entries]
        commit_save_path(self, save_path)
        set_file_label(self._file_lbl, save_path)
        if self._pending_string_ids:
            try:
                # Merge with changes made by other editors since this one opened.
                catalog = MessageInfoIdMap(self._id_map.path)
                catalog.load()
                catalog.merge_strings(self._pending_string_ids)
                self._id_map.ids = catalog.ids
                self._pending_string_ids.clear()
            except OSError as exc:
                QMessageBox.warning(self, ui_text('dlg_title_error'),
                                    ui_text('game_text_catalog_save_error', p0=exc))
        return True
