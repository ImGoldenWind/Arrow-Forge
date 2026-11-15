from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_main_label,
    ss_panel_title,
    ss_sidebar_btn,
    ss_tab_widget,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
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
import threading
import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QColorDialog, QSizePolicy, QTabWidget,
)
from PyQt6.QtGui import QFont, QColor, QCursor
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from core.themes import P
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonListRow, SkeletonBar
from parsers.costume_parser import parse_costume_xfbin, save_costume_xfbin
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


def _truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 3)] + "..."


def _color_chip_style(hex_color, *, radius=4, border_width=1, border_color=None):
    border = border_color or P["border"]
    return (
        f"background-color: {hex_color}; border: {border_width}px solid {border}; "
        f"border-radius: {radius}px;"
    )


def _color_dot_style(hex_color):
    return f"background-color: {hex_color}; border-radius: 6px; border: none;"


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
        self._dirty = False
        self._char_buttons = []
        self._notes = b''
        self._costume_frames = []  # list of QFrame, one per costume section
        self._last_compact = None

        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_error.connect(self._on_load_error)

        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        self.setStyleSheet(ss_bg_dark())
        outer_layout = QVBoxLayout(self)
        configure_layout(outer_layout, LayoutRole.ROOT)

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

        outer_layout.addWidget(top)

        # Separator
        sep = EditorSeparator(self, accent=True)


        outer_layout.addWidget(sep)

        # Main area
        main = QWidget(self)
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Character list sidebar
        list_frame = EditorSidebar(main, width=276)


        list_layout = list_frame.content_layout


        # Search
        search_frame = QWidget(list_frame)
        search_frame.setStyleSheet(ss_transparent())
        search_layout = QHBoxLayout(search_frame)
        configure_layout(search_layout, LayoutRole.ROOT)
        self._search_entry = QLineEdit(search_frame)
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(self._filter_list)
        search_layout.addWidget(self._search_entry)
        list_layout.addWidget(search_frame)

        # Actions
        actions_frame = EditorActionRow(list_frame)
        actions_layout = actions_frame.content_layout
        btn_font = ui_font(TypeSize.BODY)

        self._add_btn = QPushButton(self.t("btn_new"), actions_frame)
        self._add_btn.setEnabled(False)
        configure_button(self._add_btn, height=Size.COMPACT_CONTROL)
        self._add_btn.clicked.connect(self._add_new_char)
        self._add_btn.setProperty("designAction", 'new')
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"), actions_frame)
        self._dup_btn.setEnabled(False)
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.clicked.connect(self._duplicate_char)
        self._dup_btn.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"), actions_frame)
        self._del_btn.setEnabled(False)
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.clicked.connect(self._delete_char)
        self._del_btn.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._del_btn, 1)

        list_layout.addWidget(actions_frame)

        # Scrollable character list
        self._char_scroll = QScrollArea(list_frame)


        configure_scrollarea(self._char_scroll, transparent=True)
        self._char_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._char_list_widget = QWidget()
        self._char_list_widget.setMinimumWidth(0)
        self._char_list_widget.setStyleSheet(ss_transparent())
        self._char_list_layout = QVBoxLayout(self._char_list_widget)
        configure_layout(self._char_list_layout, LayoutRole.LIST)
        self._char_list_layout.addStretch()
        self._char_scroll.setWidget(self._char_list_widget)
        list_layout.addWidget(self._char_scroll)

        main_layout.addWidget(list_frame)

        # Divider line
        divider = EditorSeparator(main, orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        # Editor panel (scrollable)
        self._editor_scroll = QScrollArea(main)


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)

        self._show_placeholder()

        main_layout.addWidget(self._editor_scroll, 1)

        outer_layout.addWidget(main, 1)

    # File loading

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_costume"), game_files_dialog_dir(target_patterns="PlayerColorParam.bin.xfbin"),
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        create_backup_on_open(path)
        set_file_label_empty(self._file_label, self.t("loading"))
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

        hdr, hdr_layout = self._make_editor_card(margins=(16, 14, 16, 14), spacing=8)
        hdr_layout.addWidget(SkeletonBar(hdr, height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)
        configure_layout(self._editor_layout, LayoutRole.PAGE)

        for _ in range(3):
            sec, sec_layout = self._make_editor_card(margins=(12, 12, 12, 12), spacing=8)

            g = QWidget(sec)
            g_layout = QGridLayout(g)
            configure_layout(g_layout, LayoutRole.TITLE)
            for col in range(4):
                f = QWidget(g)
                f_layout = QVBoxLayout(f)
                configure_layout(f_layout, LayoutRole.FIELD)
                f_layout.addWidget(SkeletonBar(f, height=11, corner_radius=3))
                f_layout.addWidget(SkeletonBar(f, height=30, corner_radius=4))
                g_layout.addWidget(f, 0, col)
            sec_layout.addWidget(g)
            self._editor_layout.addWidget(sec)
        self._editor_layout.addStretch()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        card = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=self.t("placeholder_costume"),
            icon_name="fa6s.palette",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        _clear_layout(self._char_list_layout)
        self._char_list_layout.addStretch()
        self._show_placeholder()
        self._filepath = None
        self._dirty = False
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, raw, characters, binary_offset, notes):
        self._raw_data = raw
        self._characters = characters
        self._binary_offset = binary_offset
        self._notes = notes
        self._filepath = path
        self._dirty = False
        for char in self._characters:
            key = f"char_{char['char_id']}"
            translated = self.t(key)
            if translated != key:
                char['name'] = translated
        set_file_label(self._file_label, path)
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._populate_list()

    # Save

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not self._raw_data:
            return
        self._apply_colors()
        if not save_path:
            return
        try:
            path = save_path
            save_costume_xfbin(path, self._raw_data, self._characters, self._binary_offset, self._notes)
            commit_save_path(self, save_path)
            self._dirty = False
            set_file_label(self._file_label, path)
            QMessageBox.information(self, self.t('dlg_title_success'), self.t('msg_save_success', path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=e))

    # Character list

    def _populate_list(self):
        _clear_layout(self._char_list_layout)
        self._char_buttons = []
        for char in self._characters:
            btn = QPushButton(self._char_list_widget)
            btn.setFixedHeight(Size.LIST_ROW)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(ss_sidebar_btn())
            btn.clicked.connect(lambda checked, c=char: self._select_char(c))

            # Internal layout for the button content
            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(*Insets.LIST_ROW)
            btn_layout.setSpacing(Size.GAP_SM)

            # Text section
            text_widget = QWidget(btn)
            text_widget.setMinimumWidth(0)
            text_widget.setStyleSheet(ss_transparent())
            text_layout = QVBoxLayout(text_widget)
            configure_layout(text_layout, LayoutRole.ROOT)

            name_lbl = QLabel(_truncate(char['name'], 22), text_widget)
            name_lbl.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
            name_lbl.setStyleSheet(ss_main_label())
            name_lbl.setToolTip(char['name'])
            name_lbl.setMinimumWidth(0)
            name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout.addWidget(name_lbl)

            slots_count = len(char['costumes'])
            sub_key = "char_costumes_sub" if slots_count == 1 else "char_costumes_sub_plural"
            sub_text = self.t(sub_key, char_id=char['char_id'], n=slots_count)
            id_lbl = QLabel(_truncate(sub_text, 28), text_widget)
            id_lbl.setFont(mono_font(TypeSize.CODE))
            id_lbl.setStyleSheet(ss_dim_label())
            id_lbl.setToolTip(sub_text)
            id_lbl.setMinimumWidth(0)
            id_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
                btn.setStyleSheet(ss_sidebar_btn(selected=True))
            else:
                btn.setStyleSheet(ss_sidebar_btn())
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

    def _make_editor_card(self, parent=None, margins=Insets.CARD, spacing=Size.CARD_GAP):
        card, layout = make_editor_card(parent or self._editor_widget, margins=margins, spacing=spacing)
        card.setMinimumWidth(0)
        card.setMaximumWidth(16777215)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        return card, layout

    def _is_compact_editor(self):
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 760

    def _prep_field(self, frame, editor):
        configure_field(frame, editor)

    def _make_overview_field(self, parent, label, value, *, editable=False, font=None):
        frame, layout, _label, _hint = make_editor_field_shell(label)
        frame.setParent(parent)

        if editable:
            entry = QLineEdit(frame)
            configure_input(entry, height=Size.LARGE_CONTROL, monospace=True, font=font)
            entry.setText(str(value))
            entry.setMinimumWidth(0)
            entry.setCursorPosition(0)
            self._prep_field(frame, entry)
            layout.addWidget(entry)
            return frame, entry

        value_lbl = QLabel(str(value), frame)
        value_lbl.setFont(font or mono_font(TypeSize.DISPLAY, QFont.Weight.Bold))
        value_lbl.setStyleSheet(ss_main_label())
        value_lbl.setMinimumWidth(0)
        value_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(value_lbl)
        return frame, value_lbl

    def _slot_title(self, costume):
        slot = costume['slot']
        slot_label = self.t("costume_default") if slot == 0 else self.t("costume_slot_n", n=slot)
        return self.t("costume_slot_header", slot=slot, label=slot_label)

    def _build_editor(self, char):
        _clear_layout(self._editor_layout)
        self._color_widgets = []
        self._char_id_entry = None
        self._name_entry = None
        self._costume_frames = []
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._last_compact = self._is_compact_editor()

        hdr, hdr_wrap_layout = self._make_editor_card(margins=Insets.CARD, spacing=Size.CARD_GAP)
        add_editor_card_title(hdr_wrap_layout, char['name'], 'fa6s.palette', subtitle=f"{char['char_id']} / {len(char['costumes'])} {self.t('label_costumes').lower()}")
        hdr_layout = QGridLayout()
        configure_layout(hdr_layout, LayoutRole.GRID_TITLED)

        name_frame, self._name_entry = self._make_overview_field(
            hdr, self.t("label_display_name"), char['name'],
            editable=True, font=ui_font(TypeSize.DISPLAY, QFont.Weight.Bold)
        )
        id_frame, self._char_id_entry = self._make_overview_field(
            hdr, self.t("label_char_id_short"), char['char_id'],
            editable=True, font=mono_font(TypeSize.LARGE)
        )
        count_frame, _ = self._make_overview_field(
            hdr, self.t("label_costumes"), len(char['costumes']),
            font=mono_font(TypeSize.DISPLAY, QFont.Weight.Bold)
        )
        if self._last_compact:
            hdr_layout.addWidget(name_frame, 0, 0)
            hdr_layout.addWidget(id_frame, 1, 0)
            hdr_layout.addWidget(count_frame, 2, 0)
            hdr_layout.setColumnStretch(0, 1)
        else:
            hdr_layout.addWidget(name_frame, 0, 0, 1, 2)
            hdr_layout.addWidget(id_frame, 1, 0)
            hdr_layout.addWidget(count_frame, 1, 1)
            hdr_layout.setColumnStretch(0, 2)
            hdr_layout.setColumnStretch(1, 1)
        hdr_wrap_layout.addLayout(hdr_layout)
        self._editor_layout.addWidget(hdr)

        tabs = QTabWidget(self._editor_widget)
        tabs.setDocumentMode(True)
        tabs.setStyleSheet(ss_tab_widget())
        tabs.setMinimumWidth(0)
        tabs.setMaximumWidth(16777215)
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        tabs.tabBar().setUsesScrollButtons(True)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        for ci, costume in enumerate(char['costumes']):
            tab = QWidget(tabs)
            tab.setStyleSheet(ss_transparent())
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 10, 0, 0)
            tab_layout.setSpacing(Size.GAP)
            tab_layout.addWidget(
                self._build_costume_section(char, ci, costume, tab),
                0,
                Qt.AlignmentFlag.AlignTop,
            )
            tab_layout.addStretch()
            tabs.addTab(tab, f"Slot {costume['slot']}")
        self._editor_layout.addWidget(tabs)

        add_costume_btn = QPushButton(self.t("btn_add_costume_slot"), self._editor_widget)
        add_costume_btn.setIcon(qta.icon("fa6s.plus", color=P["text_main"]))
        configure_button(add_costume_btn)
        add_costume_btn.clicked.connect(lambda: self._add_costume_slot(char))
        add_costume_btn.setProperty("designAction", 'new')
        self._editor_layout.addWidget(add_costume_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._editor_layout.addSpacing(20)
        self._editor_layout.addStretch()
        return

    def _build_costume_section(self, char, ci, costume, parent=None):
        sec, sec_layout = self._make_editor_card(parent)
        self._costume_frames.append(sec)
        compact_section = self._is_compact_editor()

        header = QWidget(sec)
        header.setStyleSheet(ss_transparent())
        header_layout = QHBoxLayout(header)
        configure_layout(header_layout, LayoutRole.TITLE)

        slot_title = self._slot_title(costume)
        slot_lbl = QLabel(_truncate(slot_title, 26 if compact_section else 56), header)
        slot_lbl.setFont(ui_font(TypeSize.SECTION, QFont.Weight.Bold))
        slot_lbl.setStyleSheet(ss_panel_title())
        slot_lbl.setMinimumWidth(0)
        slot_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        slot_lbl.setToolTip(slot_title)
        header_layout.addWidget(slot_lbl, 1 if compact_section else 0)
        if not compact_section:
            header_layout.addStretch()

        chip_limit = 2 if compact_section else 6
        for color in costume['colors'][:chip_limit]:
            hx = f"#{color['r']:02x}{color['g']:02x}{color['b']:02x}"
            chip = QFrame(header)
            chip.setFixedSize(26 if compact_section else 34, 16 if compact_section else 18)
            chip.setStyleSheet(_color_chip_style(hx, radius=4, border_width=1))
            header_layout.addWidget(chip)

        remove_btn = QPushButton(self.t("btn_remove"), header)
        if compact_section:
            remove_btn.setFixedWidth(34)
            remove_btn.setText("")
            remove_btn.setToolTip(self.t("btn_remove"))
        remove_btn.setIcon(qta.icon("fa6s.trash", color=ui_text("ui_costume_ffffff")))
        remove_btn.setIconSize(QSize(14, 14))
        configure_button(remove_btn, danger=True, height=Size.COMPACT_CONTROL)
        remove_btn.clicked.connect(lambda checked, c=ci: self._remove_costume(c))
        remove_btn.setProperty("designAction", 'delete')
        header_layout.addWidget(remove_btn)
        sec_layout.addWidget(header)

        grid = QWidget(sec)
        grid.setStyleSheet(ss_transparent())
        grid.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(*Insets.GRID_TITLE)
        grid_layout.setHorizontalSpacing(Size.GRID_GAP)
        grid_layout.setVerticalSpacing(14)

        color_names = self._get_color_names(len(costume['colors']))
        colors_per_row = 1 if compact_section else 2
        compact_color_card = colors_per_row == 1
        for coli, color in enumerate(costume['colors']):
            row, col = divmod(coli, colors_per_row)
            grid_layout.setColumnStretch(col, 1)

            cf, cf_layout = self._make_editor_card(grid, margins=(14, 12, 14, 12), spacing=8)
            color_label_text = color_names[coli] if coli < len(color_names) else f"Color {coli + 1}"

            title_row = QWidget(cf)
            title_row.setStyleSheet(ss_transparent())
            title_layout = QHBoxLayout(title_row)
            configure_layout(title_layout, LayoutRole.TITLE)
            dot = QFrame(title_row)
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(_color_dot_style(f"#{color['r']:02x}{color['g']:02x}{color['b']:02x}"))
            title_layout.addWidget(dot)
            color_name_lbl = QLabel(color_label_text, title_row)
            color_name_lbl.setFont(ui_font(TypeSize.LABEL, QFont.Weight.Bold))
            color_name_lbl.setStyleSheet(ss_panel_title())
            title_layout.addWidget(color_name_lbl)
            title_layout.addStretch()

            del_btn = QPushButton("", title_row)
            del_btn.setFixedSize(28, 28)
            del_btn.setIcon(qta.icon("fa6s.xmark", color=ui_text("ui_costume_c0392b")))
            del_btn.setIconSize(QSize(14, 14))
            configure_button(del_btn, danger=True)
            del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_btn.clicked.connect(lambda checked, c=ci, co=coli: self._remove_color(c, co))
            del_btn.setProperty("designAction", 'delete')
            title_layout.addWidget(del_btn)
            cf_layout.addWidget(title_row)

            color_row = QWidget(cf)
            color_row.setStyleSheet(ss_transparent())
            color_row_layout = QVBoxLayout(color_row) if compact_color_card else QHBoxLayout(color_row)
            configure_layout(color_row_layout, LayoutRole.TITLE)

            hex_color = f"#{color['r']:02x}{color['g']:02x}{color['b']:02x}"
            swatch = QFrame(color_row)
            swatch.setFixedSize(76, 76)
            swatch.setStyleSheet(_color_chip_style(hex_color, radius=6, border_width=2))
            swatch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            swatch_alignment = Qt.AlignmentFlag.AlignLeft if compact_color_card else Qt.AlignmentFlag.AlignTop
            color_row_layout.addWidget(swatch, 0, swatch_alignment)

            input_grid = QGridLayout()
            input_grid.setContentsMargins(*Insets.NONE)
            input_grid.setHorizontalSpacing(Size.GAP)
            input_grid.setVerticalSpacing(6)
            r_entry = QLineEdit(color_row)
            g_entry = QLineEdit(color_row)
            b_entry = QLineEdit(color_row)
            hex_entry = QLineEdit(color_row)

            for input_row, (label_text, entry, rgb_val) in enumerate([
                ("R", r_entry, color['r']),
                ("G", g_entry, color['g']),
                ("B", b_entry, color['b']),
            ]):
                lbl = QLabel(label_text, color_row)
                lbl.setFont(mono_font(TypeSize.CODE))
                lbl.setStyleSheet(ss_dim_label())
                input_grid.addWidget(lbl, input_row, 0)
                entry.setMinimumWidth(0)
                entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                configure_input(entry, monospace=True)
                entry.setText(str(rgb_val))
                input_grid.addWidget(entry, input_row, 1)

            hex_lbl = QLabel(ui_text("ui_costume_hex"), color_row)
            hex_lbl.setFont(mono_font(TypeSize.CODE))
            hex_lbl.setStyleSheet(ss_dim_label())
            input_grid.addWidget(hex_lbl, 3, 0)
            hex_entry.setMinimumWidth(0)
            hex_entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            configure_input(hex_entry, monospace=True)
            hex_entry.setText(hex_color)
            input_grid.addWidget(hex_entry, 3, 1)
            input_grid.setColumnStretch(1, 1)

            if compact_color_card:
                color_row_layout.addLayout(input_grid)
            else:
                color_row_layout.addLayout(input_grid, 1)
            cf_layout.addWidget(color_row)

            def _make_rgb_callback(re, ge, be, he, sw, color_dot):
                def cb(_text=None):
                    try:
                        r = max(0, min(255, int(re.text())))
                        g = max(0, min(255, int(ge.text())))
                        b = max(0, min(255, int(be.text())))
                        hx = f"#{r:02x}{g:02x}{b:02x}"
                        he.blockSignals(True)
                        he.setText(hx)
                        he.blockSignals(False)
                        sw.setStyleSheet(_color_chip_style(hx, radius=6, border_width=2))
                        color_dot.setStyleSheet(_color_dot_style(hx))
                    except ValueError:
                        pass
                return cb

            def _make_hex_callback(re, ge, be, he, sw, color_dot):
                def cb(_text=None):
                    try:
                        hx = he.text().strip()
                        if len(hx) == 7 and hx[0] == '#':
                            r = int(hx[1:3], 16)
                            g = int(hx[3:5], 16)
                            b = int(hx[5:7], 16)
                            for entry, value in ((re, r), (ge, g), (be, b)):
                                entry.blockSignals(True)
                                entry.setText(str(value))
                                entry.blockSignals(False)
                            sw.setStyleSheet(_color_chip_style(hx, radius=6, border_width=2))
                            color_dot.setStyleSheet(_color_dot_style(hx))
                    except ValueError:
                        pass
                return cb

            rgb_cb = _make_rgb_callback(r_entry, g_entry, b_entry, hex_entry, swatch, dot)
            hex_cb = _make_hex_callback(r_entry, g_entry, b_entry, hex_entry, swatch, dot)
            r_entry.textChanged.connect(rgb_cb)
            g_entry.textChanged.connect(rgb_cb)
            b_entry.textChanged.connect(rgb_cb)
            hex_entry.textChanged.connect(hex_cb)
            r_entry.textEdited.connect(self._mark_dirty)
            g_entry.textEdited.connect(self._mark_dirty)
            b_entry.textEdited.connect(self._mark_dirty)
            hex_entry.textEdited.connect(self._mark_dirty)

            def _make_pick_color(re, ge, be):
                def handler(event):
                    try:
                        init_r, init_g, init_b = int(re.text()), int(ge.text()), int(be.text())
                    except ValueError:
                        init_r, init_g, init_b = 128, 128, 128
                    color = QColorDialog.getColor(QColor(init_r, init_g, init_b), self, self.t("dlg_title_choose_color"))
                    if color.isValid():
                        re.setText(str(color.red()))
                        ge.setText(str(color.green()))
                        be.setText(str(color.blue()))
                        self._mark_dirty()
                return handler

            swatch.mousePressEvent = _make_pick_color(r_entry, g_entry, b_entry)
            grid_layout.addWidget(cf, row, col)
            self._color_widgets.append((ci, coli, cf, r_entry, g_entry, b_entry))

        sec_layout.addWidget(grid)

        add_color_btn = QPushButton(self.t("btn_add_color"), sec)
        add_color_btn.setIcon(qta.icon("fa6s.plus", color=P["text_main"]))
        add_color_btn.setIconSize(QSize(12, 12))
        configure_button(add_color_btn, height=Size.COMPACT_CONTROL)
        add_color_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add_color_btn.clicked.connect(lambda checked, c=ci: self._add_color_entry(char, c))
        add_color_btn.setProperty("designAction", 'new')
        sec_layout.addWidget(add_color_btn, 0, Qt.AlignmentFlag.AlignLeft)
        return sec

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
        self._mark_dirty()

    def _add_color_entry(self, char, ci):
        self._apply_colors()
        if not char['costumes']:
            return
        char['costumes'][ci]['colors'].append({'r': 128, 'g': 128, 'b': 128})
        self._build_editor(char)
        self._mark_dirty()

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
        self._mark_dirty()

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
        self._mark_dirty()

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
        self._mark_dirty()

    def _duplicate_char(self):
        if not self._raw_data or not self._current_char:
            return
        self._apply_colors()
        char = copy.deepcopy(self._current_char)
        char['name'] = self._current_char['name'] + self.t("msg_copy_suffix")
        self._characters.append(char)
        self._populate_list()
        self._select_char(char)
        self._mark_dirty()

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
        self._mark_dirty()

    def _mark_dirty(self, *_):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_char is None or self._last_compact is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            return
        self._apply_colors()
        QTimer.singleShot(0, self._rebuild_current_for_width)

    def _rebuild_current_for_width(self):
        if self._current_char is not None:
            self._build_editor(self._current_char)
