"""Projectile Editor: focused forms for embedded Skill XML."""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
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
    configure_file_label,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import install_file_actions
import copy
import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.themes import P
from core.editor_file_state import set_file_label
from core.projectile_tools import parse_skill, skill_xml, unique_skill_id
from core.spm_tools import SpmNames
from parsers.projectile_parser import parse_projectile_xfbin, save_projectile_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
from editors.projectile_forms import _SkillTable, clear_layout as _clear_layout


def _truncate(text, limit=28):
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


_DEFAULT_SKILL_XML = ('<?xml version="1.0" encoding="Shift_JIS"?>\r\n'
    '<Skill id="new_skill" type="SKILL_TYPE_EFFECT">'
    '<Actions FirstActionId="0" num="1"><Action id="0" type="SKILL_ACTION_TYPE_ARROW"></Action></Actions>'
    '<GenActions num="0"></GenActions></Skill>')


class ProjectileEditor(QWidget):
    _load_done_signal  = pyqtSignal(str, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self._embedded = embedded
        self.t = lang_func or ui_text

        self._filepath      = None
        self._raw_data      = None
        self._chunks        = []
        self._cur_idx       = -1
        self._current_chunk = None
        self._dirty         = False
        self._skill_buttons = []
        self._loading = False
        self._names = None

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()
        install_file_actions(self, self._save_btn, existing_button=self._save_as_btn)
        install_editor_chrome(self)

    # UI Construction

    def closeEvent(self, event):
        if not self._embedded and not self._can_leave():
            event.ignore()
            return
        super().closeEvent(event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Top bar
        top = EditorToolbar()
        tl = top.content_layout

        open_btn = QPushButton(self.t("btn_open_file"))
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(self._load_file)
        open_btn.setProperty("designAction", 'open')
        tl.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)
        self._save_as_btn = QPushButton(ui_text("proj_save_as"))
        configure_button(self._save_as_btn)
        self._save_as_btn.setEnabled(False)
        self._save_as_btn.clicked.connect(self._save_as)
        tl.addWidget(self._save_as_btn)

        self._file_lbl = QLabel(self.t("no_file_loaded"))

        configure_file_label(self._file_lbl)
        tl.addWidget(self._file_lbl)

        tl.addStretch()
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Main area: sidebar + editor (always visible)
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar
        left_frame = EditorSidebar(width=276)


        lf_layout = left_frame.content_layout


        self._search_entry = QLineEdit()
        configure_search(self._search_entry)
        self._search_entry.setClearButtonEnabled(True)
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(self._filter_skill_list)
        lf_layout.addWidget(self._search_entry)

        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._skill_add_btn = QPushButton(self.t("btn_new"))
        self._skill_add_btn.setEnabled(False)
        configure_button(self._skill_add_btn, height=Size.COMPACT_CONTROL)
        self._skill_add_btn.clicked.connect(self._add_skill)
        self._skill_add_btn.setProperty("designAction", 'new')
        actions_layout.addWidget(self._skill_add_btn, 1)

        self._skill_dup_btn = QPushButton(self.t("btn_duplicate"))
        self._skill_dup_btn.setEnabled(False)
        configure_button(self._skill_dup_btn, height=Size.COMPACT_CONTROL)
        self._skill_dup_btn.clicked.connect(self._dup_skill)
        self._skill_dup_btn.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._skill_dup_btn, 1)

        self._skill_del_btn = QPushButton(self.t("btn_delete"))
        self._skill_del_btn.setEnabled(False)
        configure_button(self._skill_del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._skill_del_btn.clicked.connect(self._del_skill)
        self._skill_del_btn.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._skill_del_btn, 1)

        lf_layout.addWidget(actions_frame)

        self._skill_scroll = QScrollArea()


        configure_scrollarea(self._skill_scroll, transparent=True)
        self._skill_list_widget = QWidget()
        self._skill_list_widget.setStyleSheet(ss_transparent())
        self._skill_list_layout = QVBoxLayout(self._skill_list_widget)
        configure_layout(self._skill_list_layout, LayoutRole.LIST)
        self._skill_list_layout.addStretch()
        self._skill_scroll.setWidget(self._skill_list_widget)
        lf_layout.addWidget(self._skill_scroll)

        main_layout.addWidget(left_frame)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        # Right: placeholder OR skill editor
        right_frame = QFrame()
        right_frame.setStyleSheet(ss_bg_dark())
        right_layout = QVBoxLayout(right_frame)
        configure_layout(right_layout, LayoutRole.ROOT)

        self._placeholder_wrap = QWidget(right_frame)
        self._placeholder_wrap.setStyleSheet(ss_transparent())
        placeholder_layout = QVBoxLayout(self._placeholder_wrap)
        placeholder_layout.setContentsMargins(*Insets.NONE)
        placeholder_layout.addStretch()
        self._placeholder = make_empty_state(
            self._placeholder_wrap,
            title=self.t("no_file_loaded"),
            text=ui_text("ui_projectile_open_a_projectile_xfbin_file_to_begin_editing"),
            icon_name="fa6s.crosshairs",
        )
        placeholder_layout.addWidget(self._placeholder, 0, Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addStretch()
        right_layout.addWidget(self._placeholder_wrap, 1)

        self._skill_table = _SkillTable(lang_func=self.t)
        self._skill_table.setVisible(False)
        self._skill_table.xml_changed.connect(self._on_table_xml_changed)
        self._skill_table.skill_id_changed.connect(self._on_skill_id_changed)
        self._skill_table.validity_changed.connect(lambda valid: self._update_save_buttons())
        right_layout.addWidget(self._skill_table, 1)

        main_layout.addWidget(right_frame, 1)
        root.addWidget(main, 1)

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_projectile_open_projectile_xfbin"), game_files_dialog_dir(target_patterns="*_x.xfbin"),
            "Projectile files (*_x.xfbin *.xfbin);;All files (*.*)"
        )
        if path:
            create_backup_on_open(path)
            self._start_load(path)

    def _start_load(self, path):
        if self._loading or not self._can_leave():
            return
        self._loading = True
        self._skill_table.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._save_as_btn.setEnabled(False)
        for button in (self._skill_add_btn, self._skill_dup_btn, self._skill_del_btn):
            button.setEnabled(False)
        name = os.path.basename(path)
        self._file_lbl.setText(ui_text("ui_customcardparam_value_value", p0=self.t('loading'), p1=name))
        configure_file_label(self._file_lbl)

        def _worker():
            try:
                raw, chunks = parse_projectile_xfbin(path)
                if not chunks:
                    raise ValueError(ui_text("proj_no_skills"))
                self._load_done_signal.emit(path, raw, chunks)
            except Exception as exc:
                import traceback
                self._load_error_signal.emit(f"{exc}\n{traceback.format_exc()}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path, raw, chunks):
        self._loading = False
        self._filepath = path
        self._names = SpmNames(path)
        self._skill_table.setEnabled(True)
        self._search_entry.clear()
        self._raw_data      = raw
        self._chunks        = chunks
        self._cur_idx       = -1
        self._current_chunk = None
        self._dirty         = False

        set_file_label(self._file_lbl, path)

        self._placeholder_wrap.setVisible(False)
        self._skill_table.setVisible(True)

        self._save_btn.setEnabled(False)
        self._save_as_btn.setEnabled(True)
        self._skill_add_btn.setEnabled(True)
        self._skill_dup_btn.setEnabled(True)
        self._skill_del_btn.setEnabled(True)

        self._populate_skill_list()

    def _on_load_error(self, msg):
        self._loading = False
        self._skill_table.setEnabled(True)
        set_file_label(self._file_lbl, self._filepath, dirty=self._dirty)
        for button in (self._skill_add_btn, self._skill_dup_btn, self._skill_del_btn):
            button.setEnabled(bool(self._chunks))
        self._update_save_buttons()
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    # Skill list

    def _clear_skill_list(self):
        _clear_layout(self._skill_list_layout)
        self._skill_list_layout.addStretch()

    def _populate_skill_list(self, selected=None):
        self._clear_skill_list()
        self._skill_buttons = []
        for chunk in self._chunks:
            btn = self._make_skill_button(chunk)
            self._skill_list_layout.insertWidget(
                self._skill_list_layout.count() - 1, btn
            )
            self._skill_buttons.append((btn, chunk))
        if self._chunks:
            self._select_skill(selected if selected is not None else self._chunks[0])
        self._filter_skill_list()

    def _make_skill_button(self, chunk):
        btn = EditorListRow(height=68)

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        btn_layout = btn.content_layout


        full_name = chunk['skill_id']
        root = parse_skill(chunk['xml_text'])
        details = root.find('Details')
        description = details.get('text', '') if details is not None else ''
        chunk['_description'] = description
        display_description = self._names.display(description) if self._names else description
        chunk['_display_description'] = display_description
        name_lbl = btn.add_title(_truncate(full_name, 26))
        name_lbl.setToolTip(full_name)


        description_lbl = QLabel(_truncate(display_description, 34) or ui_text("proj_no_description"))
        description_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        configure_file_label(description_lbl)
        btn_layout.addWidget(description_lbl)
        btn.setToolTip(full_name + "\n" + display_description + "\n" + description)

        btn.clicked.connect(lambda checked=False, c=chunk: self._select_skill(c))
        return btn

    def _filter_skill_list(self):
        query = self._search_entry.text().lower()
        for btn, chunk in self._skill_buttons:
            haystack = (chunk['skill_id'] + ' ' + chunk.get('_description', '') + ' ' + chunk.get('_display_description', '')).lower()
            btn.setVisible(query in haystack)
        count = sum(query in (c['skill_id'] + ' ' + c.get('_description', '') + ' ' + c.get('_display_description', '')).lower() for c in self._chunks)

    def _select_skill(self, chunk):
        if self._skill_table.has_invalid:
            self._skill_table._update_status()
            return
        self._current_chunk = chunk
        self._cur_idx = self._chunks.index(chunk)

        for btn, c in self._skill_buttons:
            try:
                btn.setStyleSheet(ss_sidebar_btn(selected=(c is chunk)))
            except Exception:
                pass

        original_id = chunk['skill_id']
        self._skill_table.id_validator = lambda value: value == original_id or all(
            c is chunk or c['skill_id'] != value for c in self._chunks)
        self._skill_table.load(chunk['xml_text'])

    # Table ↔ chunk sync

    def _on_table_xml_changed(self, new_xml):
        if 0 <= self._cur_idx < len(self._chunks):
            chunk = self._chunks[self._cur_idx]
            chunk['xml_text'] = new_xml
            root = parse_skill(new_xml)
            details = root.find('Details')
            chunk['_description'] = details.get('text', '') if details is not None else ''
            display_description = self._names.display(chunk['_description']) if self._names else chunk['_description']
            chunk['_display_description'] = display_description
            for btn, c in self._skill_buttons:
                if c is chunk:
                    labels = btn.findChildren(QLabel)
                    if len(labels) > 1:
                        labels[1].setText(_truncate(display_description, 34) or ui_text("proj_no_description"))
                    btn.setToolTip(chunk['skill_id'] + "\n" + display_description + "\n" + chunk['_description'])
            self._filter_skill_list()
            self._mark_dirty()

    def _on_skill_id_changed(self, new_id):
        if 0 <= self._cur_idx < len(self._chunks):
            chunk = self._chunks[self._cur_idx]
            chunk['skill_id'] = new_id
            for btn, c in self._skill_buttons:
                if c is chunk:
                    labels = btn.findChildren(QLabel)
                    if labels:
                        labels[0].setText(_truncate(new_id, 26))
                        labels[0].setToolTip(new_id)
                    break

    # Add / Dup / Delete skills

    def _add_skill(self):
        if self._raw_data is None or self._loading or self._skill_table.has_invalid:
            return
        new_chunk = {
            'skill_id':  unique_skill_id(self._chunks, 'new_skill'),
            'xml_start': 0,
            'xml_end':   0,
            'xml_text':  _DEFAULT_SKILL_XML,
        }
        root = parse_skill(new_chunk['xml_text'])
        root.set('id', new_chunk['skill_id'])
        new_chunk['xml_text'] = skill_xml(root)
        self._chunks.append(new_chunk)
        self._search_entry.clear()
        self._populate_skill_list(new_chunk)
        self._mark_dirty()

    def _dup_skill(self):
        if not self._chunks or self._current_chunk is None or self._skill_table.has_invalid or self._loading:
            return
        new_chunk = copy.deepcopy(self._current_chunk)
        new_chunk['skill_id'] = unique_skill_id(self._chunks, new_chunk['skill_id'])
        root = parse_skill(new_chunk['xml_text'])
        root.set('id', new_chunk['skill_id'])
        new_chunk['xml_text'] = skill_xml(root)
        self._chunks.append(new_chunk)
        self._search_entry.clear()
        self._populate_skill_list(new_chunk)
        self._mark_dirty()

    def _del_skill(self):
        if not self._chunks or self._current_chunk is None or self._skill_table.has_invalid or self._loading:
            return
        if len(self._chunks) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_projectile_cannot_delete_the_last_skill"))
            return
        name = self._current_chunk['skill_id']
        result = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"), ui_text("ui_projectile_delete_skill_value", p0=name)
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._chunks.remove(self._current_chunk)
        self._current_chunk = None
        self._cur_idx = -1
        self._populate_skill_list()
        self._mark_dirty()

    # Save

    def _update_save_buttons(self):
        if self._skill_table.has_invalid and not self._dirty:
            self._dirty = True
            set_file_label(self._file_lbl, self._filepath, dirty=True)
        valid = bool(self._chunks) and not self._loading and not self._skill_table.has_invalid
        self._save_btn.setEnabled(valid and self._dirty)
        self._save_as_btn.setEnabled(valid)

    def _can_leave(self):
        if self._skill_table.has_invalid:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("proj_invalid"))
            return False
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, ui_text("proj_unsaved"), ui_text("proj_unsaved_hint"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self._do_save(self._filepath)
        return answer == QMessageBox.StandardButton.Discard

    def _save_file(self):
        if self._chunks and self._filepath and not self._skill_table.has_invalid and not self._loading:
            return self._do_save(self._filepath)
        return False

    def _save_as(self):
        if not self._chunks or self._skill_table.has_invalid or self._loading:
            return
        path, _ = QFileDialog.getSaveFileName(self, ui_text("proj_save_as"),
            self._filepath or '', 'XFBIN (*.xfbin)')
        if path:
            self._do_save(path)

    def _do_save(self, path):
        if self._skill_table.has_invalid or self._loading:
            return False
        try:
            save_projectile_xfbin(path, self._raw_data, self._chunks)
            selected = self._cur_idx
            raw, chunks = parse_projectile_xfbin(path)
            self._raw_data = raw
            self._chunks = chunks
            self._filepath = path
            self._dirty = False
            self._populate_skill_list(chunks[min(selected, len(chunks) - 1)])
            set_file_label(self._file_lbl, path)
            self._update_save_buttons()
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(exc))
            return False

    def _mark_dirty(self):
        self._dirty = True
        set_file_label(self._file_lbl, self._filepath, dirty=True)
        self._update_save_buttons()
