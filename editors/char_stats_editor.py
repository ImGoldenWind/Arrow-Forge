import os
import copy
import json
import struct
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.themes import P
from core.style_helpers import ss_btn, ss_toolbar, ss_accent_sep, ss_sep, ss_input
from core.skeleton import SkeletonListRow, SkeletonBar
from parsers.xfbin_parser import parse_xfbin, save_xfbin, CHUNK_SIZE
from core.translations import ui_text


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class CharacterStatsEditor(QWidget):
    _load_done_signal = pyqtSignal(str, object, object)   # path, xfbin_data, characters
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t = lang_func

        self._xfbin_data = None
        self._characters = []
        self._current_char = None
        self._fields = {}
        self._char_buttons = []

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setFixedHeight(46)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        open_btn = QPushButton(self.t("btn_open_file"))
        open_btn.setFixedHeight(30)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(30)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(f"color: {P['text_dim']};")
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        root_layout.addWidget(top)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {P['mid']};")
        root_layout.addWidget(sep)

        # Main area: character list + editor
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Character list sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        # Search
        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search_entry)

        # Action buttons
        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_new_char)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_char)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_char)
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

        # Thin divider between sidebar and editor
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Editor panel (scrollable)
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

        self._placeholder = QLabel(self.t("placeholder_char_stats"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)

        root_layout.addWidget(main, 1)

    # Helpers

    def _clear_char_list(self):
        _clear_layout(self._char_list_layout)
        self._char_list_layout.addStretch()

    def _clear_editor(self):
        _clear_layout(self._editor_layout)

    @staticmethod
    def _labels_path(xfbin_path):
        return os.path.splitext(xfbin_path)[0] + '.labels.json'

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_char_stats"), "",
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        self._file_label.setText(self.t("loading"))
        self._show_list_skeleton()
        self._show_editor_skeleton()

        def worker():
            try:
                xfbin_data, characters = parse_xfbin(path)
            except Exception as e:
                self._load_error_signal.emit(str(e))
                return

            for char in characters:
                key = f"char_{char['char_id']}"
                translated = self.t(key)
                if translated != key:
                    char['name'] = translated

            labels_path = self._labels_path(path)
            if os.path.isfile(labels_path):
                try:
                    with open(labels_path, 'r', encoding='utf-8') as f:
                        labels = json.load(f)
                    for char in characters:
                        if char['char_id'] in labels:
                            char['name'] = labels[char['char_id']]
                except Exception:
                    pass

            self._load_done_signal.emit(path, xfbin_data, characters)

        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        self._clear_char_list()
        self._char_buttons = []
        # Insert skeleton rows before the stretch
        for _ in range(10):
            row = SkeletonListRow()
            self._char_list_layout.insertWidget(self._char_list_layout.count() - 1, row)

    def _show_editor_skeleton(self):
        self._clear_editor()
        self._fields = {}

        hdr = QFrame()
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 14, 16, 14)
        hdr_layout.addWidget(SkeletonBar(height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)

        for _ in range(3):
            sec = QFrame()
            sec.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
            sec_layout = QVBoxLayout(sec)
            sec_layout.setContentsMargins(12, 12, 12, 12)

            g = QWidget()
            g_layout = QGridLayout(g)
            g_layout.setContentsMargins(0, 0, 0, 0)
            for col in range(3):
                f = QWidget()
                f_layout = QVBoxLayout(f)
                f_layout.setContentsMargins(8, 0, 8, 0)
                f_layout.setSpacing(4)
                f_layout.addWidget(SkeletonBar(height=11, corner_radius=3))
                f_layout.addWidget(SkeletonBar(height=30, corner_radius=4))
                g_layout.addWidget(f, 0, col)
                g_layout.setColumnStretch(col, 1)

            sec_layout.addWidget(g)
            self._editor_layout.addWidget(sec)

        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        self._clear_char_list()
        self._clear_editor()
        self._placeholder = QLabel(self.t("placeholder_char_stats"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()
        self._file_label.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"),
                             self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, xfbin_data, characters):
        self._xfbin_data = xfbin_data
        self._characters = characters
        self._file_label.setText(os.path.basename(path))

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    def _save_file(self):
        if not self._xfbin_data:
            return
        self._apply_fields()
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file_save_char_stats"), "",
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return
        try:
            save_xfbin(path, self._xfbin_data, self._characters)
            labels = {char['char_id']: char['name'] for char in self._characters}
            with open(self._labels_path(path), 'w', encoding='utf-8') as f:
                json.dump(labels, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, self.t("dlg_title_success"),
                                    self.t("msg_save_success", path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                 self.t("msg_save_error", error=e))

    # Character list

    def _populate_list(self):
        self._clear_char_list()
        self._char_buttons = []
        for char in self._characters:
            btn = self._make_char_button(char)
            # Insert before the trailing stretch
            self._char_list_layout.insertWidget(self._char_list_layout.count() - 1, btn)
            self._char_buttons.append((btn, char))
        if self._characters:
            self._select_char(self._characters[0])

    def _make_char_button(self, char):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border-radius: 6px; "
            f"text-align: left; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        name_lbl = QLabel(char['name'])
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        id_lbl = QLabel(char['char_id'])
        id_lbl.setFont(QFont("Consolas", 11))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(id_lbl)

        btn.clicked.connect(lambda checked=False, c=char: self._select_char(c))
        return btn

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, char in self._char_buttons:
            match = query in char['name'].lower() or query in char['char_id'].lower()
            btn.setVisible(match)

    def _select_char(self, char):
        self._apply_fields()
        self._current_char = char
        for btn, c in self._char_buttons:
            try:
                if c is char:
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
            except Exception:
                pass
        self._build_editor(char)

    def _apply_fields(self):
        if not self._current_char or not self._fields:
            return
        char = self._current_char
        for key, entry in self._fields.items():
            try:
                val = entry.text()
                parts = key.split('.')
                if parts[0] == 'mb':
                    bi, field = int(parts[1]), parts[2]
                    if field in ('gravity_strength', 'jump_upward_vel', 'jump_forward_vel',
                                 'dash_jump_height', 'dash_jump_dist'):
                        char['movement_blocks'][bi][field] = float(val)
                    else:
                        char['movement_blocks'][bi][field] = int(val)
                elif parts[0] == 'bone':
                    bi, field = int(parts[1]), parts[2]
                    if field == 'name':
                        char['bones'][bi][field] = val
                    else:
                        char['bones'][bi][field] = int(val)
                elif parts[0] == 'uf':
                    char['unk_floats'][int(parts[1])] = float(val)
                elif key in ('dmg_scaling_1', 'dmg_scaling_2', 'dmg_scaling_3'):
                    char[key] = float(val)
                elif key == 'char_id':
                    char['char_id'] = val[:7]
                    if char.get('variants'):
                        char['variants'][0] = val[:7]
                elif key == '_display_name':
                    char['name'] = val
                elif key == 'corpse_parts':
                    char[key] = val
                else:
                    char[key] = int(val)
            except (ValueError, IndexError):
                pass
        # Update sidebar button labels to reflect name/id changes
        for btn, c in self._char_buttons:
            if c is char:
                # Update name and id labels inside the button
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(char['name'])
                    labels[1].setText(char['char_id'])
                break

    # Editor

    def _build_editor(self, char):
        self._clear_editor()
        self._fields = {}

        # Character header - editable identity fields
        hdr = QFrame()
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)

        hdr_main_layout = QVBoxLayout(hdr)
        hdr_main_layout.setContentsMargins(0, 0, 0, 0)
        hdr_main_layout.addWidget(hdr_inner)

        # Display Name
        name_frame = QWidget()
        name_frame.setStyleSheet("background: transparent;")
        name_layout = QVBoxLayout(name_frame)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(2)
        lbl = QLabel(self.t("label_display_name_cosmetic"))
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        name_layout.addWidget(lbl)
        e_name = QLineEdit()
        e_name.setFixedHeight(36)
        e_name.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        e_name.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['accent']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_name.setText(char['name'])
        name_layout.addWidget(e_name)
        self._fields['_display_name'] = e_name
        hdr_grid.addWidget(name_frame, 0, 0)
        hdr_grid.setColumnStretch(0, 1)

        # Char ID
        id_frame = QWidget()
        id_frame.setStyleSheet("background: transparent;")
        id_layout = QVBoxLayout(id_frame)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(2)
        lbl = QLabel(self.t("label_char_id_saved"))
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        id_layout.addWidget(lbl)
        e_id = QLineEdit()
        e_id.setFixedHeight(36)
        e_id.setFont(QFont("Consolas", 16))
        e_id.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_id.setText(char['char_id'])
        id_layout.addWidget(e_id)
        self._fields['char_id'] = e_id
        hdr_grid.addWidget(id_frame, 0, 1)
        hdr_grid.setColumnStretch(1, 1)

        # Param ID
        pid_frame = QWidget()
        pid_frame.setStyleSheet("background: transparent;")
        pid_layout = QVBoxLayout(pid_frame)
        pid_layout.setContentsMargins(0, 0, 0, 0)
        pid_layout.setSpacing(2)
        lbl = QLabel(self.t("label_param_id"))
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        pid_layout.addWidget(lbl)
        e_pid = QLineEdit()
        e_pid.setFixedHeight(36)
        e_pid.setFont(QFont("Consolas", 16))
        e_pid.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_pid.setText(str(char['param_id']))
        pid_layout.addWidget(e_pid)
        self._fields['param_id'] = e_pid
        hdr_grid.addWidget(pid_frame, 0, 2)

        self._editor_layout.addWidget(hdr)

        # Combat Stats
        self._add_section(self.t("section_combat_stats"))
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        stats_inner = QWidget(stats_frame)
        stats_inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(stats_inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        stats_main = QVBoxLayout(stats_frame)
        stats_main.setContentsMargins(0, 0, 0, 0)
        stats_main.addWidget(stats_inner)

        stat_fields = [
            ("hp", self.t("field_hp"), char['hp']),
            ("gha_damage", self.t("field_gha_damage"), char['gha_damage']),
            ("max_gauge", self.t("field_max_gauge"), char['max_gauge']),
            ("guard_gauge", self.t("field_guard_gauge"), char['guard_gauge']),
            ("guard_break_recovery", self.t("field_guard_break_recovery"), char['guard_break_recovery']),
            ("dmg_scaling_1", self.t("field_dmg_scale_1"), f"{char['dmg_scaling_1']:.2f}"),
            ("dmg_scaling_2", self.t("field_dmg_scale_2"), f"{char['dmg_scaling_2']:.2f}"),
            ("dmg_scaling_3", self.t("field_dmg_scale_3"), f"{char['dmg_scaling_3']:.2f}"),
        ]
        for i, (key, label, val) in enumerate(stat_fields):
            row, col = divmod(i, 3)
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(0, 0, 0, 0)
            f_layout.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            f_layout.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            f_layout.addWidget(e)
            grid.addWidget(f, row, col)
            grid.setColumnStretch(col, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(stats_frame)

        # Unknown Floats
        self._add_section(self.t("section_unk_floats"))
        uf_frame = QFrame()
        uf_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        uf_inner = QWidget(uf_frame)
        uf_inner.setStyleSheet("background: transparent;")
        uf_grid = QGridLayout(uf_inner)
        uf_grid.setContentsMargins(12, 12, 12, 12)
        uf_grid.setHorizontalSpacing(16)
        uf_grid.setVerticalSpacing(8)
        uf_main = QVBoxLayout(uf_frame)
        uf_main.setContentsMargins(0, 0, 0, 0)
        uf_main.addWidget(uf_inner)

        for i, val in enumerate(char['unk_floats']):
            row, col = divmod(i, 4)
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(0, 0, 0, 0)
            f_layout.setSpacing(2)
            lbl = QLabel(self.t("field_unk_float_n", n=i + 1))
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            f_layout.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(ui_text("ui_char_stats_value", p0=val))
            f_layout.addWidget(e)
            uf_grid.addWidget(f, row, col)
            uf_grid.setColumnStretch(col, 1)
            self._fields[f"uf.{i}"] = e

        self._editor_layout.addWidget(uf_frame)

        # Collision
        self._add_section(self.t("section_collision"))
        col_frame = QFrame()
        col_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        col_inner = QWidget(col_frame)
        col_inner.setStyleSheet("background: transparent;")
        col_grid = QGridLayout(col_inner)
        col_grid.setContentsMargins(12, 12, 12, 12)
        col_grid.setHorizontalSpacing(16)
        col_grid.setVerticalSpacing(8)
        col_main = QVBoxLayout(col_frame)
        col_main.setContentsMargins(0, 0, 0, 0)
        col_main.addWidget(col_inner)

        for ci, (key, label, val) in enumerate([
            ("collision_threshold", self.t("field_collision_threshold"), char['collision_threshold']),
            ("camera_height",       self.t("field_camera_height"),       char['camera_height']),
            ("collision_size",      self.t("field_collision_size"),      char['collision_size']),
        ]):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(0, 0, 0, 0)
            f_layout.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            f_layout.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            f_layout.addWidget(e)
            col_grid.addWidget(f, 0, ci)
            col_grid.setColumnStretch(ci, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(col_frame)

        # Hitbox Bones
        self._add_section(self.t("section_hitbox_bones"))
        bones_frame = QFrame()
        bones_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        bones_inner = QWidget(bones_frame)
        bones_inner.setStyleSheet("background: transparent;")
        bg = QGridLayout(bones_inner)
        bg.setContentsMargins(12, 12, 12, 12)
        bg.setHorizontalSpacing(12)
        bg.setVerticalSpacing(4)

        bones_main = QVBoxLayout(bones_frame)
        bones_main.setContentsMargins(0, 0, 0, 0)
        bones_main.addWidget(bones_inner)

        for col, hdr_text in enumerate([self.t("bone_col_bone"), self.t("bone_col_name"),
                                        self.t("bone_col_size1"), self.t("bone_col_size2")]):
            lbl = QLabel(hdr_text)
            lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {P['text_dim']};")
            bg.addWidget(lbl, 0, col)
            bg.setColumnStretch(col, 1 if col == 1 else 0)

        for bi, bone in enumerate(char['bones']):
            lbl = QLabel(bone['label'])
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            bg.addWidget(lbl, bi + 1, 0)

            for ci, (field, val) in enumerate([('name', bone['name']),
                                                ('size_1', bone['size_1']),
                                                ('size_2', bone['size_2'])]):
                e = QLineEdit()
                e.setFixedHeight(28)
                e.setFont(QFont("Consolas", 12))
                e.setStyleSheet(
                    f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                    f"color: {P['text_main']}; padding: 2px 4px; border-radius: 4px; }}"
                )
                if ci > 0:
                    e.setFixedWidth(100)
                else:
                    e.setMinimumWidth(140)
                e.setText(str(val))
                bg.addWidget(e, bi + 1, ci + 1)
                self._fields[f"bone.{bi}.{field}"] = e

        self._editor_layout.addWidget(bones_frame)

        # Movement Blocks
        block_labels = {
            'fwd_walk':         self.t("field_fwd_walk"),
            'bwd_walk':         self.t("field_bwd_walk"),
            'fwd_run':          self.t("field_fwd_run"),
            'bwd_run':          self.t("field_bwd_run"),
            'gravity_strength': self.t("field_gravity_strength"),
            'jump_upward_vel':  self.t("field_jump_upward_vel"),
            'jump_forward_vel': self.t("field_jump_forward_vel"),
            'dash_jump_height': self.t("field_dash_jump_height"),
            'dash_jump_dist':   self.t("field_dash_jump_dist"),
        }
        for bi, block in enumerate(char['movement_blocks']):
            self._add_section(self.t("section_movement_label", label=block['label']))
            mf = QFrame()
            mf.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
            mf_inner = QWidget(mf)
            mf_inner.setStyleSheet("background: transparent;")
            mg = QGridLayout(mf_inner)
            mg.setContentsMargins(12, 12, 12, 12)
            mg.setHorizontalSpacing(16)
            mg.setVerticalSpacing(8)

            mf_main = QVBoxLayout(mf)
            mf_main.setContentsMargins(0, 0, 0, 0)
            mf_main.addWidget(mf_inner)

            fields_list = ['fwd_walk', 'bwd_walk', 'fwd_run', 'bwd_run', 'gravity_strength',
                           'jump_upward_vel', 'jump_forward_vel', 'dash_jump_height', 'dash_jump_dist']
            for fi, field in enumerate(fields_list):
                row, col = divmod(fi, 3)
                ff = QWidget()
                ff.setStyleSheet("background: transparent;")
                ff_layout = QVBoxLayout(ff)
                ff_layout.setContentsMargins(0, 0, 0, 0)
                ff_layout.setSpacing(2)
                val = block[field]
                display = f"{val:.2f}" if isinstance(val, float) else str(val)
                lbl = QLabel(block_labels[field])
                lbl.setFont(QFont("Segoe UI", 12))
                lbl.setStyleSheet(f"color: {P['text_sec']};")
                ff_layout.addWidget(lbl)
                e = QLineEdit()
                e.setFixedHeight(30)
                e.setFont(QFont("Consolas", 13))
                e.setStyleSheet(
                    f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                    f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
                )
                e.setText(display)
                ff_layout.addWidget(e)
                mg.addWidget(ff, row, col)
                mg.setColumnStretch(col, 1)
                self._fields[f"mb.{bi}.{field}"] = e

            self._editor_layout.addWidget(mf)

        # Special
        self._add_section(self.t("section_special_props"))
        sf = QFrame()
        sf.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        sf_inner = QWidget(sf)
        sf_inner.setStyleSheet("background: transparent;")
        sg = QGridLayout(sf_inner)
        sg.setContentsMargins(12, 12, 12, 12)
        sg.setHorizontalSpacing(16)
        sg.setVerticalSpacing(8)

        sf_main = QVBoxLayout(sf)
        sf_main.setContentsMargins(0, 0, 0, 0)
        sf_main.addWidget(sf_inner)

        sp_row0_fields = [
            ("dlc_code",    self.t("field_dlc_code"),    char['dlc_code']),
            ("icon_code",   self.t("field_icon_code"),   char['icon_code']),
            ("corpse_parts", self.t("field_corpse_parts"), char['corpse_parts']),
        ]
        for ci, (key, label, val) in enumerate(sp_row0_fields):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(0, 0, 0, 0)
            f_layout.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            f_layout.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            f_layout.addWidget(e)
            sg.addWidget(f, 0, ci)
            sg.setColumnStretch(ci, 1)
            self._fields[key] = e

        sp_row1_fields = [
            ("style",           self.t("field_style"),           char['style']),
            ("roster_position", self.t("field_roster_position"), char['roster_position']),
        ]
        for ci, (key, label, val) in enumerate(sp_row1_fields):
            f = QWidget()
            f.setStyleSheet("background: transparent;")
            f_layout = QVBoxLayout(f)
            f_layout.setContentsMargins(0, 0, 0, 0)
            f_layout.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_sec']};")
            f_layout.addWidget(lbl)
            e = QLineEdit()
            e.setFixedHeight(30)
            e.setFont(QFont("Consolas", 13))
            e.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            e.setText(str(val))
            f_layout.addWidget(e)
            sg.addWidget(f, 1, ci)
            sg.setColumnStretch(ci, 1)
            self._fields[key] = e

        self._editor_layout.addWidget(sf)

        # Bottom padding
        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    # Add / Duplicate / Delete

    def _make_default_char(self, chunk_offset):
        return {
            'chunk_offset': chunk_offset,
            'char_id': 'new_chr',
            'name': self.t("default_char_name"),
            'param_id': 0,
            'variants': ['new_chr'] + [''] * 18,
            'collision_threshold': 0,
            'camera_height': 0,
            'collision_size': 0,
            'bones': [
                {'label': f"Bone {i+1}", 'name': '', 'size_1': 0, 'size_2': 0}
                for i in range(4)
            ],
            'hp': 1000,
            'gha_damage': 200,
            'max_gauge': 100,
            'guard_gauge': 100,
            'guard_break_recovery': 60,
            'dmg_scaling_1': 1.0,
            'dmg_scaling_2': 1.0,
            'dmg_scaling_3': 1.0,
            'unk_floats': [0.0] * 7,
            'movement_blocks': [
                {
                    'label': label,
                    'fwd_walk': 0, 'bwd_walk': 0,
                    'fwd_run': 0, 'bwd_run': 0,
                    'gravity_strength': 0.0, 'jump_upward_vel': 0.0,
                    'jump_forward_vel': 0.0, 'dash_jump_height': 0.0,
                    'dash_jump_dist': 0.0,
                }
                for label in (ui_text("ui_char_stats_stand_on"), ui_text("ui_char_stats_stand_off"), ui_text("ui_char_stats_alternate"))
            ],
            'dlc_code': 0,
            'icon_code': 0,
            'corpse_parts': '',
            'style': 0,
            'roster_position': 0,
        }

    def _append_chunk(self, source_char=None):
        """Append a new chunk to the binary data. Returns the new chunk_offset."""
        if source_char:
            co = source_char['chunk_offset']
            raw_header = bytes(self._xfbin_data[co - 12:co])
            raw_chunk = bytes(self._xfbin_data[co:co + CHUNK_SIZE])
        else:
            raw_header = struct.pack(ui_text("ui_char_stats_i"), CHUNK_SIZE) + b'\x00' * 8
            raw_chunk = b'\x00' * CHUNK_SIZE

        # Align to 4 bytes
        while len(self._xfbin_data) % 4:
            self._xfbin_data.append(0)

        new_offset = len(self._xfbin_data) + 12
        self._xfbin_data.extend(raw_header)
        self._xfbin_data.extend(raw_chunk)
        return new_offset

    def _add_new_char(self):
        if not self._xfbin_data:
            return
        self._apply_fields()
        new_offset = self._append_chunk()
        char = self._make_default_char(new_offset)
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)

    def _duplicate_char(self):
        if not self._xfbin_data or not self._current_char:
            return
        self._apply_fields()
        src = self._current_char
        new_offset = self._append_chunk(source_char=src)
        char = copy.deepcopy(src)
        char['chunk_offset'] = new_offset
        char['name'] = src['name'] + self.t("msg_copy_suffix")
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)

    def _delete_char(self):
        if not self._xfbin_data or not self._current_char:
            return
        if len(self._characters) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("msg_cannot_delete_last_char"))
            return
        name = self._current_char['name']
        result = QMessageBox.question(self, self.t("dlg_title_confirm_delete"),
                                      self.t("msg_confirm_delete_item", name=name))
        if result != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        self._characters.remove(self._current_char)
        self._current_char = None
        self._populate_list()

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)
