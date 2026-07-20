import os
import copy
import json
import struct
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_accent_sep, ss_input, ss_file_label,
    ss_scrollarea, ss_scrollarea_transparent, ss_editor_card, ss_field_label,
    ss_main_label, ss_dim_label, ss_section_label, ss_panel_title,
    ss_transparent, make_empty_state,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from core.editor_diff import ChangeItem
from core.editor_host import confirm_editor_change_summary, notify_editor_file_loaded
from core.undo_redo import EditorHistory
from core.skeleton import SkeletonListRow, SkeletonBar
from parsers.xfbin_parser import parse_xfbin, save_xfbin, CHUNK_SIZE
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


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
        self._field_edit_order = []
        self._char_buttons = []
        self._filepath = None
        self._saved_characters = []
        self._dirty = False
        self._history = EditorHistory()
        self._restoring_history = False

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
        open_btn.clicked.connect(lambda _checked=False: self._load_file())
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
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        root_layout.addWidget(top)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
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
        self._char_scroll.setStyleSheet(ss_scrollarea_transparent())
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
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)

        self._show_placeholder()

        main_layout.addWidget(self._editor_scroll, 1)

        root_layout.addWidget(main, 1)

    # Helpers

    def _clear_char_list(self):
        _clear_layout(self._char_list_layout)
        self._char_list_layout.addStretch()

    def _clear_editor(self):
        _clear_layout(self._editor_layout)

    def _show_placeholder(self):
        self._clear_editor()
        card = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=self.t("placeholder_char_stats"),
            icon_name="fa6s.chart-simple",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    @staticmethod
    def _labels_path(xfbin_path):
        return os.path.splitext(xfbin_path)[0] + '.labels.json'

    # File I/O

    def _load_file(self, path=None):
        if path is not None and not isinstance(path, (str, os.PathLike)):
            path = None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, self.t("file_open_char_stats"), game_files_dialog_dir(target_patterns="duelPlayerParam.xfbin"),
                "XFBIN files (*.xfbin);;All files (*.*)")
            if not path:
                return

        create_backup_on_open(path, tool_id=getattr(self, "_tool_id", None))
        set_file_label_empty(self._file_label, self.t("loading"))
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
        self._field_edit_order = []

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
        self._show_placeholder()
        self._filepath = None
        self._saved_characters = []
        self._dirty = False
        self._history.clear()
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"),
                             self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, xfbin_data, characters):
        self._xfbin_data = xfbin_data
        self._characters = characters
        self._filepath = path
        self._saved_characters = copy.deepcopy(characters)
        self._dirty = False
        self._history.clear()
        set_file_label(self._file_label, path)
        notify_editor_file_loaded(self, path)

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    def _save_file(self):
        if not self._xfbin_data:
            return
        self._apply_fields()
        if not self._filepath:
            return
        if not confirm_editor_change_summary(self):
            return
        try:
            path = self._filepath
            save_xfbin(path, self._xfbin_data, self._characters)
            labels = {char['char_id']: char['name'] for char in self._characters}
            with open(self._labels_path(path), 'w', encoding='utf-8') as f:
                json.dump(labels, f, ensure_ascii=False, indent=2)
            self._saved_characters = copy.deepcopy(self._characters)
            self._dirty = False
            set_file_label(self._file_label, path)
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
        keys = list(self._field_edit_order)
        keys.extend(key for key in self._fields if key not in self._field_edit_order)
        for key in keys:
            entry = self._fields.get(key)
            if entry is None:
                continue
            state_before = self.get_undo_state()
            char_before = copy.deepcopy(char)
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
            if (
                char != char_before
                and not self._restoring_history
                and state_before is not None
            ):
                self._history.push(state_before)
        self._field_edit_order = []
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

    def _make_editor_card(self, margins=(16, 14, 16, 14), spacing=10):
        card = QFrame()
        card.setObjectName("EditorCard")
        card.setStyleSheet(ss_editor_card())
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(inner)
        return card, layout

    def _add_card_title(self, layout, title, icon_name=None):
        row = QWidget()
        row.setStyleSheet(ss_transparent())
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        if icon_name:
            icon = QLabel()
            icon.setFixedSize(18, 18)
            icon.setStyleSheet(ss_transparent())
            icon.setPixmap(qta.icon(icon_name, color=P["accent"]).pixmap(18, 18))
            row_layout.addWidget(icon)

        lbl = QLabel(title.upper())
        lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_panel_title())
        row_layout.addWidget(lbl)
        row_layout.addStretch()
        layout.addWidget(row)

    def _make_editor_field(self, label, value, field_key, *, value_font=None, height=30):
        frame = QWidget()
        frame.setStyleSheet(ss_transparent())
        field_layout = QVBoxLayout(frame)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        field_layout.addWidget(lbl)

        entry = QLineEdit()
        entry.setFixedHeight(height)
        entry.setFont(value_font or QFont("Consolas", 13))
        entry.setStyleSheet(ss_input())
        entry.setText(str(value))
        field_layout.addWidget(entry)
        self._fields[field_key] = entry
        return frame, entry

    def _build_editor(self, char):
        self._clear_editor()
        self._fields = {}
        self._field_edit_order = []
        self._editor_layout.setContentsMargins(10, 8, 10, 0)
        self._editor_layout.setSpacing(12)

        overview_lbl = QLabel("OVERVIEW")
        overview_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        overview_lbl.setStyleSheet(ss_section_label())
        self._editor_layout.addWidget(overview_lbl)

        overview_grid = QGridLayout()
        overview_grid.setContentsMargins(0, 0, 0, 0)
        overview_grid.setHorizontalSpacing(12)
        overview_grid.setVerticalSpacing(0)
        overview_font = QFont("Consolas", 16)
        name_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
        for col, (key, label, value, font) in enumerate([
            ("_display_name", self.t("label_display_name_cosmetic"), char['name'], name_font),
            ("char_id", self.t("label_char_id_saved"), char['char_id'], overview_font),
            ("param_id", self.t("label_param_id"), char['param_id'], overview_font),
        ]):
            card, card_layout = self._make_editor_card(margins=(16, 14, 16, 14), spacing=6)
            field, _ = self._make_editor_field(label, value, key, value_font=font, height=38)
            card_layout.addWidget(field)
            overview_grid.addWidget(card, 0, col)
            overview_grid.setColumnStretch(col, 1)
        self._editor_layout.addLayout(overview_grid)

        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(12)
        cards_grid.setVerticalSpacing(12)

        stats_frame, stats_layout = self._make_editor_card()
        self._add_card_title(stats_layout, self.t("section_combat_stats"), "fa6s.khanda")
        stats_grid = QGridLayout()
        stats_grid.setContentsMargins(0, 4, 0, 0)
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(10)
        for i, (key, label, val, span) in enumerate([
            ("hp", self.t("field_hp"), char['hp'], 1),
            ("gha_damage", self.t("field_gha_damage"), char['gha_damage'], 1),
            ("max_gauge", self.t("field_max_gauge"), char['max_gauge'], 1),
            ("guard_gauge", self.t("field_guard_gauge"), char['guard_gauge'], 1),
            ("guard_break_recovery", self.t("field_guard_break_recovery"), char['guard_break_recovery'], 2),
        ]):
            row, col = divmod(i, 2)
            field, _ = self._make_editor_field(label, val, key)
            stats_grid.addWidget(field, row, col, 1, span)
            stats_grid.setColumnStretch(col, 1)
        stats_layout.addLayout(stats_grid)
        cards_grid.addWidget(stats_frame, 0, 0)

        elem_frame, elem_layout = self._make_editor_card()
        self._add_card_title(elem_layout, self.t("section_elemental_modifiers"), "fa6s.fire")
        for key, label, val in [
            ("dmg_scaling_1", self.t("field_dmg_scale_1"), f"{char['dmg_scaling_1']:.2f}"),
            ("dmg_scaling_2", self.t("field_dmg_scale_2"), f"{char['dmg_scaling_2']:.2f}"),
            ("dmg_scaling_3", self.t("field_dmg_scale_3"), f"{char['dmg_scaling_3']:.2f}"),
        ]:
            field, _ = self._make_editor_field(label, val, key)
            elem_layout.addWidget(field)
        cards_grid.addWidget(elem_frame, 0, 1)

        col_frame, col_layout = self._make_editor_card()
        self._add_card_title(col_layout, self.t("section_collision"), "fa6s.shield-halved")
        for key, label, val in [
            ("collision_threshold", self.t("field_collision_threshold"), char['collision_threshold']),
            ("camera_height", self.t("field_camera_height"), char['camera_height']),
            ("collision_size", self.t("field_collision_size"), char['collision_size']),
        ]:
            field, _ = self._make_editor_field(label, val, key)
            col_layout.addWidget(field)
        cards_grid.addWidget(col_frame, 0, 2)

        uf_frame, uf_layout = self._make_editor_card()
        self._add_card_title(uf_layout, self.t("section_unk_floats"), "fa6s.circle-question")
        uf_grid = QGridLayout()
        uf_grid.setContentsMargins(0, 4, 0, 0)
        uf_grid.setHorizontalSpacing(16)
        uf_grid.setVerticalSpacing(10)
        for i, val in enumerate(char['unk_floats']):
            row, col = divmod(i, 4)
            field, _ = self._make_editor_field(
                self.t("field_unk_float_n", n=i + 1),
                ui_text("ui_char_stats_value", p0=val),
                f"uf.{i}",
            )
            uf_grid.addWidget(field, row, col)
            uf_grid.setColumnStretch(col, 1)
        uf_layout.addLayout(uf_grid)
        cards_grid.addWidget(uf_frame, 1, 0)

        bones_frame, bones_layout = self._make_editor_card()
        self._add_card_title(bones_layout, self.t("section_hitbox_bones"), "fa6s.crosshairs")
        bones_grid = QGridLayout()
        bones_grid.setContentsMargins(0, 4, 0, 0)
        bones_grid.setHorizontalSpacing(12)
        bones_grid.setVerticalSpacing(8)
        for col, hdr_text in enumerate([self.t("bone_col_bone"), self.t("bone_col_name")]):
            lbl = QLabel(hdr_text)
            lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            lbl.setStyleSheet(ss_dim_label())
            bones_grid.addWidget(lbl, 0, col)
        bones_grid.setColumnStretch(0, 0)
        bones_grid.setColumnStretch(1, 1)

        for bi, bone in enumerate(char['bones']):
            lbl = QLabel(bone['label'])
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(ss_main_label())
            bones_grid.addWidget(lbl, bi + 1, 0)
            entry = QLineEdit()
            entry.setFixedHeight(28)
            entry.setFont(QFont("Consolas", 12))
            entry.setStyleSheet(ss_input())
            entry.setText(str(bone['name']))
            bones_grid.addWidget(entry, bi + 1, 1)
            self._fields[f"bone.{bi}.name"] = entry
        bones_layout.addLayout(bones_grid)
        cards_grid.addWidget(bones_frame, 1, 1, 1, 2)

        for col in range(3):
            cards_grid.setColumnStretch(col, 1)
        self._editor_layout.addLayout(cards_grid)

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
        movement_grid = QGridLayout()
        movement_grid.setContentsMargins(0, 0, 0, 0)
        movement_grid.setHorizontalSpacing(12)
        movement_grid.setVerticalSpacing(12)
        for bi, block in enumerate(char['movement_blocks']):
            mf, mf_layout = self._make_editor_card()
            self._add_card_title(
                mf_layout,
                self.t("section_movement_label", label=block['label']),
                "fa6s.person-running",
            )
            mg = QGridLayout()
            mg.setContentsMargins(0, 4, 0, 0)
            mg.setHorizontalSpacing(16)
            mg.setVerticalSpacing(10)

            fields_list = ['fwd_walk', 'bwd_walk', 'fwd_run', 'bwd_run', 'gravity_strength',
                           'jump_upward_vel', 'jump_forward_vel', 'dash_jump_height', 'dash_jump_dist']
            for fi, field in enumerate(fields_list):
                row, col = divmod(fi, 3)
                val = block[field]
                display = f"{val:.2f}" if isinstance(val, float) else str(val)
                ff, _ = self._make_editor_field(
                    block_labels[field],
                    display,
                    f"mb.{bi}.{field}",
                )
                mg.addWidget(ff, row, col)
                mg.setColumnStretch(col, 1)

            mf_layout.addLayout(mg)
            movement_grid.addWidget(mf, 0, bi)
            movement_grid.setColumnStretch(bi, 1)

        self._editor_layout.addLayout(movement_grid)

        # Special
        sf, sf_layout = self._make_editor_card()
        self._add_card_title(sf_layout, self.t("section_special_props"), "fa6s.sliders")
        sg = QGridLayout()
        sg.setContentsMargins(0, 4, 0, 0)
        sg.setHorizontalSpacing(16)
        sg.setVerticalSpacing(10)

        sp_row0_fields = [
            ("dlc_code",    self.t("field_dlc_code"),    char['dlc_code']),
            ("icon_code",   self.t("field_icon_code"),   char['icon_code']),
            ("corpse_parts", self.t("field_corpse_parts"), char['corpse_parts']),
        ]
        for ci, (key, label, val) in enumerate(sp_row0_fields):
            f, _ = self._make_editor_field(label, val, key)
            sg.addWidget(f, 0, ci)
            sg.setColumnStretch(ci, 1)

        sp_row1_fields = [
            ("style",           self.t("field_style"),           char['style']),
            ("roster_position", self.t("field_roster_position"), char['roster_position']),
        ]
        for ci, (key, label, val) in enumerate(sp_row1_fields):
            f, _ = self._make_editor_field(label, val, key)
            sg.addWidget(f, 1, ci)
            sg.setColumnStretch(ci, 1)

        sf_layout.addLayout(sg)
        self._editor_layout.addWidget(sf)

        # Bottom padding
        for key, field in self._fields.items():
            field.textEdited.connect(lambda _text, k=key: self._on_field_text_edited(k))

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    def _mark_dirty(self, *_):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)

    def _on_field_text_edited(self, key):
        if key in self._field_edit_order:
            self._field_edit_order.remove(key)
        self._field_edit_order.append(key)
        self._mark_dirty()

    def _push_undo_state(self):
        if self._restoring_history:
            return
        state = self.get_undo_state()
        if state is not None:
            self._history.push(state)

    def get_undo_state(self):
        if self._xfbin_data is None:
            return None
        current_index = -1
        if self._current_char in self._characters:
            current_index = self._characters.index(self._current_char)
        return {
            "xfbin_data": bytearray(self._xfbin_data),
            "characters": copy.deepcopy(self._characters),
            "current_index": current_index,
        }

    def restore_undo_state(self, state):
        if not state:
            return False
        self._restoring_history = True
        try:
            self._xfbin_data = bytearray(state["xfbin_data"])
            self._characters = copy.deepcopy(state["characters"])
            self._fields = {}
            self._field_edit_order = []
            self._current_char = None
            self._populate_list()
            index = int(state.get("current_index", -1))
            if 0 <= index < len(self._characters):
                self._select_char(self._characters[index])
            self._mark_dirty()
        finally:
            self._restoring_history = False
        return True

    def apply_pending_edits(self):
        self._apply_fields()

    def get_saved_state(self):
        return copy.deepcopy(self._saved_characters)

    def get_current_state(self):
        self.apply_pending_edits()
        return copy.deepcopy(self._characters)

    def get_change_summary(self):
        return self.describe_state_diff(self.get_saved_state(), self.get_current_state())

    def load_comparison_state(self, path):
        _data, characters = parse_xfbin(path)
        return copy.deepcopy(characters)

    def describe_state_diff(self, before, after):
        before_map = {char.get("char_id", f"#{idx}"): char for idx, char in enumerate(before or [])}
        after_map = {char.get("char_id", f"#{idx}"): char for idx, char in enumerate(after or [])}
        changes = []
        for char_id, after_char in after_map.items():
            label = self._diff_char_label(after_char)
            before_char = before_map.get(char_id)
            if before_char is None:
                changes.append(ChangeItem(f"char:{char_id}", "added", self.t("qol_diff_added", item=label), "", "", True))
                continue
            before_flat = self._flatten_char(before_char)
            after_flat = self._flatten_char(after_char)
            for key in sorted(after_flat):
                if key == "chunk_offset":
                    continue
                if before_flat.get(key) != after_flat.get(key):
                    changes.append(ChangeItem(
                        f"field:{char_id}:{key}",
                        "changed",
                        f"{label} / {self._diff_field_label(key)}",
                        str(before_flat.get(key, "")),
                        str(after_flat.get(key, "")),
                        True,
                    ))
        for char_id, before_char in before_map.items():
            if char_id not in after_map:
                changes.append(ChangeItem(
                    f"char:{char_id}",
                    "removed",
                    self.t("qol_diff_removed", item=self._diff_char_label(before_char)),
                    "",
                    "",
                    False,
                ))
        return changes

    def copy_from_state(self, external_state, item_ids):
        if not item_ids:
            return
        self.apply_pending_edits()
        self._push_undo_state()
        external_map = {char.get("char_id", f"#{idx}"): char for idx, char in enumerate(external_state or [])}
        current_map = {char.get("char_id", f"#{idx}"): char for idx, char in enumerate(self._characters)}
        selected = None
        for item_id in item_ids:
            parts = item_id.split(":", 2)
            if len(parts) < 2:
                continue
            kind, char_id = parts[0], parts[1]
            source = external_map.get(char_id)
            if source is None:
                continue
            if kind == "char" and char_id not in current_map:
                new_char = copy.deepcopy(source)
                new_char["chunk_offset"] = self._append_chunk(source_char=self._characters[0] if self._characters else None)
                self._characters.append(new_char)
                current_map[char_id] = new_char
                selected = new_char
            elif kind == "field" and len(parts) == 3:
                target = current_map.get(char_id)
                if target is None:
                    continue
                value = self._get_path_value(source, parts[2])
                self._set_path_value(target, parts[2], copy.deepcopy(value))
                selected = target
        self._populate_list()
        if selected in self._characters:
            self._select_char(selected)
        self._mark_dirty()

    def _diff_char_label(self, char):
        name = char.get("name") or char.get("char_id") or "?"
        char_id = char.get("char_id") or "?"
        return f"{name} ({char_id})"

    def _diff_field_label(self, key):
        return key.replace(".", " / ").replace("_", " ")

    def _flatten_char(self, value, prefix=""):
        result = {}
        if isinstance(value, dict):
            for key, child in value.items():
                child_key = f"{prefix}.{key}" if prefix else str(key)
                result.update(self._flatten_char(child, child_key))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                child_key = f"{prefix}.{idx}" if prefix else str(idx)
                result.update(self._flatten_char(child, child_key))
        else:
            result[prefix] = value
        return result

    def _get_path_value(self, root, path):
        current = root
        for part in path.split("."):
            current = current[int(part)] if isinstance(current, list) else current[part]
        return current

    def _set_path_value(self, root, path, value):
        parts = path.split(".")
        current = root
        for part in parts[:-1]:
            current = current[int(part)] if isinstance(current, list) else current[part]
        last = parts[-1]
        if isinstance(current, list):
            current[int(last)] = value
        else:
            current[last] = value

    def shortcut_action(self, action_id: str) -> bool:
        if action_id == "editor.undo":
            self.apply_pending_edits()
            state = self._history.undo(self.get_undo_state())
            return self.restore_undo_state(state)
        if action_id == "editor.redo":
            state = self._history.redo(self.get_undo_state())
            return self.restore_undo_state(state)
        if action_id == "editor.new":
            self._add_new_char()
            return True
        if action_id == "editor.duplicate":
            self._duplicate_char()
            return True
        if action_id == "editor.delete":
            self._delete_char()
            return True
        return False

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
        self._push_undo_state()
        new_offset = self._append_chunk()
        char = self._make_default_char(new_offset)
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)
        self._mark_dirty()

    def _duplicate_char(self):
        if not self._xfbin_data or not self._current_char:
            return
        self._apply_fields()
        self._push_undo_state()
        src = self._current_char
        new_offset = self._append_chunk(source_char=src)
        char = copy.deepcopy(src)
        char['chunk_offset'] = new_offset
        char['name'] = src['name'] + self.t("msg_copy_suffix")
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)
        self._mark_dirty()

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
        self._push_undo_state()
        self._fields = {}
        self._field_edit_order = []
        self._characters.remove(self._current_char)
        self._current_char = None
        self._populate_list()
        self._mark_dirty()

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)
