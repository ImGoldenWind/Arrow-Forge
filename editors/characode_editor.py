from core.design_tokens import (
    FontRole,
    Insets,
    LayoutRole,
    Size,
    SkeletonMetrics,
    TypeSize,
    font,
    mono_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field,
    make_empty_state,
    ss_accent_label,
    ss_bg_dark,
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
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import os
import copy
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonListRow, SkeletonBar
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.quiet_unlocks import request_and_cascade
from parsers.characode_parser import (
    parse_characode_xfbin, save_characode_xfbin,
    suggest_next_slot,
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


def _truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 3)] + "..."


class CharacodeEditor(QWidget):
    """Editor for characode.bin.xfbin — character slot assignments."""

    _load_done_signal = pyqtSignal(str, object, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.setStyleSheet(ss_bg_dark())
        self.t = lang_func

        self._raw_data = None
        self._entries = []
        self._meta = None
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._filepath = None
        self._dirty = False
        self._last_editor_compact = None

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        root_layout = QVBoxLayout(self)
        configure_layout(root_layout, LayoutRole.ROOT)

        self._build_ui(root_layout)
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    # UI construction

    def _tr(self, key, fallback, **kwargs):
        value = self.t(key, **kwargs) if kwargs else self.t(key)
        return fallback if value == key else value

    def _build_ui(self, root_layout):
        # Top bar
        top = EditorToolbar(self)
        top_layout = top.content_layout

        open_btn = QPushButton(self.t("btn_open_file"), top)
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(self._load_file)
        open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"), top)
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"), top)
        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label)

        top_layout.addStretch()


        root_layout.addWidget(top)

        # Accent separator
        sep = EditorSeparator(self, accent=True)
        root_layout.addWidget(sep)

        # Main area: entry list + editor
        main = QWidget(self)
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar: entry list
        list_frame = EditorSidebar(main)
        list_layout = list_frame.content_layout

        # Search
        self._search_entry = QLineEdit(list_frame)
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(self._filter_list)
        list_layout.addWidget(self._search_entry)

        # Action buttons row
        actions_frame = EditorActionRow(list_frame)
        actions_layout = actions_frame.content_layout

        self._add_btn = QPushButton(self.t("btn_new"), actions_frame)
        self._add_btn.setEnabled(False)
        configure_button(self._add_btn, height=Size.COMPACT_CONTROL)
        self._add_btn.clicked.connect(self._add_new_entry)
        self._add_btn.setProperty("designAction", 'new')
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"), actions_frame)
        self._dup_btn.setEnabled(False)
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.clicked.connect(self._duplicate_entry)
        self._dup_btn.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"), actions_frame)
        self._del_btn.setEnabled(False)
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.clicked.connect(self._delete_entry)
        self._del_btn.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._del_btn, 1)
        list_layout.addWidget(actions_frame)

        # Scrollable entry list
        self._entry_scroll = QScrollArea(list_frame)
        configure_scrollarea(self._entry_scroll, transparent=True)
        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        configure_layout(self._entry_list_layout, LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        list_layout.addWidget(self._entry_scroll)

        main_layout.addWidget(list_frame)

        # Thin separator between list and editor
        vsep = EditorSeparator(main, orientation=Qt.Orientation.Vertical)
        main_layout.addWidget(vsep)

        # Right panel: editor
        self._editor_scroll = QScrollArea(main)
        configure_scrollarea(self._editor_scroll)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)

        self._show_placeholder()

        main_layout.addWidget(self._editor_scroll, 1)

        root_layout.addWidget(main, 1)

    # File I/O

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        card = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=self.t("placeholder_characode"),
            icon_name="fa6s.id-card",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_characode"), game_files_dialog_dir(target_patterns="characode.bin.xfbin"),
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        create_backup_on_open(path)
        set_file_label_empty(self._file_label, self.t("loading"))
        self._show_list_skeleton()
        self._show_editor_skeleton()

        def worker():
            try:
                raw_data, entries, meta = parse_characode_xfbin(path)
            except Exception as e:
                self._load_error_signal.emit(str(e))
                return
            self._load_done_signal.emit(path, raw_data, entries, meta)

        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []
        for _ in range(12):
            self._entry_list_layout.addWidget(SkeletonListRow())
        self._entry_list_layout.addStretch()

    def _show_editor_skeleton(self):
        _clear_layout(self._editor_layout)
        self._fields = {}
        configure_layout(self._editor_layout, LayoutRole.PAGE)

        hdr, hdr_inner = make_editor_card(self._editor_widget)
        self._prep_card(hdr)
        hdr_inner.addWidget(SkeletonBar(hdr, height=SkeletonMetrics.HEADER_HEIGHT, corner_radius=SkeletonMetrics.HEADER_RADIUS))
        self._editor_layout.addWidget(hdr)

        sec, sec_lay = make_editor_card(self._editor_widget)
        self._prep_card(sec)
        g = QWidget(sec)
        g.setStyleSheet(ss_transparent())
        g_layout = QGridLayout(g)
        configure_layout(g_layout, LayoutRole.GRID)
        for col in range(3):
            f = QWidget(g)
            f.setMinimumWidth(0)
            f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            f.setStyleSheet(ss_transparent())
            f_layout = QVBoxLayout(f)
            configure_layout(f_layout, LayoutRole.SKELETON_FIELD)
            f_layout.addWidget(SkeletonBar(f, height=SkeletonMetrics.LABEL_HEIGHT, corner_radius=SkeletonMetrics.LABEL_RADIUS))
            f_layout.addWidget(SkeletonBar(f, height=SkeletonMetrics.FIELD_HEIGHT, corner_radius=SkeletonMetrics.FIELD_RADIUS))
            g_layout.addWidget(f, 0, col)
            g_layout.setColumnStretch(col, 1)
        sec_lay.addWidget(g)
        self._editor_layout.addWidget(sec)

        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._show_placeholder()
        self._filepath = None
        self._dirty = False
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, raw_data, entries, meta):
        self._raw_data = raw_data
        self._entries = entries
        self._meta = meta
        self._filepath = path
        self._dirty = False
        for entry in self._entries:
            entry['name'] = self.t(f"char_{entry['char_code']}")
        set_file_label(self._file_label, path)

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not self._raw_data:
            return
        self._apply_fields()
        if not save_path:
            return
        try:
            path = save_path
            save_characode_xfbin(path, self._raw_data, self._entries, self._meta)
            commit_save_path(self, save_path)
            self._dirty = False
            set_file_label(self._file_label, path)
            QMessageBox.information(self, self.t('dlg_title_success'), self.t('msg_save_success', path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=e))

    # Entry list

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []

        sorted_entries = sorted(self._entries, key=lambda e: e['slot_index'])

        for entry in sorted_entries:
            btn = EditorListRow(self._entry_list_widget)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda checked, e=entry: self._select_entry(e))
            btn.set_texts(entry['name'], entry['char_code'], title_limit=21, subtitle_limit=24)

            self._entry_list_layout.addWidget(btn)
            self._entry_buttons.append((btn, entry))

        self._entry_list_layout.addStretch()

        if self._entries:
            self._select_entry(sorted_entries[0])

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, entry in self._entry_buttons:
            match = (query in entry['name'].lower()
                     or query in entry['char_code'].lower()
                     or query in str(entry['slot_index']))
            btn.setVisible(match)

    def _select_entry(self, entry):
        self._apply_fields()
        self._current_entry = entry
        for btn, e in self._entry_buttons:
            btn.set_selected(e is entry)
        self._build_editor(entry)

    # Apply field changes back to entry

    def _apply_fields(self):
        if not self._current_entry or not self._fields:
            return
        entry = self._current_entry
        try:
            val = self._fields['slot_index'].text().strip()
            entry['slot_index'] = int(val)
        except (ValueError, KeyError):
            pass
        try:
            code = self._fields['char_code'].text().strip()
            if code:
                entry['char_code'] = code[:7]
                entry['name'] = self.t(f"char_{code[:7]}")
        except KeyError:
            pass
        for btn, e in self._entry_buttons:
            if e is entry:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(_truncate(entry['name'], 21))
                    labels[0].setToolTip(entry['name'])
                    labels[1].setText(_truncate(entry['char_code'], 24))
                    labels[1].setToolTip(entry['char_code'])
                break

    # Editor panel

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < Size.COMPACT_BREAKPOINT

    def _prep_card(self, card):
        return configure_card(card)

    def _prep_field(self, frame, editor=None):
        configure_field(frame, editor)

    def _build_editor(self, entry):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._last_editor_compact = self._is_compact_editor()
        configure_layout(self._editor_layout, LayoutRole.PAGE)

        # Entry header card
        hdr, hdr_main_layout = make_editor_card(self._editor_widget)
        self._prep_card(hdr)
        add_editor_card_title(hdr_main_layout, self.t('label_resolved_name'), 'fa6s.id-card', subtitle=entry['name'])
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet(ss_transparent())
        hdr_grid = QGridLayout(hdr_inner)
        configure_layout(hdr_grid, LayoutRole.GRID)
        compact = self._is_compact_editor()

        # Resolved Name (read-only, first and prominent)
        name_frame = QWidget(hdr_inner)
        name_frame.setMinimumWidth(0)
        name_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name_frame.setStyleSheet(ss_transparent())
        name_lay = QVBoxLayout(name_frame)
        configure_layout(name_lay, LayoutRole.TITLE_TEXT)
        name_val = QLabel(entry['name'], name_frame)
        name_val.setFont(font(FontRole.DISPLAY))
        name_val.setStyleSheet(ss_accent_label())
        name_val.setContentsMargins(*Insets.DISPLAY_VALUE)
        name_val.setWordWrap(True)
        name_lay.addWidget(name_val)
        hdr_grid.addWidget(name_frame, 0, 0, 1, 2)
        hdr_grid.setColumnStretch(0, 2)

        hdr_main_layout.addWidget(hdr_inner)
        self._editor_layout.addWidget(hdr)

        assignment, assignment_layout = make_editor_card(self._editor_widget)
        self._prep_card(assignment)
        add_editor_card_title(assignment_layout, self._tr('ui_characode_slot_assignment', 'Slot Assignment'), 'fa6s.sliders', subtitle=f"{entry['char_code']} / slot {entry['slot_index']}")
        assignment_inner = QWidget(assignment)
        assignment_inner.setStyleSheet(ss_transparent())
        assignment_grid = QGridLayout(assignment_inner)
        configure_layout(assignment_grid, LayoutRole.GRID)

        code_frame, e_code = make_editor_field(self.t('label_char_code'), entry['char_code'], height=Size.LARGE_CONTROL, value_font=mono_font(TypeSize.LARGE))
        e_code.setText(entry['char_code'])
        e_code.setMinimumWidth(0)
        e_code.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        e_code.textEdited.connect(self._mark_dirty)
        self._fields['char_code'] = e_code
        self._prep_field(code_frame, e_code)
        assignment_grid.addWidget(code_frame, 0, 0)
        assignment_grid.setColumnStretch(0, 2)

        slot_frame, e_slot = make_editor_field(self.t('label_slot_index'), entry['slot_index'], height=Size.LARGE_CONTROL, value_font=mono_font(TypeSize.DISPLAY, QFont.Weight.Bold), accent=True)
        e_slot.setText(str(entry['slot_index']))
        e_slot.setMinimumWidth(0)
        e_slot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        e_slot.textEdited.connect(self._mark_dirty)
        self._fields['slot_index'] = e_slot
        self._prep_field(slot_frame, e_slot)
        assignment_grid.addWidget(slot_frame, 1 if compact else 0, 0 if compact else 1)
        assignment_grid.setColumnStretch(1, 1)

        assignment_layout.addWidget(assignment_inner)
        self._editor_layout.addWidget(assignment)
        self._editor_layout.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_entry is not None and self._last_editor_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_entry is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_editor_compact:
            return
        self._build_editor(self._current_entry)

    # Add / Duplicate / Delete

    def _add_new_entry(self):
        if self._raw_data is None:
            return
        self._apply_fields()
        next_slot = suggest_next_slot(self._entries)
        entry = {
            'slot_index': next_slot,
            'char_code': 'new01',
            'name': 'new01',
        }
        self._entries.append(entry)
        self._populate_list()
        self._select_entry(entry)
        self._mark_dirty()

    def _duplicate_entry(self):
        if self._raw_data is None or not self._current_entry:
            return
        self._apply_fields()
        src = self._current_entry
        entry = copy.deepcopy(src)
        entry['slot_index'] = suggest_next_slot(self._entries)
        entry['name'] = src['name'] + self.t("msg_copy_suffix")
        self._entries.append(entry)
        self._populate_list()
        self._select_entry(entry)
        self._mark_dirty()

    def _delete_entry(self):
        if self._raw_data is None or not self._current_entry:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("msg_cannot_delete_last_entry"))
            return
        code = self._current_entry['char_code']
        slot = self._current_entry['slot_index']
        name = self._current_entry.get("name", "")
        result = QMessageBox.question(
            self, self.t("dlg_title_confirm_delete"),
            self.t("msg_confirm_delete_slot", slot=slot, code=code))
        if result != QMessageBox.StandardButton.Yes:
            return
        if code == "3slc01" or name == "Silver Chariot":
            request_and_cascade(self, "Chariot Requiem")
        self._fields = {}
        self._entries.remove(self._current_entry)
        self._current_entry = None
        self._populate_list()
        self._mark_dirty()

    def _mark_dirty(self, *_):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)
