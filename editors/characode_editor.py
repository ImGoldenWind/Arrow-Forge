import os
import copy
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_toolbar, ss_accent_sep, ss_sep, ss_input, ss_scrollarea, ss_file_label,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonListRow, SkeletonBar
from core.settings import create_backup_on_open, game_files_dialog_dir
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
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class CharacodeEditor(QWidget):
    """Editor for characode.bin.xfbin — character slot assignments."""

    _load_done_signal = pyqtSignal(str, object, object, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {P['bg_dark']};")
        self.t = lang_func

        self._raw_data = None
        self._entries = []
        self._meta = None
        self._current_entry = None
        self._entry_buttons = []
        self._fields = {}
        self._filepath = None
        self._dirty = False

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._build_ui(root_layout)

    # UI construction

    def _build_ui(self, root_layout):
        # Top bar
        top = QFrame(self)
        top.setFixedHeight(46)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        open_btn = QPushButton(self.t("btn_open_file"), top)
        open_btn.setFixedHeight(30)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"), top)
        self._save_btn.setFixedHeight(30)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        sep_v = QFrame(top)
        sep_v.setFixedWidth(1)
        sep_v.setFixedHeight(26)
        sep_v.setStyleSheet(f"background-color: {P['border']};")
        top_layout.addWidget(sep_v)

        self._file_label = QLabel(self.t("no_file_loaded"), top)
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)

        top_layout.addStretch()

        self._count_label = QLabel("", top)
        self._count_label.setFont(QFont("Consolas", 12))
        self._count_label.setStyleSheet(f"color: {P['secondary']}; background-color: transparent;")
        top_layout.addWidget(self._count_label)

        root_layout.addWidget(top)

        # Accent separator
        sep = QFrame(self)
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {P['accent_dim']};")
        root_layout.addWidget(sep)

        # Main area: entry list + editor
        main = QWidget(self)
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar: entry list
        list_frame = QFrame(main)
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(8, 8, 8, 4)
        list_layout.setSpacing(4)

        # Search
        self._search_entry = QLineEdit(list_frame)
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; border-radius: 4px; padding: 2px 6px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        list_layout.addWidget(self._search_entry)

        # Action buttons row
        actions_frame = QWidget(list_frame)
        actions_frame.setStyleSheet("background-color: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self.t("btn_new"), actions_frame)
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_new_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"), actions_frame)
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"), actions_frame)
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_entry)
        actions_layout.addWidget(self._del_btn, 1)
        list_layout.addWidget(actions_frame)

        # Scrollable entry list
        self._entry_scroll = QScrollArea(list_frame)
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 3px; min-height: 20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
        )
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet("background-color: transparent;")
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        list_layout.addWidget(self._entry_scroll)

        main_layout.addWidget(list_frame)

        # Thin separator between list and editor
        vsep = QFrame(main)
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(vsep)

        # Right panel: editor
        self._editor_scroll = QScrollArea(main)
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)

        self._placeholder = QLabel(self.t("placeholder_characode"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']};")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setContentsMargins(0, 60, 0, 60)
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)

        root_layout.addWidget(main, 1)

    # File I/O

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
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)

        hdr = QFrame(self._editor_widget)
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QVBoxLayout(hdr)
        hdr_inner.setContentsMargins(16, 14, 16, 14)
        hdr_inner.addWidget(SkeletonBar(hdr, height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)

        sec = QFrame(self._editor_widget)
        sec.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        sec_lay = QVBoxLayout(sec)
        sec_lay.setContentsMargins(12, 12, 12, 12)
        g = QWidget(sec)
        g.setStyleSheet("background-color: transparent;")
        g_layout = QGridLayout(g)
        g_layout.setContentsMargins(0, 0, 0, 0)
        for col in range(3):
            f = QWidget(g)
            f.setStyleSheet("background-color: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(8, 0, 8, 0)
            f_layout.setSpacing(4)
            f_layout.addWidget(SkeletonBar(f, height=11, corner_radius=3))
            f_layout.addWidget(SkeletonBar(f, height=30, corner_radius=4))
            g_layout.addWidget(f, 0, col)
            g_layout.setColumnStretch(col, 1)
        sec_lay.addWidget(g)
        self._editor_layout.addWidget(sec)

        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        _clear_layout(self._editor_layout)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel(self.t("placeholder_characode"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']};")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setContentsMargins(0, 60, 0, 60)
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()
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
        self._count_label.setText(self.t("entries_count", n=len(entries)))

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    def _save_file(self):
        if not self._raw_data:
            return
        self._apply_fields()
        if not self._filepath:
            return
        try:
            path = self._filepath
            save_characode_xfbin(path, self._raw_data, self._entries, self._meta)
            self._dirty = False
            set_file_label(self._file_label, path)
            QMessageBox.information(self, self.t("dlg_title_success"),
                                    self.t("msg_save_success", path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                  self.t("msg_save_error", error=e))

    # Entry list

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []

        sorted_entries = sorted(self._entries, key=lambda e: e['slot_index'])

        for entry in sorted_entries:
            btn = QPushButton(self._entry_list_widget)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                f"text-align: left; padding: 0px; border: none; }}"
                f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
            )
            btn.clicked.connect(lambda checked, e=entry: self._select_entry(e))

            btn_layout = QVBoxLayout(btn)
            btn_layout.setContentsMargins(10, 3, 10, 3)
            btn_layout.setSpacing(0)

            name_lbl = QLabel(entry['name'])
            name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
            name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            btn_layout.addWidget(name_lbl)

            code_lbl = QLabel(entry['char_code'])
            code_lbl.setFont(QFont("Consolas", 11))
            code_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            code_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            btn_layout.addWidget(code_lbl)

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
            if e is entry:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {P['bg_card']}; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }}"
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }}"
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
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
                    labels[0].setText(entry['name'])
                    labels[1].setText(entry['char_code'])
                break

    # Editor panel

    def _build_editor(self, entry):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)

        # Entry header card
        hdr = QFrame(self._editor_widget)
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)

        hdr_main_layout = QVBoxLayout(hdr)
        hdr_main_layout.setContentsMargins(0, 0, 0, 0)
        hdr_main_layout.addWidget(hdr_inner)

        # Resolved Name (read-only, first and prominent)
        name_frame = QWidget(hdr_inner)
        name_frame.setStyleSheet("background: transparent;")
        name_lay = QVBoxLayout(name_frame)
        name_lay.setContentsMargins(0, 0, 0, 0)
        name_lay.setSpacing(2)
        lbl3 = QLabel(self.t("label_resolved_name"), name_frame)
        lbl3.setFont(QFont("Segoe UI", 12))
        lbl3.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        name_lay.addWidget(lbl3)
        name_val = QLabel(entry['name'], name_frame)
        name_val.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        name_val.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        name_val.setContentsMargins(2, 4, 0, 0)
        name_lay.addWidget(name_val)
        hdr_grid.addWidget(name_frame, 0, 0)
        hdr_grid.setColumnStretch(0, 2)

        # Character Code
        code_frame = QWidget(hdr_inner)
        code_frame.setStyleSheet("background: transparent;")
        code_lay = QVBoxLayout(code_frame)
        code_lay.setContentsMargins(0, 0, 0, 0)
        code_lay.setSpacing(2)
        lbl2 = QLabel(self.t("label_char_code"), code_frame)
        lbl2.setFont(QFont("Segoe UI", 12))
        lbl2.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        code_lay.addWidget(lbl2)
        e_code = QLineEdit(code_frame)
        e_code.setFixedHeight(36)
        e_code.setFont(QFont("Consolas", 16))
        e_code.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; border-radius: 4px; padding: 2px 6px; }}"
        )
        e_code.setText(entry['char_code'])
        e_code.textEdited.connect(self._mark_dirty)
        code_lay.addWidget(e_code)
        self._fields['char_code'] = e_code
        hdr_grid.addWidget(code_frame, 0, 1)
        hdr_grid.setColumnStretch(1, 2)

        # Slot Index
        slot_frame = QWidget(hdr_inner)
        slot_frame.setStyleSheet("background: transparent;")
        slot_lay = QVBoxLayout(slot_frame)
        slot_lay.setContentsMargins(0, 0, 0, 0)
        slot_lay.setSpacing(2)
        lbl = QLabel(self.t("label_slot_index"), slot_frame)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        slot_lay.addWidget(lbl)
        e_slot = QLineEdit(slot_frame)
        e_slot.setFixedHeight(36)
        e_slot.setFixedWidth(100)
        e_slot.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        e_slot.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['accent']}; border-radius: 4px; padding: 2px 6px; }}"
        )
        e_slot.setText(str(entry['slot_index']))
        e_slot.textEdited.connect(self._mark_dirty)
        slot_lay.addWidget(e_slot)
        self._fields['slot_index'] = e_slot
        hdr_grid.addWidget(slot_frame, 0, 2)

        self._editor_layout.addWidget(hdr)
        self._editor_layout.addStretch()

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
        self._count_label.setText(self.t("entries_count", n=len(self._entries)))
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
        self._count_label.setText(self.t("entries_count", n=len(self._entries)))
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
        result = QMessageBox.question(
            self, self.t("dlg_title_confirm_delete"),
            self.t("msg_confirm_delete_slot", slot=slot, code=code))
        if result != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        self._entries.remove(self._current_entry)
        self._current_entry = None
        self._count_label.setText(self.t("entries_count", n=len(self._entries)))
        self._populate_list()
        self._mark_dirty()

    def _mark_dirty(self, *_):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)
