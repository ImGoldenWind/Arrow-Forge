from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
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
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.editor_file_state import set_file_label
from parsers.dlcinfoparam_parser import (
    parse_dlcinfoparam_xfbin,
    save_dlcinfoparam_xfbin,
    make_default_entry,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


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
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


class DlcInfoParamEditor(QWidget):
    """Embedded editor for DlcInfoParam.bin.xfbin."""

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
        self._last_compact: bool | None = None

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key, fallback):
        value = self._t(key)
        return fallback if value == key else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        top = EditorToolbar()
        tl = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._do_save)
        tl.addWidget(self._btn_save)

        self._lbl_file = QLabel(self._tr("no_file_loaded", ui_text("cpk_no_file")))

        configure_file_label(self._lbl_file)
        tl.addWidget(self._lbl_file)
        tl.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main_l = QHBoxLayout(main)
        configure_layout(main_l, LayoutRole.ROOT)

        sidebar = EditorSidebar()


        sl = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._on_filter_changed)
        sl.addWidget(self._search)

        actions = EditorActionRow()

        al = actions.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._btn_add = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        al.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._do_dup)
        self._btn_dup.setProperty("designAction", 'duplicate')
        al.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._do_del)
        self._btn_del.setProperty("designAction", 'delete')
        al.addWidget(self._btn_del, 1)

        sl.addWidget(actions)

        self._list_scroll = QScrollArea()


        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._list_scroll, transparent=True)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        configure_layout(self._list_layout, LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        sl.addWidget(self._list_scroll, 1)
        main_l.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_l.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_l.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_dlcinfoparam_open_a_dlcinfoparam_xfbin_file_to_begin_editing"))
        root.addWidget(main, 1)

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _clear_entry_list(self):
        _clear_layout(self._list_layout)
        self._list_layout.addStretch()

    def _visible_indices(self):
        text = self._filter_text.lower().strip()
        result = []
        for i, e in enumerate(self._entries):
            haystack = " ".join((
                e.get("type_str", ""),
                e.get("name", ""),
                e.get("code", ""),
                str(e.get("index", "")),
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
            self._show_placeholder(ui_text("ui_dlcinfoparam_select_a_dlc_entry_to_edit"))

    def _make_entry_button(self, idx):
        e = self._entries[idx]
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        bl = btn.content_layout


        title_text = ui_text("ui_customcardparam_entry_value_2", p0=idx)
        title = btn.add_title(_truncate(title_text, 24))


        title.setToolTip(title_text)


        subtitle_text = ui_text("ui_customcardparam_value_value", p0=e.get('type_str', ''), p1=e.get('dlc_id', ''))
        subtitle = btn.add_subtitle(_truncate(subtitle_text, 28))


        subtitle.setToolTip(subtitle_text)


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

    def _prep_card(self, card: QFrame):
        configure_card(card)
        return card

    def _prep_field_widget(self, widget: QWidget):
        configure_field(widget)
        return widget

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _field_position(self, row: int, col: int, max_columns: int) -> tuple[int, int]:
        columns = self._grid_columns(max_columns)
        logical_index = row * max_columns + col
        return divmod(logical_index, columns)

    def _build_editor(self, idx):
        self._loading_detail = True
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._last_compact = self._is_compact_editor()
        e = self._entries[idx]

        hdr, grid = make_editor_grid_card(self._editor_widget, title=ui_text('ui_customcardparam_entry_value', p0=idx), icon_name='fa6s.box-open', subtitle=ui_text('ui_customcardparam_value_value', p0=e.get('type_str', ''), p1=e.get('dlc_id', '')))
        self._prep_card(hdr)
        self._active_grid_columns = 3
        self._add_field(grid, 0, 0, "type_str", ui_text("ui_dlcinfoparam_type"), e.get("type_str", ""), wide=True)
        self._add_field(grid, 0, 1, "dlc_id", ui_text("ui_charviewer_dlc_id"), e.get("dlc_id", 0))
        self._add_field(grid, 0, 2, "index", ui_text("ui_dictionaryparam_index"), e.get("index", 0))
        self._add_editor_card(hdr)

        self._add_section(ui_text("ui_dictionaryparam_identifiers"))
        self._add_card_grid([
            ("name", ui_text("skill_field_name"), e.get("name", "")),
            ("code", ui_text("ui_dlcinfoparam_code"), e.get("code", "")),
        ], columns=2)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_index is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_index is None or self._loading_detail:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._build_editor(self._current_index)

    def _add_section(self, title):
        self._pending_section_title = title

    def _add_card_grid(self, fields, columns=3):
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
        self._prep_card(card)

        self._active_grid_columns = columns
        for i, (key, label, value) in enumerate(fields):
            row, col = divmod(i, columns)
            self._add_field(grid, row, col, key, label, value)

        self._add_editor_card(card)

    def _add_field(self, grid, row, col, key, label, value, wide=False):
        f, fl, _label, _hint = make_editor_field_shell(label)
        self._prep_field_widget(f)

        le = QLineEdit()
        text = str(value)
        le.setText(text)
        le.setCursorPosition(next((i for i, ch in enumerate(text) if ch.isprintable() and ord(ch) >= 32 and ch not in {"\u25a1", "\ufffd"}), 0))
        configure_input(le, height=Size.CONTROL if not wide else Size.LARGE_CONTROL, monospace=True)
        le.setMinimumWidth(0)
        le.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        le.textChanged.connect(lambda text, k=key: self._on_field_changed(k, text))
        fl.addWidget(le)

        mapped_row, mapped_col = self._field_position(row, col, getattr(self, "_active_grid_columns", 3))
        grid.addWidget(f, mapped_row, mapped_col)
        grid.setColumnStretch(mapped_col, 1)
        self._fields[key] = le

    def _on_field_changed(self, key, text):
        if self._loading_detail or self._current_index is None:
            return
        e = self._entries[self._current_index]
        try:
            if key in {"index", "dlc_id"}:
                e[key] = int(text.strip() or "0")
            else:
                e[key] = text.strip()
        except ValueError:
            return

        self._mark_dirty()
        if key in {"type_str", "dlc_id"}:
            self._refresh_current_button()

    def _refresh_current_button(self):
        if self._current_index is None:
            return
        e = self._entries[self._current_index]
        for btn, i in self._entry_buttons:
            if i == self._current_index:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    title = ui_text("ui_customcardparam_entry_value_2", p0=i)
                    subtitle = ui_text("ui_customcardparam_value_value", p0=e.get('type_str', ''), p1=e.get('dlc_id', ''))
                    labels[0].setText(_truncate(title, 24))
                    labels[0].setToolTip(title)
                    labels[1].setText(_truncate(subtitle, 28))
                    labels[1].setToolTip(subtitle)
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
            self, ui_text("ui_dlcinfoparam_open_dlcinfoparam"),
            game_files_dialog_dir(os.path.expanduser("~"), ("DlcInfoParam.xfbin", "DlcInfoParam.bin.xfbin")),
            "XFBIN files (*.xfbin);;All files (*)",
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_dlcinfoparam_xfbin(path)
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

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None:
            return
        try:
            save_dlcinfoparam_xfbin(save_path, self._raw_data, self._version, self._entries)
            with open(save_path, 'rb') as fh:
                self._raw_data = bytearray(fh.read())
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._lbl_file, save_path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_customizedefaultparam_save_failed'), str(exc))

    def _do_add(self):
        if self._raw_data is None:
            return
        self._entries.append(make_default_entry())
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
            ui_text("ui_dlcinfoparam_delete_entry_value_value_value", p0=self._current_index, p1=e.get('type_str', ''), p2=e.get('name', '')),
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
