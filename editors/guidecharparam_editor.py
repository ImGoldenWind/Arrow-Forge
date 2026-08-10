"""editors/guidecharparam_editor.py  –  Full editor for GuideCharParam.bin.xfbin."""

import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.style_helpers import (
    make_empty_state,
    make_editor_field_shell,
    make_editor_grid_card,
    ss_btn, ss_sep, ss_accent_sep, ss_input, ss_search,
    ss_accent_label, ss_dim_label, ss_main_label,
    ss_scrollarea, ss_scrollarea_transparent, ss_sidebar_btn,
    ss_file_label, ss_transparent,
    ss_bg_dark, ss_bg_panel, ss_sidebar_frame,
    TOOLBAR_H, TOOLBAR_BTN_H,
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
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


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
        self._last_compact: bool | None = None

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
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
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 12)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)

        self._show_placeholder(ui_text("ui_guidecharparam_open_a_guidecharparam_bin_xfbin_file_to_begin_editing"))
        self.setStyleSheet(ss_bg_dark())

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(TOOLBAR_H)
        bar.setStyleSheet(ss_bg_panel())

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
        self._lbl_file.setStyleSheet(ss_file_label())
        layout.addWidget(self._lbl_file)
        layout.addStretch()

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(ss_sidebar_frame())

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(ui_text("search_placeholder"))
        self._search_box.setFixedHeight(32)
        self._search_box.setFont(QFont("Segoe UI", 13))
        self._search_box.setStyleSheet(ss_search())
        self._search_box.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_box)

        btn_row = QWidget()
        btn_row.setStyleSheet(ss_transparent())
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
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
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
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.book-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _clear_editor(self):
        while self._editor_layout.count():
            item = self._editor_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

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
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=selected))

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        event_text = e.get("event", ui_text("ui_guidecharparam_no_event"))
        event_lbl = QLabel(_truncate(event_text, 24))
        event_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        event_lbl.setStyleSheet(ss_main_label())
        event_lbl.setMinimumWidth(0)
        event_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        event_lbl.setToolTip(event_text)
        event_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(event_lbl)

        char = e.get("character", "")
        char_label = _CHAR_LABELS.get(char, char)
        sub_lbl = QLabel(_truncate(char_label, 28))
        sub_lbl.setFont(QFont("Consolas", 11))
        sub_lbl.setStyleSheet(ss_dim_label())
        sub_lbl.setMinimumWidth(0)
        sub_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sub_lbl.setToolTip(char_label)
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(sub_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        return btn

    def _select_entry(self, idx: int):
        self._current_idx = idx
        for btn, bi in self._entry_buttons:
            if bi == idx:
                btn.setStyleSheet(ss_sidebar_btn(selected=True))
                self._list_scroll.ensureWidgetVisible(btn)
            else:
                btn.setStyleSheet(ss_sidebar_btn())
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(self._entries[idx])

    def _on_filter_changed(self):
        self._filter_text = self._search_box.text()
        self._rebuild_list()

    # Editor building

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _prep_card(self, card: QFrame):
        card.setMinimumWidth(0)
        card.setMaximumWidth(980)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _add_editor_card(self, card: QFrame):
        self._editor_layout.addWidget(card)

    def _add_section(self, title: str, icon_name: str = "fa6s.sliders"):
        self._pending_section_title = title
        self._pending_section_icon = icon_name

    def _add_card(self) -> tuple[QFrame, QGridLayout]:
        section_title = getattr(self, "_pending_section_title", None)
        section_icon = getattr(self, "_pending_section_icon", "fa6s.sliders")
        self._pending_section_title = None
        self._pending_section_icon = "fa6s.sliders"
        card, grid = make_editor_grid_card(
            self._editor_widget,
            title=section_title,
            icon_name=section_icon,
            vertical_spacing=10,
        )
        self._prep_card(card)
        return card, grid

    def _prep_field_widget(self, widget: QWidget):
        widget.setMinimumWidth(0)
        widget.setMinimumHeight(54)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return widget

    def _add_le(self, grid: QGridLayout, row: int, col: int,
                label: str, value: str, key: str, col_span: int = 1) -> QLineEdit:
        le = QLineEdit()
        le.setFixedHeight(30)
        le.setFont(QFont("Consolas", 13))
        le.setStyleSheet(ss_input())
        le.setMinimumWidth(0)
        le.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        text = str(value)
        le.setText(text)
        le.setCursorPosition(next((i for i, ch in enumerate(text) if ch.isprintable() and ord(ch) >= 32 and ch not in {"\u25a1", "\ufffd"}), 0))

        container, cl, _label, _hint = make_editor_field_shell(label)
        self._prep_field_widget(container)
        cl.addWidget(le)

        grid.addWidget(container, row, col, 1, col_span)
        grid.setColumnStretch(col, 1)
        self._detail_widgets[key] = le
        le.textChanged.connect(lambda: None if self._loading_detail else self._save_current_entry())
        return le

    def _build_editor(self, e: dict):
        self._clear_editor()
        self._detail_widgets = {}
        self._loading_detail = True
        self._last_compact = self._is_compact_editor()
        compact = self._last_compact

        # Identity
        self._add_section(ui_text("skill_section_identity"), "fa6s.id-card")
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_guidecharparam_event_id"), e.get("event", ""), "event", col_span=1 if compact else 2)
        self._add_le(g, 1, 0, ui_text("ui_assist_character"), e.get("character", ""), "character")

        # Quick-pick combo for known characters
        container, cl, _label, _hint = make_editor_field_shell(ui_text("ui_guidecharparam_quick_pick_character"))
        self._prep_field_widget(container)
        cb_pick = QComboBox()
        cb_pick.setFixedHeight(30)
        cb_pick.setStyleSheet(ss_input())
        cb_pick.setMinimumWidth(0)
        cb_pick.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        cb_pick.setMinimumContentsLength(1)
        cb_pick.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb_pick.addItem(ui_text("ui_guidecharparam_select"), "")
        for ch in KNOWN_CHARACTERS:
            cb_pick.addItem(f"{_CHAR_LABELS.get(ch, ch)}  ({ch})", ch)
        char_val = e.get("character", "")
        for i in range(cb_pick.count()):
            if cb_pick.itemData(i) == char_val:
                cb_pick.setCurrentIndex(i)
                break
        cl.addWidget(cb_pick)
        g.addWidget(container, 2 if compact else 1, 0 if compact else 1)
        g.setColumnStretch(0, 1)
        if not compact:
            g.setColumnStretch(1, 1)
        cb_pick.currentIndexChanged.connect(
            lambda: None if self._loading_detail else self._on_char_picked(cb_pick)
        )

        self._add_editor_card(card)

        # Messages
        self._add_section(ui_text("ui_guidecharparam_message_slots"), "fa6s.comments")
        card, g = self._add_card()

        for j in range(5):
            if compact:
                header_row = j * 3
                name_row = header_row + 1
                message_row = header_row + 2
                message_col = 0
            else:
                header_row = j * 2
                name_row = header_row + 1
                message_row = name_row
                message_col = 1

            slot_title = f"Slot {j + 1}" + (ui_text("ui_guidecharparam_reserved") if j == 4 else "")
            slot_lbl = QLabel(slot_title)
            slot_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            slot_lbl.setStyleSheet(ss_accent_label())
            slot_lbl.setContentsMargins(0, 6 if j > 0 else 0, 0, 0)
            g.addWidget(slot_lbl, header_row, 0, 1, 1 if compact else 2)

            self._add_le(g, name_row, 0, ui_text("ui_guidecharparam_name_id"),    e.get(f"msg{j}_name",   ""), f"msg{j}_name")
            self._add_le(g, message_row, message_col, ui_text("ui_guidecharparam_message_id"), e.get(f"msg{j}_string", ""), f"msg{j}_string")

        self._add_editor_card(card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

        self._loading_detail = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx >= 0 and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx < 0 or self._last_compact is None:
            return
        compact = self._is_compact_editor()
        if compact != self._last_compact:
            self._apply_current_entry(mark_dirty=False)
            if 0 <= self._current_idx < len(self._entries):
                self._build_editor(self._entries[self._current_idx])

    def _on_char_picked(self, combo: QComboBox):
        val = combo.currentData()
        if val:
            char_le = self._detail_widgets.get("character")
            if char_le:
                char_le.setText(val)

    # Dynamic save

    def _save_current_entry(self):
        self._apply_current_entry(mark_dirty=True)

    def _apply_current_entry(self, *, mark_dirty: bool):
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

        if mark_dirty:
            self._mark_dirty()

        for btn, bi in self._entry_buttons:
            if bi == self._current_idx:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    event_text = e["event"] or ui_text("ui_guidecharparam_no_event")
                    char_text = _CHAR_LABELS.get(e["character"], e["character"])
                    labels[0].setText(_truncate(event_text, 24))
                    labels[0].setToolTip(event_text)
                    labels[1].setText(_truncate(char_text, 28))
                    labels[1].setToolTip(char_text)
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
