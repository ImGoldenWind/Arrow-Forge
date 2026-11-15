"""TrophyParam catalog and exact editing of two unknown values."""
import os

from PyQt6.QtCore import QEvent, QRegularExpression, QSignalBlocker, Qt, QTimer
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_dim_label, ss_error_label, ss_input_validation,
)
from core.translations import ui_text
from core.trophy_tools import FIELDS, UINT32_MAX, TrophySession, uint32
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (
    EditorActionRow, EditorFilterCombo, EditorSeparator, EditorSidebar, EditorToolbar,
    configure_button, configure_card, configure_field, configure_file_label,
    configure_input, configure_layout, configure_scrollarea, configure_search,
    fit_scroll_page,
)
from core.ui.number_input import IntegerStepper
from core.ui.record_list import EditorRecordList
from editors.trophyparam_model import TrophyFilterModel, TrophyTableModel
from parsers.trophyparam_parser import make_default_entry, parse_trophyparam_xfbin, save_trophyparam_xfbin


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class TrophyParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t, self._embedded = t or ui_text, embedded
        self._filepath = self._raw_data = self._result = self._session = None
        self._entries, self._fields = [], {}
        self._current_idx = None
        self._dirty = self._loading_detail = False
        self._last_compact = None
        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r'[0-9]{0,10}'), self)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        top = EditorToolbar()
        self._btn_open = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._btn_open.setProperty('designAction', 'open')
        self._btn_open.clicked.connect(self._do_open)
        self._btn_save = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._btn_save.clicked.connect(self._do_save)
        self._btn_save.setEnabled(False)
        self._file_label = configure_file_label(QLabel(ui_text('no_file_loaded')))
        for widget in (self._btn_open, self._btn_save, self._file_label):
            top.content_layout.addWidget(widget)
        top.content_layout.addStretch()
        root.addWidget(top)
        root.addWidget(EditorSeparator(accent=True))

        main = configure_layout(QHBoxLayout(), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=290)
        side = sidebar.content_layout
        self._search = configure_search(QLineEdit())
        self._search.setToolTip(ui_text('trophy_search_hint'))
        self._search.textChanged.connect(self._filter_list)
        side.addWidget(self._search)
        self._status_filter = EditorFilterCombo()
        for key in ('all', 'modified', 'new', 'unchanged', 'duplicates'):
            self._status_filter.addItem(ui_text('trophy_filter_' + key), key)
        self._status_filter.currentIndexChanged.connect(self._filter_list)
        side.addWidget(self._status_filter)

        self._sort_combo = configure_input(QComboBox(), monospace=False)
        self._sort_combo.setToolTip(ui_text('trophy_sort_hint'))
        self._sort_combo.setAccessibleName(ui_text('trophy_sort_hint'))
        for key, column, order in (('order', 0, Qt.SortOrder.AscendingOrder),
                                   ('id', 1, Qt.SortOrder.AscendingOrder),
                                   ('value_up', 2, Qt.SortOrder.AscendingOrder),
                                   ('value_down', 2, Qt.SortOrder.DescendingOrder)):
            self._sort_combo.addItem(ui_text('trophy_sort_' + key), (column, order))
        self._sort_combo.currentIndexChanged.connect(self._sort_catalog)
        side.addWidget(self._sort_combo)

        actions = EditorActionRow()
        self._btn_add = self._action('btn_new', self._do_add, 'new')
        self._btn_dup = self._action('btn_duplicate', self._do_dup, 'duplicate')
        self._btn_del = self._action('btn_delete', self._do_del, 'delete', danger=True)
        for button in (self._btn_add, self._btn_dup, self._btn_del):
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)

        self._catalog_model = TrophyTableModel(self)
        self._catalog_proxy = TrophyFilterModel(self)
        self._catalog_proxy.setSourceModel(self._catalog_model)
        self._catalog = EditorRecordList(self._catalog_proxy, self._describe_catalog_row)
        self._catalog.setAccessibleName(ui_text('trophy_catalog_title'))
        self._catalog_proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self._catalog.selectionModel().currentRowChanged.connect(self._on_catalog_selection)
        side.addWidget(self._catalog, 1)
        self._no_matches = self._label(ui_text('trophy_no_matches'))
        self._no_matches.hide()
        side.addWidget(self._no_matches)
        main.addWidget(sidebar)
        main.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))

        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main.addWidget(self._editor_scroll, 1)
        root.addLayout(main, 1)
        self._show_placeholder(ui_text('ui_trophyparam_open_file_to_begin_editing'))
        self._update_actions()

    def _action(self, key, callback, action=None, *, danger=False):
        button = configure_button(QPushButton(ui_text(key)), danger=danger, height=Size.COMPACT_CONTROL)
        if action:
            button.setProperty('designAction', action)
        button.clicked.connect(callback)
        return button

    def _sort_catalog(self, *_):
        column, order = self._sort_combo.currentData()
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_proxy.sort(column, order)
        self._sync_catalog_selection()
        del blocker

    def _describe_catalog_row(self, index):
        source = self._catalog_proxy.mapToSource(index)
        entry = self._entries[source.row()]
        title = ui_text('ui_trophyparam_entry_title', index=source.row(), trophy_id=entry['trophy_id'])
        subtitle = ui_text('ui_trophyparam_entry_subtitle', first=entry['trophy_id'], value=entry['requirement_value'])
        status = self._session.status(entry)
        if status != 'unchanged':
            title = ('● ' if status == 'modified' else '+ ') + title
        return title, subtitle, source.data(Qt.ItemDataRole.ToolTipRole)

    def _label(self, text, *, error=False):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_error_label() if error else ss_dim_label())
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _ensure_session(self):
        if self._result is not None and (self._session is None or self._session.result is not self._result):
            self._session = TrophySession(self._result)
            self._catalog_model.reset_session(self._session)

    def _show_placeholder(self, text):
        self._fields = {}
        self._last_compact = None
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(
            self._editor_widget, title=ui_text('no_file_loaded') if self._raw_data is None else ui_text('ui_trophyparam_no_entries'),
            text=text, icon_name='fa6s.trophy'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_trophyparam_open_title'),
            game_files_dialog_dir(target_patterns=('TrophyParam.bin.xfbin', 'TrophyParam.xfbin')),
            ui_text('ui_trophyparam_file_filter'))
        if path:
            self._load(path)

    def _load(self, path):
        # Failed parsing and cancelled discard both retain the current document.
        try:
            raw, result = parse_trophyparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        if self._dirty and QMessageBox.question(self, ui_text('unsaved_changes_title'),
                ui_text('trophy_discard'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        create_backup_on_open(path)
        self._filepath, self._raw_data, self._result = str(path), raw, result
        self._entries, self._current_idx = result['entries'], None
        self._fields = {}
        self._session = TrophySession(result)
        self._dirty = False
        self._search.clear()
        self._status_filter.setCurrentIndex(0)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text('trophy_empty_hint'))
        self._update_actions()
        return True

    def _do_save(self, target_path=None):
        path = target_path or editor_path(self)
        if not path or self._result is None or not self._apply_current_entry(show_errors=True):
            return False
        try:
            save_trophyparam_xfbin(path, self._raw_data, self._result)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False
        commit_save_path(self, path)
        self._session.mark_saved()
        self._dirty = False
        self._update_actions()
        QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(path)))
        return True

    def _populate_list(self):
        self._ensure_session()
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_model.reset_session(self._session)
        del blocker
        self._filter_list()

    def _filter_list(self, *_):
        if not hasattr(self, '_catalog_proxy'):
            return
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._catalog_proxy.set_filters(self._search.text(), self._status_filter.currentData())
        self._sync_catalog_selection()
        del blocker
        self._no_matches.setVisible(bool(self._entries) and self._catalog_proxy.rowCount() == 0)

    def _sync_catalog_selection(self):
        if self._current_idx is None:
            self._catalog.clearSelection()
            return
        index = self._catalog_proxy.mapFromSource(self._catalog_model.index(self._current_idx, 0))
        if index.isValid():
            self._catalog.setCurrentIndex(index)
            self._catalog.scrollTo(index)
        else:
            self._catalog.clearSelection()
            self._catalog.setCurrentIndex(self._catalog_proxy.index(-1, -1))

    def _on_catalog_selection(self, current, previous):
        if not current.isValid():
            return
        row = self._catalog_proxy.mapToSource(current).row()
        if not self._select_entry(row):
            blocker = QSignalBlocker(self._catalog.selectionModel())
            self._sync_catalog_selection()
            del blocker

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_current_entry(show_errors=True):
            return False
        if idx != self._current_idx or not self._fields:
            self._current_idx = idx
            self._build_editor(idx)
        blocker = QSignalBlocker(self._catalog.selectionModel())
        self._sync_catalog_selection()
        del blocker
        self._update_actions()
        return True

    def _build_editor(self, idx):
        self._ensure_session()
        self._loading_detail = True
        self._fields = {}
        self._last_compact = None
        _clear_layout(self._editor_layout)
        entry = self._entries[idx]
        card, self._field_grid = make_editor_grid_card(self._editor_widget,
            title=ui_text('ui_trophyparam_entry_title', index=idx, trophy_id=entry['trophy_id']),
            icon_name='fa6s.trophy')
        self._title_label = next(label for label in card.findChildren(QLabel)
            if label.text() == ui_text('ui_trophyparam_entry_title', index=idx, trophy_id=entry['trophy_id']))
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        self._field_frames = []
        self._comparisons = {}
        for column, key in enumerate(FIELDS):
            frame, layout, _, _ = make_editor_field_shell(ui_text('ui_trophyparam_' + key))
            edit = configure_input(QLineEdit(str(entry[key])), monospace=True)
            edit.setValidator(self._uint_validator)
            edit.setMaxLength(10)
            edit.setAccessibleName(ui_text('ui_trophyparam_' + key))
            edit.setToolTip(ui_text('ui_trophyparam_' + key + '_hint') + '\n\n' + ui_text('trophy_storage_hint'))
            edit.setProperty('messageReference', False)
            layout.addWidget(IntegerStepper(edit, 0, UINT32_MAX))
            comparison = self._label('')
            layout.addWidget(comparison)
            comparison.hide()
            configure_field(frame, edit, vertical_policy=QSizePolicy.Policy.Minimum)
            self._fields[key], self._comparisons[key] = edit, comparison
            self._field_frames.append(frame)
            self._field_grid.addWidget(frame, 0, column)
            edit.textChanged.connect(self._on_field_text_changed)
        self._editor_layout.addWidget(card)

        self._validation_label = self._label('', error=True)
        self._btn_restore = self._action('trophy_restore', self._restore_entry)
        self._btn_restore.hide()
        self._btn_restore.setToolTip(ui_text('trophy_restore_hint') + '\n\n' + ui_text('trophy_comparison_hint'))
        self._duplicate_label = self._label(ui_text('trophy_duplicate_hint'))
        card.layout().addWidget(self._validation_label)
        card.layout().addWidget(self._btn_restore, 0, Qt.AlignmentFlag.AlignLeft)
        card.layout().addWidget(self._duplicate_label)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow()
        self._refresh_detail()

    def _is_compact_editor(self):
        return self._editor_scroll.viewport().width() < 780

    def eventFilter(self, watched, event):
        if watched is self._editor_scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._fields and not self._loading_detail:
            self._reflow()

    def _reflow(self):
        compact = self._is_compact_editor()
        if compact != self._last_compact:
            for column in range(2):
                self._field_grid.setColumnStretch(column, 0)
            for frame in self._field_frames:
                self._field_grid.removeWidget(frame)
            for index, frame in enumerate(self._field_frames):
                row, column = (index, 0) if compact else (0, index)
                self._field_grid.addWidget(frame, row, column)
                self._field_grid.setColumnStretch(column, 1)
            self._last_compact = compact
        fit_scroll_page(self._editor_scroll)

    def _read_uint(self, key, show_errors=False):
        widget = self._fields.get(key)
        if widget is None:
            return None
        try:
            return uint32(widget.text())
        except ValueError:
            if show_errors:
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('ui_trophyparam_invalid_integer',
                    value=widget.text(), min=0, max=UINT32_MAX))
            return None

    def _apply_current_entry(self, show_errors=False):
        if self._current_idx is None or not self._fields:
            return True
        values = {key: self._read_uint(key, show_errors) for key in FIELDS}
        if any(value is None for value in values.values()):
            return False
        self._entries[self._current_idx].update(values)
        return True

    def _on_field_text_changed(self, *_):
        if self._loading_detail:
            return
        # Commit both words together; incomplete input never silently becomes zero.
        if self._apply_current_entry():
            blocker = QSignalBlocker(self._catalog.selectionModel())
            self._catalog_model.refresh(self._current_idx)
            self._filter_list()
            del blocker
        self._mark_dirty()
        self._refresh_detail()

    def _refresh_detail(self):
        entry = self._entries[self._current_idx]
        self._title_label.setText(ui_text('ui_trophyparam_entry_title', index=self._current_idx, trophy_id=entry['trophy_id']))
        original = self._session.original(entry)
        invalid = []
        for key in FIELDS:
            current = self._read_uint(key)
            self._fields[key].setStyleSheet(ss_input_validation(invalid=current is None))
            if current is None:
                invalid.append(ui_text('ui_trophyparam_' + key))
            if original is None:
                text = ui_text('trophy_no_original')
            elif current is None:
                text = ui_text('trophy_original_only', original=original[key])
            else:
                text = ui_text('trophy_field_comparison', original=original[key], current=current,
                               delta=f'{current - original[key]:+d}')
            self._comparisons[key].setText(text)
            self._comparisons[key].setToolTip(text)
        self._validation_label.setText(ui_text('trophy_invalid_hint', fields=', '.join(invalid)) if invalid else '')
        self._validation_label.setVisible(bool(invalid))
        self._btn_restore.setEnabled(original is not None and (bool(invalid) or self._session.status(entry) != 'unchanged'))
        self._duplicate_label.setVisible(entry['trophy_id'] in self._catalog_model.duplicates)
        fit_scroll_page(self._editor_scroll)

    def _mark_dirty(self):
        self._ensure_session()
        pending = any(self._read_uint(key) is None for key in self._fields)
        self._dirty = bool(self._session and (self._session.dirty() or pending))
        self._update_actions()

    def _update_actions(self):
        loaded = self._raw_data is not None
        selected = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        valid = all(self._read_uint(key) is not None for key in self._fields)
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and selected)
        self._btn_del.setEnabled(loaded and selected)
        self._btn_save.setEnabled(loaded and self._dirty and valid)
        refresh_file_actions(self, loaded=loaded)
        state = (self._filepath, self._dirty)
        if self._filepath and state != getattr(self, '_displayed_file_state', None):
            set_file_label(self._file_label, self._filepath, dirty=self._dirty)
            self._displayed_file_state = state

    def _restore_entry(self):
        original = self._session.original(self._entries[self._current_idx])
        if original is None:
            return
        for key in FIELDS:
            blocker = QSignalBlocker(self._fields[key])
            self._fields[key].setText(str(original[key]))
            del blocker
        self._on_field_text_changed()
        for stepper in self.findChildren(IntegerStepper):
            stepper.refresh()

    def _finish_structure(self, index):
        self._current_idx = None
        self._fields = {}
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(index)
        else:
            self._show_placeholder(ui_text('trophy_empty_hint'))
        self._update_actions()

    def _do_add(self):
        if self._raw_data is None or not self._apply_current_entry(show_errors=True):
            return
        self._ensure_session()
        self._entries.append(make_default_entry(trophy_id=self._session.next_id()))
        self._finish_structure(len(self._entries) - 1)

    def _do_dup(self):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        index = self._current_idx + 1
        self._entries.insert(index, make_default_entry(self._entries[self._current_idx]))
        self._finish_structure(index)

    def _do_del(self):
        if self._current_idx is None or not self._apply_current_entry(show_errors=True):
            return
        index = self._current_idx
        entry = self._entries[index]
        name = ui_text('ui_trophyparam_entry_title', index=index, trophy_id=entry['trophy_id'])
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'), ui_text('msg_confirm_delete_item', name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._entries.pop(index)
        self._finish_structure(min(index, len(self._entries) - 1))
