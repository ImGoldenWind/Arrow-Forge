import os
import copy
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QColorDialog, QSizePolicy, QSpacerItem,
)
from PyQt6.QtGui import QFont, QColor, QCursor
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_toolbar, ss_accent_sep, ss_sep, ss_input,
    ss_scrollarea, ss_scrollarea_transparent,
)
from core.skeleton import SkeletonListRow, SkeletonBar
from parsers.costume_parser import parse_costume_xfbin, save_costume_xfbin
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


class CostumeEditor(QWidget):
    # Signals for thread-safe GUI updates
    _sig_load_done = pyqtSignal(str, bytearray, list, int, object)
    _sig_load_error = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t = lang_func

        self._raw_data = None
        self._characters = []
        self._binary_offset = 0
        self._current_char = None
        self._color_widgets = []  # list of (costume_idx, color_idx, frame, r_entry, g_entry, b_entry)
        self._filepath = None
        self._char_buttons = []
        self._notes = b''
        self._costume_frames = []  # list of QFrame, one per costume section

        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_error.connect(self._on_load_error)

        self._build_ui()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

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

        self._file_label = QLabel(self.t("no_file_loaded"), top)
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        outer_layout.addWidget(top)

        # Separator
        sep = QFrame(self)
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {P['accent_dim']};")
        outer_layout.addWidget(sep)

        # Main area
        main = QWidget(self)
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Character list sidebar
        list_frame = QFrame(main)
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        # Search
        search_frame = QWidget(list_frame)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(8, 8, 8, 4)
        self._search_entry = QLineEdit(search_frame)
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search_entry.textChanged.connect(self._filter_list)
        search_layout.addWidget(self._search_entry)
        list_layout.addWidget(search_frame)

        # Actions
        actions_frame = QWidget(list_frame)
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(8, 2, 8, 4)
        actions_layout.setSpacing(4)
        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self.t("btn_new"), actions_frame)
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_new_char)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"), actions_frame)
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_char)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"), actions_frame)
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_char)
        actions_layout.addWidget(self._del_btn, 1)

        list_layout.addWidget(actions_frame)

        # Scrollable character list
        self._char_scroll = QScrollArea(list_frame)
        self._char_scroll.setWidgetResizable(True)
        self._char_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._char_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._char_list_widget = QWidget()
        self._char_list_widget.setStyleSheet("background: transparent;")
        self._char_list_layout = QVBoxLayout(self._char_list_widget)
        self._char_list_layout.setContentsMargins(0, 0, 0, 0)
        self._char_list_layout.setSpacing(1)
        self._char_list_layout.addStretch()
        self._char_scroll.setWidget(self._char_list_widget)
        list_layout.addWidget(self._char_scroll)

        main_layout.addWidget(list_frame)

        # Divider line
        divider = QFrame(main)
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Editor panel (scrollable)
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

        self._placeholder = QLabel(self.t("placeholder_costume"), self._editor_widget)
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addSpacing(60)
        self._editor_layout.addWidget(self._placeholder, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)

        outer_layout.addWidget(main, 1)

    # File loading

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_costume"), "",
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        self._file_label.setText(self.t("loading"))
        self._show_list_skeleton()
        self._show_editor_skeleton()

        def worker():
            try:
                raw, characters, binary_offset, notes = parse_costume_xfbin(path)
            except Exception as e:
                self._sig_load_error.emit(str(e))
                return
            self._sig_load_done.emit(path, raw, characters, binary_offset, notes)

        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        _clear_layout(self._char_list_layout)
        self._char_buttons = []
        for _ in range(10):
            self._char_list_layout.addWidget(SkeletonListRow(self._char_list_widget))
        self._char_list_layout.addStretch()

    def _show_editor_skeleton(self):
        _clear_layout(self._editor_layout)
        self._color_widgets = []

        hdr = QFrame(self._editor_widget)
        hdr.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 14, 16, 14)
        hdr_layout.addWidget(SkeletonBar(hdr, height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)

        for _ in range(3):
            sec = QFrame(self._editor_widget)
            sec.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
            sec_layout = QVBoxLayout(sec)
            sec_layout.setContentsMargins(12, 12, 12, 12)

            g = QWidget(sec)
            g_layout = QGridLayout(g)
            g_layout.setContentsMargins(0, 0, 0, 0)
            g_layout.setSpacing(8)
            for col in range(4):
                f = QWidget(g)
                f_layout = QVBoxLayout(f)
                f_layout.setContentsMargins(0, 0, 0, 0)
                f_layout.setSpacing(4)
                f_layout.addWidget(SkeletonBar(f, height=11, corner_radius=3))
                f_layout.addWidget(SkeletonBar(f, height=30, corner_radius=4))
                g_layout.addWidget(f, 0, col)
            sec_layout.addWidget(g)
            self._editor_layout.addWidget(sec)
        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        _clear_layout(self._char_list_layout)
        self._char_list_layout.addStretch()
        _clear_layout(self._editor_layout)
        self._placeholder = QLabel(self.t("placeholder_costume"), self._editor_widget)
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addSpacing(60)
        self._editor_layout.addWidget(self._placeholder, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._file_label.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, raw, characters, binary_offset, notes):
        self._raw_data = raw
        self._characters = characters
        self._binary_offset = binary_offset
        self._notes = notes
        self._filepath = path
        for char in self._characters:
            key = f"char_{char['char_id']}"
            translated = self.t(key)
            if translated != key:
                char['name'] = translated
        self._file_label.setText(os.path.basename(path))
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    # Save

    def _save_file(self):
        if not self._raw_data:
            return
        self._apply_colors()
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file_save_costume"), "",
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return
        try:
            save_costume_xfbin(path, self._raw_data, self._characters, self._binary_offset, self._notes)
            QMessageBox.information(self, self.t("dlg_title_success"),
                                    self.t("msg_save_success", path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                 self.t("msg_save_error", error=e))

    # Character list

    def _populate_list(self):
        _clear_layout(self._char_list_layout)
        self._char_buttons = []
        for char in self._characters:
            btn = QPushButton(self._char_list_widget)
            btn.setFixedHeight(44)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                f"border: none; text-align: left; padding: 0; }} "
                f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
            )
            btn.clicked.connect(lambda checked, c=char: self._select_char(c))

            # Internal layout for the button content
            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(10, 3, 10, 3)
            btn_layout.setSpacing(4)

            # Text section
            text_widget = QWidget(btn)
            text_widget.setStyleSheet("background: transparent;")
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(0)

            name_lbl = QLabel(char['name'], text_widget)
            name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
            name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout.addWidget(name_lbl)

            slots_count = len(char['costumes'])
            sub_key = "char_costumes_sub" if slots_count == 1 else "char_costumes_sub_plural"
            sub_text = self.t(sub_key, char_id=char['char_id'], n=slots_count)
            id_lbl = QLabel(sub_text, text_widget)
            id_lbl.setFont(QFont("Consolas", 11))
            id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout.addWidget(id_lbl)

            btn_layout.addWidget(text_widget, 1)

            self._char_list_layout.addWidget(btn)
            self._char_buttons.append((btn, char))

        self._char_list_layout.addStretch()

        if self._characters:
            self._select_char(self._characters[0])

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, char in self._char_buttons:
            match = query in char['name'].lower() or query in char['char_id'].lower()
            btn.setVisible(match)

    def _select_char(self, char):
        self._apply_colors()
        self._current_char = char
        for btn, c in self._char_buttons:
            if c is char:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {P['bg_card']}; border-radius: 6px; "
                    f"border: none; text-align: left; padding: 0; }} "
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                    f"border: none; text-align: left; padding: 0; }} "
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
        self._build_editor(char)

    # Apply edits back to data

    def _apply_colors(self):
        if not self._current_char or not self._color_widgets:
            return
        char = self._current_char
        for ci, coli, _, r_entry, g_entry, b_entry in self._color_widgets:
            try:
                r = max(0, min(255, int(r_entry.text())))
                g = max(0, min(255, int(g_entry.text())))
                b = max(0, min(255, int(b_entry.text())))
                char['costumes'][ci]['colors'][coli]['r'] = r
                char['costumes'][ci]['colors'][coli]['g'] = g
                char['costumes'][ci]['colors'][coli]['b'] = b
            except (ValueError, IndexError):
                pass
        # Apply char_id if changed
        if hasattr(self, '_char_id_entry') and self._char_id_entry:
            try:
                new_id = self._char_id_entry.text().strip()[:7]
                if new_id:
                    char['char_id'] = new_id
            except Exception:
                pass
        if hasattr(self, '_name_entry') and self._name_entry:
            try:
                char['name'] = self._name_entry.text()
            except Exception:
                pass

    # Editor panel

    def _build_editor(self, char):
        _clear_layout(self._editor_layout)
        self._color_widgets = []
        self._char_id_entry = None
        self._name_entry = None
        self._costume_frames = []
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)

        # Character header
        hdr = QFrame(self._editor_widget)
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_outer = QVBoxLayout(hdr)
        hdr_outer.setContentsMargins(16, 12, 16, 12)

        hdr_grid = QWidget(hdr)
        hdr_grid.setStyleSheet("background: transparent;")
        hdr_grid_layout = QGridLayout(hdr_grid)
        hdr_grid_layout.setContentsMargins(0, 0, 0, 0)
        hdr_grid_layout.setSpacing(16)

        # Display Name
        name_frame = QWidget(hdr_grid)
        name_frame.setStyleSheet("background: transparent;")
        name_layout = QVBoxLayout(name_frame)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(2)
        name_label = QLabel(self.t("label_display_name"), name_frame)
        name_label.setFont(QFont("Segoe UI", 12))
        name_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        name_layout.addWidget(name_label)
        e_name = QLineEdit(name_frame)
        e_name.setFixedHeight(36)
        e_name.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        e_name.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['accent']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_name.setText(char['name'])
        name_layout.addWidget(e_name)
        self._name_entry = e_name
        hdr_grid_layout.addWidget(name_frame, 0, 0)
        hdr_grid_layout.setColumnStretch(0, 1)

        # Char ID
        id_frame = QWidget(hdr_grid)
        id_frame.setStyleSheet("background: transparent;")
        id_layout = QVBoxLayout(id_frame)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(2)
        id_label = QLabel(self.t("label_char_id_short"), id_frame)
        id_label.setFont(QFont("Segoe UI", 12))
        id_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_layout.addWidget(id_label)
        e_id = QLineEdit(id_frame)
        e_id.setFixedHeight(36)
        e_id.setFont(QFont("Consolas", 16))
        e_id.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        e_id.setText(char['char_id'])
        id_layout.addWidget(e_id)
        self._char_id_entry = e_id
        hdr_grid_layout.addWidget(id_frame, 0, 1)
        hdr_grid_layout.setColumnStretch(1, 1)

        # Costume count info
        info_frame = QWidget(hdr_grid)
        info_frame.setStyleSheet("background: transparent;")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        info_label = QLabel(self.t("label_costumes"), info_frame)
        info_label.setFont(QFont("Segoe UI", 12))
        info_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        info_layout.addWidget(info_label)
        count_label = QLabel(str(len(char['costumes'])), info_frame)
        count_label.setFont(QFont("Consolas", 24, QFont.Weight.Bold))
        count_label.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        info_layout.addWidget(count_label)
        hdr_grid_layout.addWidget(info_frame, 0, 2)

        hdr_outer.addWidget(hdr_grid)
        self._editor_layout.addWidget(hdr)

        # Costume slots
        for ci, costume in enumerate(char['costumes']):
            self._build_costume_section(char, ci, costume)

        # Add Costume Slot button at the very bottom
        add_costume_frame = QWidget(self._editor_widget)
        add_costume_frame.setStyleSheet("background: transparent;")
        add_costume_layout = QHBoxLayout(add_costume_frame)
        add_costume_layout.setContentsMargins(0, 4, 0, 0)
        add_costume_layout.setSpacing(4)

        add_costume_btn = QPushButton(self.t("btn_add_costume_slot"), add_costume_frame)
        add_costume_btn.setFixedHeight(30)
        add_costume_btn.setFont(QFont("Segoe UI", 10))
        add_costume_btn.setIcon(qta.icon("fa6s.plus", color=P["text_main"]))
        add_costume_btn.setStyleSheet(ss_btn())
        add_costume_btn.clicked.connect(lambda: self._add_costume_slot(char))
        add_costume_layout.addWidget(add_costume_btn)
        add_costume_layout.addStretch()

        self._editor_layout.addWidget(add_costume_frame)

        # Bottom padding
        self._editor_layout.addSpacing(20)
        self._editor_layout.addStretch()

    def _build_costume_section(self, char, ci, costume):
        slot = costume['slot']
        slot_label = self.t("costume_default") if slot == 0 else self.t("costume_slot_n", n=slot)

        # Section header — no click-to-select
        sec_header = QWidget(self._editor_widget)
        sec_header.setStyleSheet("background: transparent;")
        sec_header_layout = QHBoxLayout(sec_header)
        sec_header_layout.setContentsMargins(20, 10, 20, 2)

        slot_lbl = QLabel(self.t("costume_slot_header", slot=slot, label=slot_label), sec_header)
        slot_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        slot_lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        sec_header_layout.addWidget(slot_lbl)
        sec_header_layout.addStretch()

        remove_btn = QPushButton(self.t("btn_remove"), sec_header)
        remove_btn.setFixedHeight(26)
        remove_btn.setFont(QFont("Segoe UI", 10))
        remove_btn.setIcon(qta.icon("fa6s.trash", color=ui_text("ui_costume_ffffff")))
        remove_btn.setIconSize(QSize(14, 14))
        remove_btn.setStyleSheet(ss_btn(danger=True))
        remove_btn.clicked.connect(lambda checked, c=ci: self._remove_costume(c))
        sec_header_layout.addWidget(remove_btn)

        self._editor_layout.addWidget(sec_header)

        sec = QFrame(self._editor_widget)
        sec.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}"
        )
        self._costume_frames.append(sec)
        sec_layout = QVBoxLayout(sec)
        sec_layout.setContentsMargins(12, 12, 12, 12)
        sec_layout.setSpacing(8)

        grid = QWidget(sec)
        grid.setStyleSheet("background: transparent;")
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(16)
        grid_layout.setVerticalSpacing(12)

        color_names = self._get_color_names(len(costume['colors']))

        for coli, color in enumerate(costume['colors']):
            row = coli // 2
            col = coli % 2
            grid_layout.setColumnStretch(col, 1)

            cf = QWidget(grid)
            cf.setStyleSheet("background: transparent;")
            cf_layout = QVBoxLayout(cf)
            cf_layout.setContentsMargins(0, 0, 0, 0)
            cf_layout.setSpacing(2)

            # Color name label
            color_label_text = color_names[coli] if coli < len(color_names) else f"Color {coli + 1}"
            color_name_lbl = QLabel(color_label_text, cf)
            color_name_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            color_name_lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            cf_layout.addWidget(color_name_lbl)

            color_row = QWidget(cf)
            color_row.setStyleSheet("background: transparent;")
            color_row_layout = QHBoxLayout(color_row)
            color_row_layout.setContentsMargins(0, 2, 0, 0)
            color_row_layout.setSpacing(8)

            # Color preview swatch (clickable)
            hex_color = f"#{color['r']:02x}{color['g']:02x}{color['b']:02x}"
            swatch = QFrame(color_row)
            swatch.setFixedSize(40, 40)
            swatch.setStyleSheet(
                f"background-color: {hex_color}; border-radius: 6px; "
                f"border: 2px solid {P['border']};"
            )
            swatch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            color_row_layout.addWidget(swatch)

            # RGB inputs
            rgb_frame = QWidget(color_row)
            rgb_frame.setStyleSheet("background: transparent;")
            rgb_layout = QHBoxLayout(rgb_frame)
            rgb_layout.setContentsMargins(0, 0, 0, 0)
            rgb_layout.setSpacing(4)

            r_entry = QLineEdit(rgb_frame)
            g_entry = QLineEdit(rgb_frame)
            b_entry = QLineEdit(rgb_frame)

            for label_text, entry, rgb_val in [("R", r_entry, color['r']),
                                                ("G", g_entry, color['g']),
                                                ("B", b_entry, color['b'])]:
                inp_frame = QWidget(rgb_frame)
                inp_frame.setStyleSheet("background: transparent;")
                inp_layout = QVBoxLayout(inp_frame)
                inp_layout.setContentsMargins(0, 0, 0, 0)
                inp_layout.setSpacing(0)
                lbl = QLabel(label_text, inp_frame)
                lbl.setFont(QFont("Consolas", 11))
                lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
                inp_layout.addWidget(lbl)
                entry.setFixedHeight(28)
                entry.setFixedWidth(60)
                entry.setFont(QFont("Consolas", 13))
                entry.setStyleSheet(
                    f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                    f"color: {P['text_main']}; padding: 2px 4px; border-radius: 4px; }}"
                )
                entry.setText(str(rgb_val))
                inp_layout.addWidget(entry)
                rgb_layout.addWidget(inp_frame)

            # Hex input
            hex_frame = QWidget(rgb_frame)
            hex_frame.setStyleSheet("background: transparent;")
            hex_layout = QVBoxLayout(hex_frame)
            hex_layout.setContentsMargins(8, 0, 0, 0)
            hex_layout.setSpacing(0)
            hex_lbl = QLabel(ui_text("ui_costume_hex"), hex_frame)
            hex_lbl.setFont(QFont("Consolas", 11))
            hex_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            hex_layout.addWidget(hex_lbl)
            hex_entry = QLineEdit(hex_frame)
            hex_entry.setFixedHeight(28)
            hex_entry.setFixedWidth(80)
            hex_entry.setFont(QFont("Consolas", 13))
            hex_entry.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['text_main']}; padding: 2px 4px; border-radius: 4px; }}"
            )
            hex_entry.setText(hex_color)
            hex_layout.addWidget(hex_entry)
            rgb_layout.addWidget(hex_frame)

            rgb_layout.addStretch()
            color_row_layout.addWidget(rgb_frame, 1)

            # Bind updates: RGB -> hex+swatch, hex -> RGB+swatch
            def _make_rgb_callback(re, ge, be, he, sw):
                def cb(_text=None):
                    try:
                        r = max(0, min(255, int(re.text())))
                        g = max(0, min(255, int(ge.text())))
                        b = max(0, min(255, int(be.text())))
                        hx = f"#{r:02x}{g:02x}{b:02x}"
                        he.blockSignals(True)
                        he.setText(hx)
                        he.blockSignals(False)
                        sw.setStyleSheet(
                            f"background-color: {hx}; border-radius: 6px; "
                            f"border: 2px solid {P['border']};"
                        )
                    except ValueError:
                        pass
                return cb

            def _make_hex_callback(re, ge, be, he, sw):
                def cb(_text=None):
                    try:
                        hx = he.text().strip()
                        if len(hx) == 7 and hx[0] == '#':
                            r = int(hx[1:3], 16)
                            g = int(hx[3:5], 16)
                            b = int(hx[5:7], 16)
                            re.blockSignals(True)
                            ge.blockSignals(True)
                            be.blockSignals(True)
                            re.setText(str(r))
                            ge.setText(str(g))
                            be.setText(str(b))
                            re.blockSignals(False)
                            ge.blockSignals(False)
                            be.blockSignals(False)
                            sw.setStyleSheet(
                                f"background-color: {hx}; border-radius: 6px; "
                                f"border: 2px solid {P['border']};"
                            )
                    except ValueError:
                        pass
                return cb

            rgb_cb = _make_rgb_callback(r_entry, g_entry, b_entry, hex_entry, swatch)
            hex_cb = _make_hex_callback(r_entry, g_entry, b_entry, hex_entry, swatch)

            r_entry.textChanged.connect(rgb_cb)
            g_entry.textChanged.connect(rgb_cb)
            b_entry.textChanged.connect(rgb_cb)
            hex_entry.textChanged.connect(hex_cb)

            # Color picker on swatch click
            def _make_pick_color(re, ge, be, he, sw):
                def handler(event):
                    try:
                        init_r, init_g, init_b = int(re.text()), int(ge.text()), int(be.text())
                    except ValueError:
                        init_r, init_g, init_b = 128, 128, 128
                    initial = QColor(init_r, init_g, init_b)
                    color = QColorDialog.getColor(initial, self, self.t("dlg_title_choose_color"))
                    if color.isValid():
                        re.setText(str(color.red()))
                        ge.setText(str(color.green()))
                        be.setText(str(color.blue()))
                return handler

            swatch.mousePressEvent = _make_pick_color(r_entry, g_entry, b_entry, hex_entry, swatch)

            # Delete color button — icon only, no text
            del_btn = QPushButton("", color_row)
            del_btn.setFixedSize(28, 28)
            del_btn.setIcon(qta.icon("fa6s.xmark", color=ui_text("ui_costume_c0392b")))
            del_btn.setIconSize(QSize(14, 14))
            del_btn.setStyleSheet(ss_btn(danger=True))
            del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_btn.clicked.connect(lambda checked, c=ci, co=coli: self._remove_color(c, co))
            color_row_layout.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignTop)

            cf_layout.addWidget(color_row)
            grid_layout.addWidget(cf, row, col)

            self._color_widgets.append((ci, coli, cf, r_entry, g_entry, b_entry))

        sec_layout.addWidget(grid)

        # Add Color button at the bottom of the slot card
        add_color_row = QWidget(sec)
        add_color_row.setStyleSheet("background: transparent;")
        add_color_row_layout = QHBoxLayout(add_color_row)
        add_color_row_layout.setContentsMargins(0, 4, 0, 0)
        add_color_row_layout.setSpacing(0)
        add_color_btn = QPushButton(self.t("btn_add_color"), add_color_row)
        add_color_btn.setFixedHeight(28)
        add_color_btn.setFont(QFont("Segoe UI", 10))
        add_color_btn.setIcon(qta.icon("fa6s.plus", color=P["text_main"]))
        add_color_btn.setIconSize(QSize(12, 12))
        add_color_btn.setStyleSheet(ss_btn())
        add_color_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_color_btn.clicked.connect(lambda checked, c=ci: self._add_color_entry(char, c))
        add_color_row_layout.addWidget(add_color_btn)
        add_color_row_layout.addStretch()
        sec_layout.addWidget(add_color_row)

        self._editor_layout.addWidget(sec)

    def _get_color_names(self, count):
        tint_letters = "ABCDEF"
        return [
            self.t("color_tint", letter=tint_letters[i]) if i < len(tint_letters)
            else self.t("color_tint_n", n=i + 1)
            for i in range(count)
        ]

    # Costume/color management

    def _add_costume_slot(self, char):
        self._apply_colors()
        max_slot = max((c['slot'] for c in char['costumes']), default=-1)
        new_slot = max_slot + 1
        char['costumes'].append({
            'slot': new_slot,
            'colors': [
                {'r': 128, 'g': 128, 'b': 128},
                {'r': 64, 'g': 64, 'b': 64},
            ]
        })
        self._build_editor(char)

    def _add_color_entry(self, char, ci):
        self._apply_colors()
        if not char['costumes']:
            return
        char['costumes'][ci]['colors'].append({'r': 128, 'g': 128, 'b': 128})
        self._build_editor(char)

    def _remove_costume(self, costume_idx):
        if not self._current_char:
            return
        char = self._current_char
        if len(char['costumes']) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("msg_cannot_remove_last_costume"))
            return
        self._apply_colors()
        del char['costumes'][costume_idx]
        self._build_editor(char)

    def _remove_color(self, costume_idx, color_idx):
        if not self._current_char:
            return
        char = self._current_char
        costume = char['costumes'][costume_idx]
        if len(costume['colors']) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("msg_cannot_remove_last_color"))
            return
        self._apply_colors()
        del costume['colors'][color_idx]
        self._build_editor(char)

    # Character management

    def _add_new_char(self):
        if not self._raw_data:
            return
        self._apply_colors()
        char = {
            'char_id': 'new_ch',
            'name': self.t("default_char_name"),
            'costumes': [
                {
                    'slot': 0,
                    'colors': [
                        {'r': 200, 'g': 200, 'b': 200},
                        {'r': 100, 'g': 100, 'b': 100},
                        {'r': 150, 'g': 150, 'b': 150},
                        {'r': 80, 'g': 80, 'b': 80},
                    ]
                }
            ]
        }
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)

    def _duplicate_char(self):
        if not self._raw_data or not self._current_char:
            return
        self._apply_colors()
        char = copy.deepcopy(self._current_char)
        char['name'] = self._current_char['name'] + self.t("msg_copy_suffix")
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)

    def _delete_char(self):
        if not self._raw_data or not self._current_char:
            return
        if len(self._characters) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("msg_cannot_delete_last_char"))
            return
        name = self._current_char['name']
        reply = QMessageBox.question(
            self, self.t("dlg_title_confirm_delete"),
            self.t("msg_confirm_delete_item", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._color_widgets = []
        self._characters.remove(self._current_char)
        self._current_char = None
        self._populate_list()
