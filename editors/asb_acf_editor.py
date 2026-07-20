import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
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
    ss_accent_sep,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_dim_label,
    ss_editor_card,
    ss_field_label,
    ss_file_label,
    ss_input,
    ss_main_label,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_section_label,
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_transparent,
)
from core.translations import ui_text
from parsers.asb_acf_parser import (
    DT_VLDATA,
    ST_PERROW,
    AcfBlob,
    AcfColumn,
    AcfUtfTable,
    make_default_row,
    parse_asb_acf,
    save_asb_acf,
    validate_cell_value,
)


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


def _blob_to_hex(blob: AcfBlob) -> str:
    return " ".join(f"{byte:02X}" for byte in blob.data)


class AsbAcfEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._root: AcfUtfTable | None = None
        self._tables: list[AcfUtfTable] = []
        self._table_buttons: list[tuple[QPushButton, int]] = []
        self._row_cards: list[tuple[QFrame, int]] = []
        self._fields: dict[QLineEdit, tuple[AcfUtfTable, int, AcfColumn]] = {}
        self._current_table_idx: int | None = None
        self._current_row_idx: int | None = None
        self._dirty = False
        self._loading_detail = False

        self._build_ui()

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

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

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))
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
        sidebar.setFixedWidth(290)
        sidebar.setStyleSheet(ss_sidebar_frame())
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 4)
        sidebar_layout.setSpacing(4)

        title = QLabel(ui_text("ui_asb_acf_tables"))
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(ss_section_label())
        sidebar_layout.addWidget(title)

        actions = QWidget()
        actions.setStyleSheet(ss_transparent())
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)
        self._btn_add = self._action_button("btn_new", self._do_add_row)
        self._btn_dup = self._action_button("btn_duplicate", self._do_duplicate_row)
        self._btn_del = self._action_button("btn_delete", self._do_delete_row, danger=True)
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
        actions_layout.addWidget(self._btn_del, 1)
        sidebar_layout.addWidget(actions)

        self._table_list_widget = QWidget()
        self._table_list_widget.setStyleSheet(ss_transparent())
        self._table_list_layout = QVBoxLayout(self._table_list_widget)
        self._table_list_layout.setContentsMargins(0, 0, 0, 0)
        self._table_list_layout.setSpacing(1)
        self._table_list_layout.addStretch()

        table_scroll = QScrollArea()
        table_scroll.setWidgetResizable(True)
        table_scroll.setFrameShape(QFrame.Shape.NoFrame)
        table_scroll.setStyleSheet(ss_scrollarea_transparent())
        table_scroll.setWidget(self._table_list_widget)
        sidebar_layout.addWidget(table_scroll, 1)
        main_layout.addWidget(sidebar)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)
        self._show_placeholder(ui_text("ui_asb_acf_open_file_to_begin_editing"))
        self._update_actions()

    def _action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setFixedHeight(28)
        btn.setFont(QFont("Segoe UI", 10))
        btn.setEnabled(False)
        btn.setStyleSheet(ss_btn(danger=danger))
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._row_cards = []
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_asb_acf_open_title"),
            game_files_dialog_dir(target_patterns=("ASB.acf", "*.acf")),
            ui_text("ui_asb_acf_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        create_backup_on_open(path)
        try:
            root = parse_asb_acf(path)
        except Exception as exc:
            self._filepath = None
            self._root = None
            self._tables = []
            self._current_table_idx = None
            self._current_row_idx = None
            self._clear_table_list()
            set_file_label_empty(self._file_label, self._tr("no_file_loaded", ui_text("no_file_loaded")))
            self._show_placeholder(ui_text("ui_asb_acf_open_file_to_begin_editing"))
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._root = root
        self._dirty = False
        self._btn_save.setEnabled(False)
        set_file_label(self._file_label, path)
        self._refresh_table_index()
        self._populate_table_list()
        self._select_table(0 if self._tables else None)
        self._update_actions()

    def _do_save(self):
        if not self._filepath or self._root is None:
            return
        if not self._apply_all_fields(show_errors=True):
            return
        try:
            save_asb_acf(self._filepath, self._root)
            self._root = parse_asb_acf(self._filepath)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, self._filepath)
            old_idx = self._current_table_idx
            self._refresh_table_index()
            self._populate_table_list()
            selected = min(old_idx or 0, len(self._tables) - 1) if self._tables else None
            self._select_table(selected)
            QMessageBox.information(
                self,
                ui_text("dlg_title_success"),
                ui_text("msg_save_success", path=os.path.basename(self._filepath)),
            )
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _refresh_table_index(self):
        self._tables = []
        if self._root is not None:
            self._collect_tables(self._root)

    def _collect_tables(self, table: AcfUtfTable):
        self._tables.append(table)
        for row in table.rows:
            for value in row.values():
                if isinstance(value, AcfBlob) and value.table is not None:
                    self._collect_tables(value.table)

    def _clear_table_list(self):
        _clear_layout(self._table_list_layout)
        self._table_list_layout.addStretch()
        self._table_buttons = []

    def _populate_table_list(self):
        self._clear_table_list()
        for idx, table in enumerate(self._tables):
            btn = self._make_table_button(idx, table)
            self._table_list_layout.insertWidget(self._table_list_layout.count() - 1, btn)
            self._table_buttons.append((btn, idx))

    def _make_table_button(self, idx: int, table: AcfUtfTable) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_table_idx))
        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        title = QLabel(table.source_column or table.name)
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(ss_main_label())
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)

        title_text = table.source_column or table.name
        if table.name != title_text:
            subtitle = QLabel(ui_text("ui_asb_acf_table_subtitle", name=table.name))
            subtitle.setFont(QFont("Segoe UI", 9))
            subtitle.setStyleSheet(ss_dim_label())
            subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(subtitle)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_table(i))
        return btn

    def _select_table(self, idx: int | None):
        if not self._apply_all_fields(show_errors=True):
            return
        if idx is None or idx < 0 or idx >= len(self._tables):
            self._current_table_idx = None
            self._current_row_idx = None
            self._show_placeholder(ui_text("ui_asb_acf_open_file_to_begin_editing"))
            self._update_actions()
            return
        self._current_table_idx = idx
        self._current_row_idx = 0 if self._tables[idx].rows else None
        for btn, button_idx in self._table_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(self._tables[idx])
        self._update_actions()

    def _build_editor(self, table: AcfUtfTable):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._row_cards = []
        self._pending_section_titles = []
        self._loading_detail = True

        self._add_section(ui_text("ui_asb_acf_table_title", name=table.name))

        if not table.rows:
            self._show_placeholder(ui_text("ui_asb_acf_no_rows"))
            self._loading_detail = False
            return

        for row_idx, row in enumerate(table.rows):
            if len(table.rows) > 1:
                self._add_section(ui_text("ui_asb_acf_row_title", index=row_idx))
            for category_key, columns in self._column_groups(table):
                for chunk in self._column_chunks(columns, 12):
                    card = self._make_category_card(table, row_idx, row, category_key, chunk)
                    self._editor_layout.addWidget(card)
                    self._row_cards.append((card, row_idx))

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_row_card_styles()

    def _add_section(self, title: str):
        titles = getattr(self, "_pending_section_titles", [])
        titles.append(title)
        self._pending_section_titles = titles

    def _make_category_card(
        self,
        table: AcfUtfTable,
        row_idx: int,
        row: dict,
        category_key: str,
        columns: list[AcfColumn],
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("EditorCard")
        card.setStyleSheet(ss_editor_card())
        card.mousePressEvent = lambda event, idx=row_idx: self._select_row(idx)

        main = QVBoxLayout(card)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        section_titles = getattr(self, "_pending_section_titles", [])
        self._pending_section_titles = []
        for section_title in section_titles:
            add_editor_card_title(layout, section_title, "fa6s.table")

        header = QLabel(ui_text(category_key))
        header.setMinimumWidth(0)
        header.setWordWrap(True)
        header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        header.setStyleSheet(ss_main_label())
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        layout.addLayout(grid)

        for idx, column in enumerate(columns):
            grid_row, grid_col = divmod(idx, 3)
            field = self._field_widget(table, row_idx, column, row.get(column.name))
            grid.addWidget(field, grid_row, grid_col)
            grid.setColumnStretch(grid_col, 1)

        main.addWidget(inner)
        return card

    def _column_groups(self, table: AcfUtfTable) -> list[tuple[str, list[AcfColumn]]]:
        groups: list[tuple[str, list[AcfColumn]]] = []
        order = [
            "ui_asb_acf_group_identity",
            "ui_asb_acf_group_values",
            "ui_asb_acf_group_voice_limits",
            "ui_asb_acf_group_routing",
            "ui_asb_acf_group_dsp_fx",
            "ui_asb_acf_group_categories",
            "ui_asb_acf_group_aisac",
            "ui_asb_acf_group_commands",
            "ui_asb_acf_group_work",
            "ui_asb_acf_group_nested_tables",
            "ui_asb_acf_group_raw_data",
            "ui_asb_acf_group_reserved",
        ]
        buckets = {key: [] for key in order}

        for column in table.columns:
            key = self._column_group_key(table, column)
            buckets.setdefault(key, []).append(column)

        for key in order:
            if buckets.get(key):
                groups.append((key, buckets[key]))
        return groups

    def _column_group_key(self, table: AcfUtfTable, column: AcfColumn) -> str:
        name = column.name.lower()
        is_header = table.name == "Header"
        if name.startswith("r") and name[1:].isdigit():
            return "ui_asb_acf_group_reserved"
        if is_header and any(token in name for token in ("voice", "cue", "limit")):
            return "ui_asb_acf_group_voice_limits"
        if is_header and any(token in name for token in ("category", "react")):
            return "ui_asb_acf_group_categories"
        if "md5" in name:
            return "ui_asb_acf_group_raw_data"
        if "aisac" in name:
            return "ui_asb_acf_group_aisac"
        if "command" in name or "react" in table.name.lower():
            return "ui_asb_acf_group_commands"
        if "fx" in name or "dsp" in name or "srtype" in name or "parameter" in name:
            return "ui_asb_acf_group_dsp_fx"
        if "bus" in name or "send" in name or "link" in name or "pan3d" in name:
            return "ui_asb_acf_group_routing"
        if any(token in name for token in ("work", "offset", "index", "start", "num")):
            return "ui_asb_acf_group_work"
        if column.dtype == DT_VLDATA:
            return "ui_asb_acf_group_raw_data" if not is_header else "ui_asb_acf_group_nested_tables"
        if any(token in name for token in ("name", "identifier", "version", "type", "target")):
            return "ui_asb_acf_group_identity"
        return "ui_asb_acf_group_values"

    def _column_chunks(self, columns: list[AcfColumn], size: int) -> list[list[AcfColumn]]:
        return [columns[idx:idx + size] for idx in range(0, len(columns), size)]

    def _field_widget(self, table: AcfUtfTable, row_idx: int, column: AcfColumn, value) -> QWidget:
        frame = QWidget()
        frame.setMinimumWidth(0)
        frame.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(ui_text("ui_asb_acf_column_header", name=column.name, type=column.type_name))
        label.setMinimumWidth(0)
        label.setWordWrap(True)
        label.setFont(QFont("Segoe UI", 12))
        label.setStyleSheet(ss_field_label())
        layout.addWidget(label)

        edit = QLineEdit()
        edit.setFixedHeight(30)
        edit.setMinimumWidth(0)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.setText(self._format_value(value))
        edit.setReadOnly(column.storage != ST_PERROW or (isinstance(value, AcfBlob) and value.table is not None))
        if isinstance(value, AcfBlob) and value.table is not None:
            edit.setToolTip(ui_text("ui_asb_acf_nested_table_cell", name=value.table.name))
        original_mouse_press = edit.mousePressEvent
        edit.mousePressEvent = lambda event, idx=row_idx, handler=original_mouse_press: (
            self._select_row(idx),
            handler(event),
        )
        edit.textEdited.connect(lambda _text, idx=row_idx: self._on_text_edited(idx))
        edit.editingFinished.connect(lambda widget=edit: self._apply_field(widget, show_errors=True))
        edit.selectionChanged.connect(lambda idx=row_idx: self._select_row(idx))
        layout.addWidget(edit)
        self._fields[edit] = (table, row_idx, column)
        return frame

    def _format_value(self, value) -> str:
        if isinstance(value, AcfBlob):
            if value.table is not None:
                return ui_text("ui_asb_acf_nested_table_cell", name=value.table.name)
            return _blob_to_hex(value)
        if isinstance(value, float):
            return f"{value:.9g}"
        return "" if value is None else str(value)

    def _select_row(self, row_idx: int):
        self._current_row_idx = row_idx
        self._refresh_row_card_styles()
        self._update_actions()

    def _refresh_row_card_styles(self):
        table = self._selected_table()
        show_selection = bool(table is not None and len(table.rows) > 1)
        for card, row_idx in self._row_cards:
            selected = show_selection and row_idx == self._current_row_idx
            card.setStyleSheet(ss_editor_card(selected=selected))

    def _on_text_edited(self, row_idx: int):
        if self._loading_detail:
            return
        self._select_row(row_idx)
        self._mark_dirty()

    def _apply_field(self, edit: QLineEdit, show_errors: bool = False) -> bool:
        if self._loading_detail or edit not in self._fields:
            return True
        table, row_idx, column = self._fields[edit]
        if row_idx >= len(table.rows) or column.storage != ST_PERROW:
            return True

        current = table.rows[row_idx].get(column.name)
        if isinstance(current, AcfBlob) and current.table is not None:
            return True

        try:
            table.rows[row_idx][column.name] = validate_cell_value(column, edit.text())
        except ValueError as exc:
            edit.setText(self._format_value(current))
            if show_errors:
                self._show_validation_error(column.name, str(exc))
            return False
        return True

    def _apply_all_fields(self, show_errors: bool = False) -> bool:
        for edit in list(self._fields):
            if not self._apply_field(edit, show_errors=show_errors):
                return False
        return True

    def _show_validation_error(self, field: str, code: str):
        key = {
            "invalid_hex": "ui_asb_acf_invalid_hex",
            "invalid_integer": "ui_asb_acf_invalid_integer",
            "integer_range": "ui_asb_acf_invalid_integer",
            "invalid_float": "ui_asb_acf_invalid_float",
        }.get(code, "ui_asb_acf_invalid_value")
        QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text(key, field=field))

    def _selected_table(self) -> AcfUtfTable | None:
        if self._current_table_idx is None or self._current_table_idx >= len(self._tables):
            return None
        return self._tables[self._current_table_idx]

    def _selected_row(self) -> int | None:
        table = self._selected_table()
        if table is None or self._current_row_idx is None:
            return None
        if self._current_row_idx < 0 or self._current_row_idx >= len(table.rows):
            return None
        return self._current_row_idx

    def _do_add_row(self):
        table = self._selected_table()
        if table is None or not self._apply_all_fields(show_errors=True):
            return
        table.rows.append(make_default_row(table))
        self._mark_dirty()
        self._refresh_after_row_change(len(table.rows) - 1)

    def _do_duplicate_row(self):
        table = self._selected_table()
        row = self._selected_row()
        if table is None or row is None or not self._apply_all_fields(show_errors=True):
            return
        table.rows.insert(row + 1, make_default_row(table, table.rows[row]))
        self._mark_dirty()
        self._refresh_after_row_change(row + 1)

    def _do_delete_row(self):
        table = self._selected_table()
        row = self._selected_row()
        if table is None or row is None:
            return
        if table is self._root and len(table.rows) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_asb_acf_cannot_delete_header"))
            return
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_asb_acf_delete_row_confirm", row=row, table=table.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        table.rows.pop(row)
        self._mark_dirty()
        self._refresh_after_row_change(max(0, min(row, len(table.rows) - 1)))

    def _refresh_after_row_change(self, selected_row: int):
        selected_table = self._selected_table()
        self._refresh_table_index()
        self._populate_table_list()
        if selected_table in self._tables:
            self._current_table_idx = self._tables.index(selected_table)
        self._select_table(self._current_table_idx)
        self._select_row(selected_row)

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._filepath:
                set_file_label(self._file_label, self._filepath, dirty=True)
        self._update_actions()

    def _update_actions(self):
        loaded = self._root is not None
        table = self._selected_table()
        has_row = table is not None and bool(table.rows)
        can_mutate_rows = table is not None and table is not self._root
        self._btn_add.setEnabled(loaded and can_mutate_rows)
        self._btn_dup.setEnabled(loaded and can_mutate_rows and has_row)
        self._btn_del.setEnabled(loaded and can_mutate_rows and has_row)
        self._btn_save.setEnabled(loaded and self._dirty)
