"""editors/guidecharparam_editor.py  –  Full editor for GuideCharParam.bin.xfbin."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_panel,
    ss_scrollarea, ss_section_label, ss_field_label,
    ss_placeholder, TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.guidecharparam_parser import (
    parse_guidecharparam_xfbin,
    save_guidecharparam_xfbin,
    make_default_entry,
    KNOWN_CHARACTERS,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

_CHAR_LABELS = {
    "guide_chara_speedwagon": ui_text("ui_guidecharparam_speedwagon_p1"),
    "guide_chara_polnareff":  ui_text("ui_guidecharparam_polnareff_p3"),
    "guide_chara_messina":    ui_text("ui_guidecharparam_messina_p2"),
    "guide_chara_melone":     ui_text("ui_guidecharparam_melone_p5"),
    "guide_chara_abbacchio":  ui_text("ui_guidecharparam_abbacchio_p5"),
    "guide_chara_emporio":    ui_text("ui_guidecharparam_emporio_p6"),
    "guide_chara_wangchen":   ui_text("ui_guidecharparam_wang_chen_p3"),
    "guide_chara_boingo":     ui_text("ui_guidecharparam_boingo_p4"),
    "guide_chara_derbyd":     ui_text("ui_guidecharparam_darby_d_p4"),
    "guide_chara_derbyt":     ui_text("ui_guidecharparam_darby_t_p4"),
    "guide_chara_giatcho":    ui_text("ui_guidecharparam_ghiaccio_p5"),
    "guide_chara_ringo":      ui_text("ui_guidecharparam_ringo_p7"),
}


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class GuideCharParamEditor(QWidget):
    """Embedded editor for GuideCharParam.bin.xfbin."""

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw: bytearray | None = None
        self._version: int = 1000
        self._entries: list[dict] = []
        self._dirty = False
        self._loading_detail = False
        self._filter_text = ""
        self._visible_indices: list[int] = []
        self._current_idx: int = -1
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._detail_widgets: dict = {}

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_sidebar())

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

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
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

        self._show_placeholder(ui_text("ui_guidecharparam_open_a_guidecharparam_bin_xfbin_file_to_begin_editing"))
        self.setStyleSheet(f"background-color: {P['bg_dark']}; color: {P['text_main']};")

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(TOOLBAR_H)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._on_save)
        layout.addWidget(self._btn_save)

        self._lbl_file = QLabel(ui_text("xfa_no_file"))
        self._lbl_file.setFont(QFont("Consolas", 12))
        self._lbl_file.setStyleSheet(
            f"color: {P['text_dim']}; background: transparent; text-decoration: none;"
        )
        layout.addWidget(self._lbl_file)
        layout.addStretch()

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(ui_text("search_placeholder"))
        self._search_box.setFixedHeight(32)
        self._search_box.setFont(QFont("Segoe UI", 13))
        self._search_box.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
            f"QLineEdit:focus {{ border: 1px solid {P['accent']}; }}"
        )
        self._search_box.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_box)

        btn_row = QWidget()
        btn_row.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 2, 0, 4)
        btn_layout.setSpacing(4)
        btn_font = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(ui_text("btn_new"))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(btn_font)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._on_add)
        btn_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_duplicate"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(btn_font)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._on_duplicate)
        btn_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(btn_font)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._on_delete)
        btn_layout.addWidget(self._btn_del, 1)

        layout.addWidget(btn_row)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
        )
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        layout.addWidget(self._list_scroll)

        return sidebar

    # Placeholder / editor clear

    def _show_placeholder(self, text: str = ui_text("ui_dictionaryparam_select_an_entry_to_edit")):
        self._clear_editor()
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(ss_placeholder())
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setContentsMargins(0, 60, 0, 60)
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    def _clear_editor(self):
        while self._editor_layout.count():
            item = self._editor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # List management

    def _rebuild_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        txt = self._filter_text.lower()
        self._visible_indices = []
        self._entry_buttons = []

        for i, e in enumerate(self._entries):
            event = e.get("event", "")
            char  = e.get("character", "")
            if txt and txt not in event.lower() and txt not in char.lower():
                continue
            self._visible_indices.append(i)
            btn = self._make_entry_button(e, i)
            self._list_layout.insertWidget(self._list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, i))

    def _make_entry_button(self, e: dict, idx: int) -> QPushButton:
        selected = (idx == self._current_idx)
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {P['bg_card'] if selected else 'transparent'}; "
            f"border-radius: 6px; text-align: left; padding: 0px; border: none; }}"
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        event_lbl = QLabel(e.get("event", ui_text("ui_guidecharparam_no_event")))
        event_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        event_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        event_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(event_lbl)

        char = e.get("character", "")
        char_label = _CHAR_LABELS.get(char, char)
        sub_lbl = QLabel(char_label)
        sub_lbl.setFont(QFont("Consolas", 11))
        sub_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(sub_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _select_entry(self, idx: int):
        self._current_idx = idx
        for btn, bi in self._entry_buttons:
            if bi == idx:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {P['bg_card']}; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }}"
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
                self._list_scroll.ensureWidgetVisible(btn)
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: transparent; border-radius: 6px; "
                    f"text-align: left; padding: 0px; border: none; }}"
                    f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
                )
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(self._entries[idx])

    def _on_filter_changed(self):
        self._filter_text = self._search_box.text()
        self._rebuild_list()

    # Editor building

    def _add_section(self, title: str):
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        lbl.setStyleSheet(ss_section_label())
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)

    def _add_card(self) -> tuple[QFrame, QGridLayout]:
        card = QFrame()
        card.setStyleSheet(ss_panel())
        inner = QWidget(card)
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(inner)
        return card, grid

    def _add_le(self, grid: QGridLayout, row: int, col: int,
                label: str, value: str, key: str) -> QLineEdit:
        le = QLineEdit()
        le.setFixedHeight(30)
        le.setFont(QFont("Consolas", 13))
        le.setStyleSheet(ss_input())
        le.setText(str(value))

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        cl.addWidget(lbl)
        cl.addWidget(le)

        grid.addWidget(container, row, col)
        grid.setColumnStretch(col, 1)
        self._detail_widgets[key] = le
        le.textChanged.connect(lambda: None if self._loading_detail else self._save_current_entry())
        return le

    def _build_editor(self, e: dict):
        self._clear_editor()
        self._detail_widgets = {}
        self._loading_detail = True

        # Identity
        self._add_section(ui_text("skill_section_identity"))
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_guidecharparam_event_id"),   e.get("event", ""),     "event")
        self._add_le(g, 0, 1, ui_text("ui_assist_character"),  e.get("character", ""), "character")

        # Quick-pick combo for known characters
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        lbl_pick = QLabel(ui_text("ui_guidecharparam_quick_pick_character"))
        lbl_pick.setFont(QFont("Segoe UI", 12))
        lbl_pick.setStyleSheet(ss_field_label())
        cl.addWidget(lbl_pick)
        cb_pick = QComboBox()
        cb_pick.setFixedHeight(30)
        cb_pick.setStyleSheet(ss_input())
        cb_pick.addItem(ui_text("ui_guidecharparam_select"), "")
        for ch in KNOWN_CHARACTERS:
            cb_pick.addItem(f"{_CHAR_LABELS.get(ch, ch)}  ({ch})", ch)
        char_val = e.get("character", "")
        for i in range(cb_pick.count()):
            if cb_pick.itemData(i) == char_val:
                cb_pick.setCurrentIndex(i)
                break
        cl.addWidget(cb_pick)
        g.addWidget(container, 1, 0)
        g.setColumnStretch(0, 1)
        cb_pick.currentIndexChanged.connect(
            lambda: None if self._loading_detail else self._on_char_picked(cb_pick)
        )

        self._editor_layout.addWidget(card)

        # Messages
        self._add_section(ui_text("ui_guidecharparam_message_slots"))
        card, g = self._add_card()

        for j in range(5):
            header_row = j * 2
            field_row  = j * 2 + 1

            slot_title = f"Slot {j + 1}" + (ui_text("ui_guidecharparam_reserved") if j == 4 else "")
            slot_lbl = QLabel(slot_title)
            slot_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            style = f"color: {P['secondary']}; background: transparent;"
            if j > 0:
                style += ui_text("ui_guidecharparam_margin_top_6px")
            slot_lbl.setStyleSheet(style)
            g.addWidget(slot_lbl, header_row, 0, 1, 2)

            self._add_le(g, field_row, 0, ui_text("ui_guidecharparam_name_id"),    e.get(f"msg{j}_name",   ""), f"msg{j}_name")
            self._add_le(g, field_row, 1, ui_text("ui_guidecharparam_message_id"), e.get(f"msg{j}_string", ""), f"msg{j}_string")

        self._editor_layout.addWidget(card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

        self._loading_detail = False

    def _on_char_picked(self, combo: QComboBox):
        val = combo.currentData()
        if val:
            char_le = self._detail_widgets.get("character")
            if char_le:
                char_le.setText(val)

    # Dynamic save

    def _save_current_entry(self):
        if self._current_idx < 0 or self._loading_detail:
            return
        e = self._entries[self._current_idx]

        def _txt(key, fallback="") -> str:
            w = self._detail_widgets.get(key)
            return w.text() if isinstance(w, QLineEdit) else fallback

        e["event"]     = _txt("event")
        e["character"] = _txt("character")
        for j in range(5):
            e[f"msg{j}_name"]   = _txt(f"msg{j}_name")
            e[f"msg{j}_string"] = _txt(f"msg{j}_string")

        self._mark_dirty()

        for btn, bi in self._entry_buttons:
            if bi == self._current_idx:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(e["event"] or ui_text("ui_guidecharparam_no_event"))
                    labels[1].setText(_CHAR_LABELS.get(e["character"], e["character"]))
                break

    # File operations

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_guidecharparam_open_guidecharparam_bin_xfbin"), game_files_dialog_dir(target_patterns="GuideCharParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_guidecharparam_xfbin(path)
        except Exception as ex:
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(ex))
            return
        self._filepath    = path
        self._raw         = raw
        self._version     = version
        self._entries     = entries
        self._dirty       = False
        self._current_idx = -1
        set_file_label(self._lbl_file, path)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._rebuild_list()
        if self._visible_indices:
            self._select_entry(self._visible_indices[0])
        else:
            self._show_placeholder(ui_text("ui_assist_no_entries_found"))

    def _on_save(self):
        if not self._filepath or self._raw is None:
            path, _ = QFileDialog.getSaveFileName(
                self, ui_text("ui_guidecharparam_save_guidecharparam_bin_xfbin"),
                ui_text("ui_guidecharparam_guidecharparam_bin_xfbin"),
                "XFBIN Files (*.xfbin);;All Files (*)"
            )
            if not path:
                return
            self._filepath = path
            set_file_label(self._lbl_file, path)
        try:
            save_guidecharparam_xfbin(self._filepath, self._raw, self._version, self._entries)
            with open(self._filepath, "rb") as fh:
                self._raw = bytearray(fh.read())
            self._dirty = False
            set_file_label(self._lbl_file, self._filepath)
            QMessageBox.information(self, ui_text("ui_assist_saved"),
                                    ui_text("ui_charviewer_saved_value_entries_to_value", p0=len(self._entries), p1=self._filepath))
        except Exception as ex:
            QMessageBox.critical(self, ui_text("ui_assist_save_error"), str(ex))

    # Add / Duplicate / Delete

    def _mark_dirty(self):
        self._dirty = True
        if self._filepath:
            set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _on_add(self):
        new_e = make_default_entry(len(self._entries))
        self._entries.append(new_e)
        self._mark_dirty()
        self._rebuild_list()
        self._select_entry(len(self._entries) - 1)

    def _on_duplicate(self):
        if self._current_idx < 0:
            return
        new_e = copy.deepcopy(self._entries[self._current_idx])
        new_e["event"] = new_e["event"] + "_COPY"
        insert_at = self._current_idx + 1
        self._entries.insert(insert_at, new_e)
        self._mark_dirty()
        self._rebuild_list()
        self._select_entry(insert_at)

    def _on_delete(self):
        if self._current_idx < 0:
            return
        e = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self, ui_text("dlg_title_confirm_delete"),
            ui_text("ui_charviewer_delete_entry_value", p0=e.get('event', self._current_idx)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        old_idx = self._current_idx
        del self._entries[old_idx]
        self._mark_dirty()
        self._current_idx = -1
        self._rebuild_list()
        if self._visible_indices:
            target = min(old_idx, len(self._visible_indices) - 1)
            self._select_entry(self._visible_indices[target])
        else:
            self._show_placeholder(ui_text("ui_dictionaryparam_select_an_entry_to_edit"))
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
