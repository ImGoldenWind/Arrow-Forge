from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_editor_card,
    ss_field_label,
    ss_main_label,
    ss_transparent,
    ss_input_validation,
    editor_rich_link,
    make_editor_card,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
    fit_scroll_page,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import os
import copy
from html import escape
from parsers.acf_dsp import DspField, FX_NAMES, dsp_fields
from core.acf_research import (CommandField, command_fields, normalized_frequency,
    category_name, routing_rows, reference_issues)
from core.acf_tools import TABLE_NAMES, row_name, value_choices, reference_target, searchable_row, user_table, user_column, user_help
from core.record_session import RecordSession
from core.ui.record_list import RecordListModel, EditorRecordList
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper, FloatStepper, FloatSliderInput

from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, QEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from parsers.asb_acf_parser import (
    DT_VLDATA,
    DT_FLOAT,
    integer_bounds,
    ST_CONSTANT,
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


def _truncate(text: str, limit: int = 28) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


class AsbAcfEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._root: AcfUtfTable | None = None
        self._tables: list[AcfUtfTable] = []
        self._row_cards: list[tuple[QFrame, int]] = []
        self._fields: dict[QLineEdit, tuple[AcfUtfTable, int, AcfColumn | DspField]] = {}
        self._current_table_idx: int | None = None
        self._current_row_idx: int | None = None
        self._dirty = False
        self._loading_detail = False
        self._grid_cols = 0
        self._grids = []
        self._combos = {}
        self._sessions = {}
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._rebuild_for_width)
        self._decoder_timer = QTimer(self)
        self._decoder_timer.setSingleShot(True)
        self._decoder_timer.timeout.connect(lambda: self._refresh_decoder(*self._decoder_target))

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))
        self._file_label.setMinimumWidth(0)
        self._file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label, 1)
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        sidebar = EditorSidebar()


        sidebar_layout = sidebar.content_layout


        self._search_entry = configure_search(QLineEdit())
        self._search_entry.textChanged.connect(self._filter_rows)
        sidebar_layout.addWidget(self._search_entry)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        self._btn_add = self._action_button("btn_new", self._do_add_row)
        self._btn_add.setProperty("designAction", 'new')
        self._btn_dup = self._action_button("btn_duplicate", self._do_duplicate_row)
        self._btn_dup.setProperty("designAction", 'duplicate')
        self._btn_del = self._action_button("btn_delete", self._do_delete_row, danger=True)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
        actions_layout.addWidget(self._btn_del, 1)
        sidebar_layout.addWidget(actions)

        self._section_combo = configure_input(QComboBox(), monospace=False)
        self._section_combo.setMinimumWidth(0)
        self._section_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._section_combo.setToolTip(ui_text('ui_asb_acf_tables'))
        self._section_combo.setAccessibleName(ui_text('ui_asb_acf_tables'))
        self._section_combo.setEnabled(False)
        self._section_combo.currentIndexChanged.connect(self._table_changed)
        sidebar_layout.addWidget(self._section_combo)
        self._row_model = RecordListModel(self)
        self._catalog = EditorRecordList(self._row_model, self._describe_row)
        self._catalog.setAccessibleName(ui_text('acf_records'))
        self._catalog.selectionModel().currentRowChanged.connect(self._catalog_changed)
        sidebar_layout.addWidget(self._catalog, 1)
        self._no_matches = QLabel(ui_text('acf_no_matches'))
        self._no_matches.setWordWrap(True)
        self._no_matches.setStyleSheet(ss_dim_label())
        self._no_matches.hide()
        sidebar_layout.addWidget(self._no_matches)
        main_layout.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)
        self._show_placeholder(ui_text("ui_asb_acf_open_file_to_begin_editing"))
        self._update_actions()

    def _editor_width(self) -> int:
        return max(0, self._editor_scroll.viewport().width() if hasattr(self, "_editor_scroll") else self.width())

    def _grid_columns(self) -> int:
        width = self._editor_width()
        if width < 620:
            return 1
        if width < 930:
            return 2
        return 3

    def _chunk_size(self) -> int:
        return max(1, self._grid_columns() * 4)

    def _prep_card(self, card: QWidget, *, max_width: int = 16777215):
        configure_card(card, maximum_width=max_width, vertical_policy=QSizePolicy.Policy.Minimum)

    def _rebuild_for_width(self):
        cols = self._grid_columns()
        self._grid_cols = cols
        for grid, frames in self._grids:
            for col in range(3):
                grid.setColumnStretch(col, int(col < cols))
            for i, frame in enumerate(frames):
                grid.addWidget(frame, i // cols, i % cols, Qt.AlignmentFlag.AlignTop)
        fit_scroll_page(self._editor_scroll)

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._resize_timer.start()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._tables and self._current_table_idx is not None:
            self._resize_timer.start()

    def _action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setEnabled(False)
        configure_button(btn, danger=danger, height=Size.COMPACT_CONTROL)
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str, title=None):
        self._reset_form()
        _clear_layout(self._editor_layout)
        card = make_empty_state(
            self._editor_widget,
            title=title or ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _reset_form(self):
        # Clear Python references before Qt destroys the old form. Never retain
        # QLabel wrappers across section/row switches or deferred rebuilds.
        self._fields = {}
        self._combos = {}
        self._grids = []
        self._row_cards = []
        self._reference_labels = []
        self._routing_label = None
        self._issues_label = None
        self._react_labels = []
        self._restore_btn = None

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
        if not self._apply_all_fields(show_errors=True):
            return False
        try:
            root = parse_asb_acf(path)
            create_backup_on_open(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return False

        self._filepath = path
        self._fields = {}
        self._root = root
        self._dirty = False
        self._btn_save.setEnabled(False)
        set_file_label(self._file_label, path)
        self._refresh_table_index()
        self._sessions = {id(t): RecordSession({'entries': t.rows}, [c.name for c in t.columns
            if not any(isinstance(r.get(c.name), AcfBlob) and r[c.name].table is not None for r in t.rows)]) for t in self._tables}
        self._current_table_idx = None
        self._current_row_idx = None
        self._populate_table_list()
        self._search_entry.clear()
        self._select_table(0 if self._tables else None)
        self._update_actions()
        return True

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._root is None:
            return
        if not self._apply_all_fields(show_errors=True):
            return
        try:
            save_asb_acf(save_path, self._root)
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
            for session in self._sessions.values():
                session.mark_saved()
            self._update_actions()
            QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(save_path)))
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False

    def _refresh_table_index(self):
        self._tables = []
        if self._root is not None:
            self._collect_tables(self._root)

    def _collect_tables(self, table: AcfUtfTable):
        if any(t is table for t in self._tables):
            return
        self._tables.append(table)
        for row in table.rows:
            for value in row.values():
                if isinstance(value, AcfBlob) and value.table is not None:
                    self._collect_tables(value.table)

    def _clear_table_list(self):
        with QSignalBlocker(self._section_combo):
            self._section_combo.clear()
        self._section_combo.setEnabled(False)

    def _populate_table_list(self):
        with QSignalBlocker(self._section_combo):
            self._section_combo.clear()
            for index, table in enumerate(self._tables):
                if not user_table(table):
                    continue
                self._section_combo.addItem(self._table_title(table), index)
            self._section_combo.setCurrentIndex(self._section_combo.findData(self._current_table_idx))
        self._section_combo.setEnabled(bool(self._tables))

    def _table_title(self, table):
        return ui_text('acf_table_' + table.name) if table.name in TABLE_NAMES else table.name

    def _table_changed(self, index):
        if not self._select_table(self._section_combo.itemData(index) if index >= 0 else None):
            with QSignalBlocker(self._section_combo):
                self._section_combo.setCurrentIndex(self._section_combo.findData(self._current_table_idx))

    def _describe_row(self, index):
        _, row_index = self._row_model.rows[index.row()]
        table = self._selected_table()
        title = row_name(self._tables, table, row_index) or ui_text('ui_asb_acf_row_title', index=row_index)
        session = self._sessions.get(id(table))
        mark = '● ' if session and session.modified(table.rows[row_index]) else ''
        return mark + title, ui_text('ui_asb_acf_row_title', index=row_index), title

    def _filter_rows(self, *_):
        table = self._selected_table()
        query = self._search_entry.text().strip().casefold()
        rows = [(row_name(self._tables, table, i), i) for i in range(len(table.rows))
                if not query or query in searchable_row(self._tables, table, i)] if table else []
        with QSignalBlocker(self._catalog.selectionModel()):
            self._row_model.reset_rows(rows)
            visible = next((i for i, r in enumerate(rows) if r[1] == self._current_row_idx), -1)
            self._catalog.setCurrentIndex(self._row_model.index(visible))
        self._no_matches.setVisible(table is not None and not rows)

    def _catalog_changed(self, index, previous):
        if index.isValid() and not self._open_row(self._row_model.rows[index.row()][1]):
            with QSignalBlocker(self._catalog.selectionModel()):
                self._catalog.setCurrentIndex(previous)

    def _open_row(self, row_idx):
        table = self._selected_table()
        if table is None or not 0 <= row_idx < len(table.rows) or not self._apply_all_fields(show_errors=True):
            return False
        self._current_row_idx = row_idx
        self._build_editor(table)
        self._filter_rows()
        self._update_actions()
        return True

    def _select_table(self, idx: int | None):
        if not self._apply_all_fields(show_errors=True):
            return False
        if idx is None or idx < 0 or idx >= len(self._tables):
            self._current_table_idx = None
            self._current_row_idx = None
            self._show_placeholder(ui_text("ui_asb_acf_open_file_to_begin_editing"))
            self._update_actions()
            return True
        self._current_table_idx = idx
        self._current_row_idx = 0 if self._tables[idx].rows else None
        with QSignalBlocker(self._section_combo):
            self._section_combo.setCurrentIndex(self._section_combo.findData(idx))
        self._filter_rows()
        self._build_editor(self._tables[idx])
        self._update_actions()
        return True

    def _build_editor(self, table: AcfUtfTable):
        self._reset_form()
        _clear_layout(self._editor_layout)
        self._pending_section_titles = []
        self._loading_detail = True
        self._grid_cols = self._grid_columns()

        self._add_section(self._table_title(table))
        self._add_context_card(table)

        if not table.rows:
            self._show_placeholder(ui_text("ui_asb_acf_no_rows"), self._table_title(table))
            self._loading_detail = False
            return

        row_idx = self._current_row_idx if self._current_row_idx is not None else 0
        row_idx = max(0, min(row_idx, len(table.rows) - 1))
        self._current_row_idx = row_idx
        row = table.rows[row_idx]
        if len(table.rows) > 1:
            self._add_section(ui_text("ui_asb_acf_row_title", index=row_idx))
        if table.name == 'DspFx':
            self._add_dsp_parameter_card(table, row_idx, row)
        elif table.name == 'Command':
            blob = row.get('Command')
            fields = command_fields(blob.data) if isinstance(blob, AcfBlob) else ()
            if fields:
                self._add_packed_card(table, row_idx, row, fields, ui_text('acf_command_title'))
            elif isinstance(blob, AcfBlob) and blob.data:
                self._add_unavailable(ui_text('acf_command_unavailable'))
        elif table.name == 'React':
            self._add_react_overview(table, row_idx)
        for category_key, columns in self._column_groups(table):
            card = self._make_category_card(table, row_idx, row, category_key, columns)
            self._editor_layout.addWidget(card)
            self._row_cards.append((card, row_idx))

        self._add_restore(table, row_idx)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._refresh_row_card_styles()
        self._rebuild_for_width()

    def _add_dsp_parameter_card(self, table, row_idx, row):
        blob = row.get('Parameters')
        fields = dsp_fields(row.get('FxType', 0), blob.data) if isinstance(blob, AcfBlob) and row.get('SrType', 0) == 0 else ()
        if not fields:
            self._add_unavailable(ui_text('acf_effect_unavailable'))
            return
        self._add_packed_card(table, row_idx, row, fields, FX_NAMES.get(row.get('FxType'), str(row.get('FxType'))))

    def _add_packed_card(self, table, row_idx, row, fields, title):
        from core.style_helpers import make_editor_grid_card, make_editor_field_shell
        blob = row[fields[0].blob_name]
        card, grid = make_editor_grid_card(self._editor_widget,
            title=title, icon_name='fa6s.sliders')
        self._prep_card(card)
        columns = self._grid_columns()
        frames = []
        editable = next((c.storage in (ST_PERROW, ST_CONSTANT) for c in table.columns if c.name == fields[0].blob_name), False)
        for index, field in enumerate(fields):
            shell, layout, _, _ = make_editor_field_shell(ui_text('acf_dsp_' + field.name))
            edit, control = self._value_input(table, row_idx, field, field.read(blob.data), editable)
            edit.setToolTip('')
            if field.name == 'flags':
                edit.setToolTip(ui_text('acf_user_bypass'))
            elif isinstance(field, CommandField):
                edit.setToolTip(ui_text('acf_user_' + field.name))
            layout.addWidget(control)
            self._add_value_control(layout, edit, row_idx, field.name)
            grid.addWidget(shell, index // columns, index % columns)
            grid.setColumnStretch(index % columns, 1)
            frames.append(shell)
            if editable:
                self._fields[edit] = (table, row_idx, field)
            self._add_original_hint(layout, table, row_idx, field)
        self._grids.append((grid, frames))
        self._editor_layout.addWidget(card)
        self._row_cards.append((card, row_idx))

    def _add_unavailable(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(ss_dim_label())
        label.setFont(ui_font(TypeSize.BODY))
        self._editor_layout.addWidget(label)

    def _value_input(self, table, row_idx, field, value, editable):
        choices = value_choices(self._tables, table, field.name, ui_text) if editable else []
        if choices:
            if value not in [v for v, _ in choices]:
                choices.append((value, ui_text('acf_stored_value', value=value)))
            combo = EditorValueCombo(choices, value)
            # Native integer data is retained; EditorValueCombo.value_text also
            # handles it and preserves incomplete/custom numeric entry.
            for i, (key, _) in enumerate(choices):
                combo.setItemData(i, key)
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            edit, control = combo.lineEdit(), combo
            self._combos[edit] = combo
            combo.activated.connect(lambda _: self._apply_all_fields(show_errors=True))
        else:
            edit = configure_input(QLineEdit(self._format_value(value)), monospace=True)
            edit.setReadOnly(not editable)
            edit.setMinimumWidth(0)
            control = edit
            bounds = integer_bounds(getattr(field, 'dtype', None))
            if isinstance(field, DspField) and field.fmt in ('B', 'H'):
                bounds = (0, 255 if field.fmt == 'B' else 65535)
            if editable and bounds:
                control = IntegerStepper(edit, *bounds)
            elif editable and (getattr(field, 'dtype', None) == DT_FLOAT or isinstance(field, DspField) and field.fmt == 'f'):
                if field.name in ('Volume', 'SendLevel', 'Pan3dVolume', 'Level',
                                  'frequency_normalized', 'cutoff_high_normalized', 'cutoff_low_normalized') and not (
                        field.name == 'Level' and table.name == 'React' and table.rows[row_idx].get('ParameterId', 0) != 0):
                    control = FloatSliderInput(edit, 0, 1, .001)
                    # Outside this shortcut span exact manual values remain
                    # editable, with the drag disabled rather than clamped.
                    def sync(*_):
                        v = control.stepper.value()
                        control.slider.setEnabled(v is not None and 0 <= v <= 1)
                    edit.textChanged.connect(sync)
                    control.value_changed.connect(lambda: self._apply_all_fields())
                    control.stepper.increase.clicked.connect(lambda: self._apply_all_fields())
                    control.stepper.decrease.clicked.connect(lambda: self._apply_all_fields())
                    sync()
                else:
                    control = FloatStepper(edit, .01)
        edit.setAccessibleName(self._field_title(field))
        edit.textChanged.connect(lambda _text, i=row_idx: self._on_text_edited(i))
        edit.editingFinished.connect(lambda: self._apply_all_fields(show_errors=True))
        if isinstance(control, (IntegerStepper, FloatStepper)):
            control.increase.clicked.connect(lambda: self._apply_all_fields())
            control.decrease.clicked.connect(lambda: self._apply_all_fields())
        return edit, control

    def _add_value_control(self, layout, edit, row_idx, name):
        if name.endswith('_normalized'):
            label = QLabel()
            label.setFont(ui_font(TypeSize.BODY))
            label.setStyleSheet(ss_dim_label())
            def frequency(text):
                try:
                    hz = normalized_frequency(float(text))
                except ValueError:
                    hz = None
                label.setText(ui_text('acf_frequency_hz', hz=f'{hz:.2f}') if hz is not None else '')
            edit.textChanged.connect(frequency)
            frequency(edit.text())
            layout.addWidget(label)

    def _field_title(self, field):
        key = ('acf_dsp_' if isinstance(field, DspField) else 'acf_field_') + field.name
        title = ui_text(key)
        return field.name if title == key else title

    def _add_original_hint(self, layout, table, row_idx, field):
        session = self._sessions.get(id(table))
        original = session.original(table.rows[row_idx]) if session else None
        if original is None:
            return
        value = original.get(field.blob_name) if isinstance(field, DspField) else original.get(field.name)
        if isinstance(value, AcfBlob) and value.table is not None:
            return
        if isinstance(field, DspField):
            fields = command_fields(value.data) if isinstance(field, CommandField) and isinstance(value, AcfBlob) else (
                dsp_fields(original.get('FxType', 0), value.data) if isinstance(value, AcfBlob) else ())
            if field not in fields:
                return
            value = field.read(value.data)
        choices = dict(value_choices(self._tables, table, field.name, ui_text))
        text = choices.get(value, self._format_value(value))
        label = QLabel(ui_text('acf_original_value', value=_truncate(text, 50)))
        label.setToolTip(text)
        label.setWordWrap(True)
        label.setStyleSheet(ss_dim_label())
        label.setFont(ui_font(TypeSize.HINT))
        layout.addWidget(label)
        label.hide()

    def _add_restore(self, table, row_idx):
        session = self._sessions.get(id(table))
        if not session or session.original(table.rows[row_idx]) is None:
            return
        self._restore_btn = configure_button(QPushButton(ui_text('acf_restore_record')))
        self._restore_btn.hide()
        self._restore_btn.setEnabled(session.modified(table.rows[row_idx]))
        self._restore_btn.clicked.connect(self._restore_row)
        self._editor_layout.addWidget(self._restore_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _restore_row(self):
        table, index = self._selected_table(), self._selected_row()
        if table is None or index is None:
            return
        session = self._sessions.get(id(table))
        original = session.original(table.rows[index]) if session else None
        if original is None:
            return
        self._fields = {}
        row = table.rows[index]
        for column in table.columns:
            value = original[column.name]
            if isinstance(value, AcfBlob) and value.table is not None:
                continue
            if row.get(column.name) != value:
                self._promote_constant(table, column)
                row[column.name] = copy.deepcopy(value)
        self._mark_dirty()
        self._build_editor(table)
        self._filter_rows()

    def _add_react_overview(self, table, row_idx):
        card, layout = make_editor_card(self._editor_widget)
        self._prep_card(card)
        label = QLabel()
        label.setFont(ui_font(TypeSize.CODE))
        label.setWordWrap(True)
        label.setStyleSheet(ss_main_label())
        layout.addWidget(label)
        self._react_labels.append((label, table, row_idx))
        self._editor_layout.addWidget(card)
        self._row_cards.append((card, row_idx))
        self._refresh_references()

    def _add_context_card(self, table):
        if table.name in ('Bus', 'BusLink', 'DspSetting'):
            card, layout = make_editor_card(self._editor_widget)
            self._prep_card(card)
            add_editor_card_title(layout, ui_text('acf_route_view'), 'fa6s.diagram-project')
            hint = QLabel(ui_text('acf_route_hint'))
            hint.setWordWrap(True)
            hint.setStyleSheet(ss_dim_label())
            hint.setFont(ui_font(TypeSize.HINT))
            layout.addWidget(hint)
            self._routing_label = QLabel()
            self._routing_label.setFont(ui_font(TypeSize.CODE))
            self._routing_label.setWordWrap(True)
            self._routing_label.setTextFormat(Qt.TextFormat.RichText)
            self._routing_label.setStyleSheet(ss_dim_label())
            self._routing_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
            self._routing_label.linkActivated.connect(self._route_activated)
            layout.addWidget(self._routing_label)
            self._editor_layout.addWidget(card)
        self._issues_label = QLabel()
        self._issues_label.setFont(ui_font(TypeSize.BODY))
        self._issues_label.setWordWrap(True)
        self._issues_label.setStyleSheet(ss_dim_label())
        self._editor_layout.addWidget(self._issues_label)
        self._refresh_references()

    def _route_activated(self, link):
        name, _, index = link.partition(':')
        target = next((t for t in self._tables if t.name == name), None)
        if target is not None and index.isdecimal() and 0 <= int(index) < len(target.rows):
            self._navigate(target, int(index))

    def _refresh_references(self):
        for label, table, row_idx in getattr(self, '_react_labels', []):
            row = table.rows[row_idx]
            source = category_name(self._tables, row.get('Src')) or str(row.get('Src', '?'))
            dest = category_name(self._tables, row.get('Dest')) or str(row.get('Dest', '?'))
            hold = (ui_text('acf_hold_duration', ms=row.get('HoldTime', 0)) if row.get('HoldType') == 1 else
                    ui_text('acf_hold_until_end') if row.get('HoldType') == 0 else ui_text('acf_hold_unknown'))
            label.setText(ui_text('acf_user_react_flow', source=source, dest=dest,
                attack=row.get('DecrementTime', 0), level=f'{row.get("Level", 0):.4g}', hold=hold,
                release=row.get('IncrementTime', 0), parameter=row.get('ParameterId', 0)))
        for label, table, column, row_idx in getattr(self, '_reference_labels', []):
            if row_idx < len(table.rows):
                row = table.rows[row_idx]
                description = self._field_description(table, column, row.get(column.name), row)
                label.setText(description)
                label.setVisible(bool(description))
        if getattr(self, '_routing_label', None):
            from core.acf_research import table_by_name
            lines = []
            buses = table_by_name(self._tables, 'Bus')
            links = table_by_name(self._tables, 'BusLink')
            def anchor(table, index, text):
                return editor_rich_link(text, f'{table}:{index}')
            for bus_index, (name, number, chain, sends) in enumerate(routing_rows(self._tables)):
                selected = self._selected_table()
                if selected is buses and bus_index != self._current_row_idx:
                    continue
                bus_row = buses.rows[bus_index]
                if selected and selected.name == 'DspSetting' and self._selected_row() is not None:
                    setting = selected.rows[self._current_row_idx]
                    if not setting.get('StartIndex', 0) <= bus_index < setting.get('StartIndex', 0) + setting.get('NumBuses', 0):
                        continue
                source = '<b>' + anchor('Bus', bus_index, f'{name} [{number}]') + '</b>'
                if chain:
                    source += ' → ' + ' → '.join(anchor('DspFx', bus_row.get('StartFxIndex', 0) + i, effect) for i, effect in enumerate(chain))
                for i, (target, dest, gain, kind) in enumerate(sends):
                    tap = ui_text('acf_link_' + str(kind)) if kind in (0, 1, 2) else f'Type {kind}'
                    link_index = bus_row.get('StartBusLinkIndex', 0) + i
                    target_index = next((i for i, r in enumerate(buses.rows) if r.get('BusNo') == dest), None)
                    destination = anchor('Bus', target_index, f'{target} [{dest}]') if target_index is not None else escape(str(target))
                    lines.append(source + ' → ' + destination + ' · ' + anchor('BusLink', link_index, f'×{gain:.4g} · {tap}'))
                if not sends:
                    lines.append(source + ' · ' + ui_text('acf_no_sends'))
            self._routing_label.setText('<br><br>'.join(lines))
        if getattr(self, '_issues_label', None):
            issues = reference_issues(self._tables)
            self._issues_label.setText(ui_text('acf_user_invalid_links') if issues else '')
            self._issues_label.setVisible(bool(issues))
        # Reference diagnostics/phase descriptions can wrap to more lines after
        # a commit; update their shared card heights without rebuilding inputs.
        self._resize_timer.start()

    def _field_description(self, table, column, value, row=None):
        key = user_help(table, column.name)
        description = ui_text(key) if key else ''
        if table.name == 'React' and column.name == 'Level' and row is not None and row.get('ParameterId', 0) != 0:
            description = ''
        return description

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
        from core.style_helpers import make_editor_grid_card
        section_titles = getattr(self, '_pending_section_titles', [])
        self._pending_section_titles = []
        card, grid = make_editor_grid_card(self._editor_widget,
            title=ui_text(category_key), subtitle=' · '.join(section_titles), icon_name='fa6s.sliders')
        self._prep_card(card)
        card.mousePressEvent = lambda event, idx=row_idx: self._select_row(idx)

        cols = max(1, self._grid_cols or self._grid_columns())
        frames = []
        for idx, column in enumerate(columns):
            grid_row, grid_col = divmod(idx, cols)
            field = self._field_widget(table, row_idx, column, row.get(column.name))
            grid.addWidget(field, grid_row, grid_col)
            grid.setColumnStretch(grid_col, 1)
            frames.append(field)

        self._grids.append((grid, frames))

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
            if not user_column(table, column):
                continue
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
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        frame.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(frame)
        configure_layout(layout, LayoutRole.TITLE_TEXT)

        label_text = self._field_title(column)
        if table.name == 'React' and column.name == 'Level' and table.rows[row_idx].get('ParameterId', 0) != 0:
            label_text = ui_text('acf_target_parameter')
        label = QLabel(label_text)
        description = self._field_description(table, column, value, table.rows[row_idx])
        label.setToolTip(description)
        label.setMinimumWidth(0)
        label.setWordWrap(True)
        label.setFont(ui_font(TypeSize.LABEL))
        label.setStyleSheet(ss_field_label())
        layout.addWidget(label)

        editable = column.storage in (ST_PERROW, ST_CONSTANT) and not (isinstance(value, AcfBlob) and value.table is not None)
        edit, control = self._value_input(table, row_idx, column, value, editable)
        control.setToolTip(description)
        edit.setToolTip(description)
        if edit.isReadOnly():
            edit.setCursorPosition(0)
        original_mouse_press = edit.mousePressEvent
        edit.mousePressEvent = lambda event, idx=row_idx, handler=original_mouse_press: (
            self._select_row(idx),
            handler(event),
        )
        edit.selectionChanged.connect(lambda idx=row_idx: self._select_row(idx))
        layout.addWidget(control)
        self._add_value_control(layout, edit, row_idx, column.name)
        target_name = reference_target(table.name, column.name)
        nested = value.table if isinstance(value, AcfBlob) else None
        if target_name or nested is not None:
            button = configure_button(QPushButton(ui_text('acf_open_related')), height=Size.COMPACT_CONTROL)
            button.clicked.connect(lambda _, w=edit, target=target_name, child=nested: self._open_related(w, target, child))
            layout.addWidget(button)
        help_label = QLabel(description, frame)
        help_label.setVisible(bool(description))
        help_label.setWordWrap(True)
        help_label.setStyleSheet(ss_dim_label())
        help_label.setFont(ui_font(TypeSize.HINT))
        layout.addWidget(help_label)
        if table.name == 'React':
            self._reference_labels.append((help_label, table, column, row_idx))
        self._add_original_hint(layout, table, row_idx, column)
        self._fields[edit] = (table, row_idx, column)
        return frame

    def _edit_text(self, edit):
        combo = self._combos.get(edit)
        return combo.value_text() if combo is not None else edit.text()

    def _open_related(self, edit, target_name, nested):
        if not self._apply_all_fields(show_errors=True):
            return
        target = nested or next((t for t in self._tables if t.name == target_name), None)
        try:
            row_idx = 0 if nested is not None else int(self._edit_text(edit), 0)
        except ValueError:
            return
        if target is None or not 0 <= row_idx < len(target.rows):
            return
        self._navigate(target, row_idx)

    def _navigate(self, table, row_idx):
        if self._select_table(next(i for i, t in enumerate(self._tables) if t is table)):
            self._search_entry.clear()
            self._open_row(row_idx)

    def shortcut_action(self, action_id):
        if action_id not in ('editor.next', 'editor.previous'):
            return False
        count = self._row_model.rowCount()
        if count:
            step = 1 if action_id == 'editor.next' else -1
            row = max(0, min(count - 1, self._catalog.currentIndex().row() + step))
            self._catalog.setCurrentIndex(self._row_model.index(row))
            self._catalog.scrollTo(self._catalog.currentIndex())
        return True

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
        for card, _ in self._row_cards:
            card.setStyleSheet(ss_editor_card())

    def _on_text_edited(self, row_idx: int):
        if self._loading_detail:
            return
        self._select_row(row_idx)
        if self._restore_btn is not None:
            self._restore_btn.setEnabled(True)
        self._mark_dirty()

    def _apply_field(self, edit: QLineEdit, show_errors: bool = False) -> bool:
        return self._apply_all_fields(show_errors)

    def _apply_all_fields(self, show_errors: bool = False) -> bool:
        if self._loading_detail:
            return True
        staged = []
        # Validate the entire form before publishing any edit. Packed operands
        # still use the layout under which this form was built.
        for edit, (table, row_idx, column) in list(self._fields.items()):
            if row_idx >= len(table.rows) or edit.isReadOnly() or column.storage not in (ST_PERROW, ST_CONSTANT):
                continue
            row = table.rows[row_idx]
            text = self._edit_text(edit)
            current = row.get(column.blob_name) if isinstance(column, DspField) else row.get(column.name)
            display = self._format_value(column.read(current.data)) if isinstance(column, DspField) else self._format_value(current)
            try:
                if text == display:
                    value = None
                elif isinstance(column, DspField):
                    value = column.write(current.data, text)
                else:
                    value = validate_cell_value(column, text)
            except (ValueError, OverflowError) as exc:
                control = self._combos.get(edit, edit)
                control.setStyleSheet(ss_input_validation(True))
                if show_errors:
                    self._show_validation_error(self._field_title(column), str(exc))
                    edit.setFocus()
                return False
            control = self._combos.get(edit, edit)
            control.setStyleSheet(ss_input_validation(False))
            if text != display:
                staged.append((edit, table, row_idx, column, value))
        changed_layout = False
        for edit, table, row_idx, column, value in sorted(staged, key=lambda item: not isinstance(item[3], DspField)):
            row = table.rows[row_idx]
            if isinstance(column, DspField):
                actual = next(c for c in table.columns if c.name == column.blob_name)
                # Re-encode into the latest staged blob so two operand edits
                # cannot overwrite each other's neighboring bytes.
                data = column.write(row[column.blob_name].data, self._edit_text(edit))
                self._promote_constant(table, actual)
                row[column.blob_name].data = data
            elif value != row.get(column.name):
                self._promote_constant(table, column)
                row[column.name] = value
                changed_layout |= table.name == 'DspFx' and column.name in ('FxType', 'SrType')
            self._mark_dirty()
        if staged:
            self._refresh_references()
            self._filter_rows()
        if changed_layout:
            table, index = self._selected_table(), self._selected_row()
            row = table.rows[index] if table is not None and index is not None else None
            self._decoder_target = table, row
            self._decoder_timer.start(0)
        return True

    def _refresh_decoder(self, table, row):
        index = self._selected_row()
        if table is self._selected_table() and index is not None and table.rows[index] is row:
            if self._apply_all_fields():
                self._build_editor(table)

    def _promote_constant(self, table, column):
        if column.storage == ST_CONSTANT:
            # A single shared @UTF constant becomes one value per row only on
            # change. Clone blobs first, so neighboring rows retain their bytes.
            for row in table.rows:
                value = row.get(column.name)
                if isinstance(value, AcfBlob):
                    row[column.name] = value.clone()
            column.storage = ST_PERROW

    def _show_validation_error(self, field: str, code: str):
        key = {
            "invalid_hex": "ui_asb_acf_invalid_hex",
            "invalid_text": "acf_invalid_text",
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
        if table is None or table is self._root or not self._apply_all_fields(show_errors=True):
            return
        self._reset_form()
        table.rows.append(make_default_row(table))
        self._mark_dirty()
        self._refresh_after_row_change(len(table.rows) - 1)

    def _do_duplicate_row(self):
        table = self._selected_table()
        row = self._selected_row()
        if table is None or table is self._root or row is None or not self._apply_all_fields(show_errors=True):
            return
        self._reset_form()
        table.rows.append(make_default_row(table, table.rows[row]))
        self._mark_dirty()
        self._refresh_after_row_change(len(table.rows) - 1)

    def _do_delete_row(self):
        table = self._selected_table()
        row = self._selected_row()
        if table is None or row is None or not self._apply_all_fields(show_errors=True):
            return
        if table is self._root and len(table.rows) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_asb_acf_cannot_delete_header"))
            return
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_asb_acf_delete_row_confirm", row=row, table=table.name) + '\n\n' + ui_text('acf_delete_references'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._reset_form()
        table.rows.pop(row)
        self._mark_dirty()
        self._refresh_after_row_change(max(0, min(row, len(table.rows) - 1)))

    def _refresh_after_row_change(self, selected_row: int):
        selected_table = self._selected_table()
        self._refresh_table_index()
        self._populate_table_list()
        self._current_table_idx = next((i for i, t in enumerate(self._tables) if t is selected_table), None)
        self._current_row_idx = selected_row if selected_table.rows else None
        self._search_entry.clear()
        self._build_editor(selected_table)
        self._filter_rows()
        self._update_actions()

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._filepath:
                set_file_label(self._file_label, self._filepath, dirty=True)
        self._update_actions()

    def _update_actions(self):
        loaded = self._root is not None
        table = self._selected_table()
        has_row = self._selected_row() is not None
        can_mutate_rows = table is not None and table is not self._root
        self._btn_add.setEnabled(loaded and can_mutate_rows)
        self._btn_dup.setEnabled(loaded and can_mutate_rows and has_row)
        self._btn_del.setEnabled(loaded and can_mutate_rows and has_row)
        self._btn_save.setEnabled(loaded and self._dirty)
        if hasattr(self, '_file_actions'):
            self._file_actions.loaded = loaded
            self._file_actions.refresh()
