"""editors/speaking_editor.py  –  Editor for SpeakingLineParam.bin.xfbin."""

import os

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.themes import P
from core.style_helpers import ss_btn, ss_sep, TOOLBAR_H, TOOLBAR_BTN_H
from parsers.speaking_parser import (
    parse_speaking_xfbin, save_speaking_xfbin,
    INTERACTION_NAMES,
)
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


_CHAR_NAMES = {
    "0bao01": ui_text("char_0bao01"),
    "1jnt01": ui_text("char_1jnt01"),     "1zpl01": ui_text("char_1zpl01"),
    "1dio01": ui_text("char_1dio01"),           "1sdw01": ui_text("char_1sdw01"),
    "2jsp01": ui_text("char_2jsp01"),       "2csr01": ui_text("char_2csr01"),
    "2esd01": ui_text("char_2esd01"),              "2wmu01": ui_text("char_2wmu01"),
    "2krs01": ui_text("char_2krs01"),                 "2lsa01": ui_text("char_2lsa01"),
    "2shm01": ui_text("char_2shm01"),
    "3jtr01": ui_text("char_3jtr01"),          "3kki01": ui_text("char_3kki01"),
    "3jsp01": ui_text("char_3jsp01"),   "3pln01": ui_text("char_3pln01"),
    "3abd01": ui_text("char_3abd01"),       "3igy01": ui_text("char_3igy01"),
    "3hhs01": ui_text("char_3hhs01"),            "3vni01": ui_text("char_3vni01"),
    "3dio01": "DIO",                  "3mra01": ui_text("char_3mra01"),
    "3psp01": ui_text("char_3psp01"),
    "4jsk01": ui_text("char_4jsk01"), "4koi01": ui_text("char_4koi01"),
    "4oky01": ui_text("char_4oky01"),     "4kch01": ui_text("char_4kch01"),
    "4rhn01": ui_text("char_4rhn01"),        "4sgc01": ui_text("char_4sgc01"),
    "4fgm01": ui_text("char_4fgm01"),         "4oti01": ui_text("char_4oti01"),
    "4kir01": ui_text("char_4kir01"),       "4kwk01": ui_text("char_4kwk01"),
    "4jtr01": ui_text("char_4jtr01"), "4ykk01": ui_text("char_4ykk01"),
    "5grn01": ui_text("char_5grn01"),      "5mst01": ui_text("char_5mst01"),
    "5fgo01": ui_text("char_5fgo01"),      "5nrc01": ui_text("char_5nrc01"),
    "5bct01": ui_text("char_5bct01"),     "5abc01": ui_text("char_5abc01"),
    "5dvl01": ui_text("char_5dvl01"),              "5gac01": ui_text("char_5gac01"),
    "5prs01": ui_text("char_5prs01"),           "5trs01": ui_text("char_5trs01"),
    "5ris01": ui_text("char_5ris01"),
    "6jln01": ui_text("char_6jln01"),         "6elm01": ui_text("char_6elm01"),
    "6ans01": ui_text("char_6ans01"),       "6pci01": ui_text("char_6pci01"),
    "6pci02": ui_text("char_6pci02"),         "6fit01": ui_text("char_6fit01"),
    "6wet01": ui_text("char_6wet01"),
    "7jny01": ui_text("char_7jny01"),       "7jir01": ui_text("char_7jir01"),
    "7vtn01": ui_text("char_7vtn01"),      "7dio01": ui_text("char_7dio01"),
    "7dio02": ui_text("char_7dio02"),
    "8jsk01": ui_text("char_8jsk01"), "8wou01": ui_text("char_8wou01"),
}

_TYPE_ORDER = [1, 2, 3]  # Battle Start, Round Win, Battle Win


class SpeakingEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t             = t or (lambda k, **kw: k)
        self._embedded      = embedded
        self._filepath      = None
        self._original_data = None
        self._version       = 1000
        self._entries:      list[dict] = []
        self._orig_entries: list[dict] = []
        self._dirty         = False
        self._selected_pair: tuple[str, str] | None = None
        self._pair_buttons:  list[tuple[QPushButton, str, str]] = []
        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._on_open)
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._on_save)
        top_layout.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("xfa_no_file"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        top_layout.addWidget(self._file_lbl)
        top_layout.addStretch()

        root.addWidget(top)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_speaking_search_characters"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(
            f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        )
        self._search.textChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._search)

        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._btn_add = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setFont(btn_font)
        self._btn_add.setEnabled(False)
        self._btn_add.setStyleSheet(ss_btn())
        self._btn_add.clicked.connect(self._on_add)
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setFixedHeight(28)
        self._btn_dup.setFont(btn_font)
        self._btn_dup.setEnabled(False)
        self._btn_dup.setStyleSheet(ss_btn())
        self._btn_dup.clicked.connect(self._on_dup)
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setFixedHeight(28)
        self._btn_del.setFont(btn_font)
        self._btn_del.setEnabled(False)
        self._btn_del.setStyleSheet(ss_btn(danger=True))
        self._btn_del.clicked.connect(self._on_delete)
        actions_layout.addWidget(self._btn_del, 1)

        list_vlayout.addWidget(actions_frame)

        self._pair_scroll = QScrollArea()
        self._pair_scroll.setWidgetResizable(True)
        self._pair_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._pair_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
        )
        self._pair_list_widget = QWidget()
        self._pair_list_widget.setStyleSheet("background-color: transparent;")
        self._pair_list_layout = QVBoxLayout(self._pair_list_widget)
        self._pair_list_layout.setContentsMargins(0, 0, 0, 0)
        self._pair_list_layout.setSpacing(1)
        self._pair_list_layout.addStretch()
        self._pair_scroll.setWidget(self._pair_list_widget)
        list_vlayout.addWidget(self._pair_scroll)

        main_layout.addWidget(list_frame)

        # Thin vertical divider
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(divider)

        # Right editor panel
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

        self._show_placeholder(ui_text("ui_speaking_open_a_file_to_get_started"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    # Placeholder

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    # Pair list

    def _get_pairs(self) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str]] = []
        for e in self._entries:
            key = (e["char1"], e["char2"])
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result

    def _entries_for_pair(self, c1: str, c2: str) -> list[tuple[int, dict]]:
        return [(i, e) for i, e in enumerate(self._entries)
                if e["char1"] == c1 and e["char2"] == c2]

    def _populate_list(self, select: tuple[str, str] | None = None):
        _clear_layout(self._pair_list_layout)
        self._pair_buttons = []
        self._pair_list_layout.addStretch()

        pairs = self._get_pairs()
        for c1, c2 in pairs:
            btn = self._make_pair_button(c1, c2)
            self._pair_list_layout.insertWidget(
                self._pair_list_layout.count() - 1, btn
            )
            self._pair_buttons.append((btn, c1, c2))

        if not pairs:
            self._selected_pair = None
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
            self._show_placeholder(ui_text("ui_speaking_no_interactions_press_add_to_create_one"))
            return

        target = select if (select and select in pairs) else pairs[0]
        self._select_pair(*target)

    def _make_pair_button(self, c1: str, c2: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border-radius: 6px; "
            f"text-align: left; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
        )
        layout = QVBoxLayout(btn)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        n1 = _CHAR_NAMES.get(c1, c1)
        n2 = _CHAR_NAMES.get(c2, c2)

        pair_lbl = QLabel(ui_text("ui_speaking_value_vs_value", p0=n1, p1=n2))
        pair_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        pair_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        pair_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(pair_lbl)

        id_lbl = QLabel(ui_text("ui_sound_value_value_2", p0=c1, p1=c2))
        id_lbl.setFont(QFont("Consolas", 10))
        id_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(id_lbl)

        btn.clicked.connect(
            lambda checked=False, _c1=c1, _c2=c2: self._select_pair(_c1, _c2)
        )
        return btn

    def _filter_list(self):
        query = self._search.text().lower()
        for btn, c1, c2 in self._pair_buttons:
            n1 = _CHAR_NAMES.get(c1, "").lower()
            n2 = _CHAR_NAMES.get(c2, "").lower()
            match = (query in c1.lower() or query in c2.lower() or
                     query in n1 or query in n2)
            btn.setVisible(match)

    def _select_pair(self, c1: str, c2: str):
        self._selected_pair = (c1, c2)
        for btn, bc1, bc2 in self._pair_buttons:
            selected = (bc1 == c1 and bc2 == c2)
            bg = P['bg_card'] if selected else "transparent"
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; border-radius: 6px; "
                f"text-align: left; padding: 0px; border: none; }} "
                f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
            )
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(c1, c2)

    # Editor

    def _build_editor(self, c1: str, c2: str):
        _clear_layout(self._editor_layout)

        pair_entries = self._entries_for_pair(c1, c2)

        # Character header
        hdr = QFrame()
        hdr.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        hdr_inner = QWidget(hdr)
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(16, 12, 16, 12)
        hdr_grid.setHorizontalSpacing(16)

        hdr_main = QVBoxLayout(hdr)
        hdr_main.setContentsMargins(0, 0, 0, 0)
        hdr_main.addWidget(hdr_inner)

        for col, (field, code, label_text) in enumerate([
            ("char1", c1, ui_text("ui_speaking_character_1")),
            ("char2", c2, ui_text("ui_speaking_character_2")),
        ]):
            frame = QWidget()
            frame.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(2)

            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color: {P['text_dim']};")
            fl.addWidget(lbl)

            edit = QLineEdit(code)
            edit.setFixedHeight(36)
            edit.setFont(QFont("Consolas", 16))
            edit.setStyleSheet(
                f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
                f"color: {P['accent']}; padding: 2px 6px; border-radius: 4px; }}"
            )
            fl.addWidget(edit)

            edit.editingFinished.connect(
                lambda _field=field, _edit=edit, _c1=c1, _c2=c2:
                    self._on_char_changed(_c1, _c2, _field, _edit.text().strip())
            )

            hdr_grid.addWidget(frame, 0, col)
            hdr_grid.setColumnStretch(col, 1)

        self._editor_layout.addWidget(hdr)

        # Three dialogue cards
        for itype in _TYPE_ORDER:
            type_name = INTERACTION_NAMES[itype]

            section_lbl = QLabel(type_name)
            section_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
            section_lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
            section_lbl.setContentsMargins(20, 10, 0, 2)
            self._editor_layout.addWidget(section_lbl)

            typed = [(i, e) for i, e in pair_entries if e["interaction_type"] == itype]

            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}"
            )
            card_inner = QWidget(card)
            card_inner.setStyleSheet("background: transparent;")
            card_grid = QGridLayout(card_inner)
            card_grid.setContentsMargins(12, 12, 12, 12)
            card_grid.setHorizontalSpacing(16)
            card_grid.setVerticalSpacing(8)

            card_main = QVBoxLayout(card)
            card_main.setContentsMargins(0, 0, 0, 0)
            card_main.addWidget(card_inner)

            if not typed:
                empty_lbl = QLabel(ui_text("ui_speaking_no_entry_for_this_interaction_type"))
                empty_lbl.setFont(QFont("Segoe UI", 11))
                empty_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
                card_grid.addWidget(empty_lbl, 0, 0)

                add_btn = QPushButton(ui_text("ui_speaking_add_entry"))
                add_btn.setFixedHeight(28)
                add_btn.setFont(QFont("Segoe UI", 10))
                add_btn.setStyleSheet(ss_btn())
                add_btn.clicked.connect(
                    lambda checked=False, _c1=c1, _c2=c2, _itype=itype:
                        self._add_type_entry(_c1, _c2, _itype)
                )
                card_grid.addWidget(add_btn, 0, 1, Qt.AlignmentFlag.AlignRight)
            else:
                for row_idx, (entry_idx, entry) in enumerate(typed):
                    for col_idx, (dkey, dlabel) in enumerate([
                        ("dialogue1", ui_text("ui_speaking_dialogue_1")),
                        ("dialogue2", ui_text("ui_speaking_dialogue_2")),
                    ]):
                        f = QWidget()
                        f.setStyleSheet("background: transparent;")
                        fl = QVBoxLayout(f)
                        fl.setContentsMargins(0, 0, 0, 0)
                        fl.setSpacing(2)

                        lbl = QLabel(dlabel)
                        lbl.setFont(QFont("Segoe UI", 12))
                        lbl.setStyleSheet(f"color: {P['text_sec']};")
                        fl.addWidget(lbl)

                        edit = QLineEdit(entry[dkey])
                        edit.setFixedHeight(30)
                        edit.setFont(QFont("Consolas", 13))
                        edit.setStyleSheet(
                            f"QLineEdit {{ background-color: {P['bg_card']}; "
                            f"border: 1px solid {P['border']}; "
                            f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
                        )
                        edit.textChanged.connect(
                            lambda text, _idx=entry_idx, _key=dkey:
                                self._update_entry_field(_idx, _key, text)
                        )
                        fl.addWidget(edit)

                        card_grid.addWidget(f, row_idx, col_idx)
                        card_grid.setColumnStretch(col_idx, 1)

            self._editor_layout.addWidget(card)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

    # Field update helpers

    def _update_entry_field(self, idx: int, key: str, value: str):
        if 0 <= idx < len(self._entries):
            self._entries[idx][key] = value
            self._dirty = True
            self._btn_save.setEnabled(True)

    def _add_type_entry(self, c1: str, c2: str, itype: int):
        """Add a new entry for the given interaction type to the current pair."""
        new_e = {
            "interaction_type": itype,
            "is_round_win": 0,
            "char1": c1, "char2": c2,
            "dialogue1": "", "dialogue2": "",
        }
        self._entries.append(new_e)
        self._orig_entries.append(dict(new_e))
        self._dirty = True
        self._btn_save.setEnabled(True)
        self._build_editor(c1, c2)

    def _on_char_changed(self, old_c1: str, old_c2: str, field: str, new_val: str):
        if not new_val:
            return
        changed = False
        for e in self._entries:
            if e["char1"] == old_c1 and e["char2"] == old_c2:
                e[field] = new_val
                changed = True
        if not changed:
            return
        self._dirty = True
        self._btn_save.setEnabled(True)
        new_c1 = new_val if field == "char1" else old_c1
        new_c2 = new_val if field == "char2" else old_c2
        self._selected_pair = (new_c1, new_c2)
        self._populate_list(select=(new_c1, new_c2))

    # CRUD

    def _on_add(self):
        new_c1, new_c2 = "new_chr", "new_chr"
        for itype in _TYPE_ORDER:
            e = {
                "interaction_type": itype,
                "is_round_win": 0,
                "char1": new_c1, "char2": new_c2,
                "dialogue1": "", "dialogue2": "",
            }
            self._entries.append(e)
            self._orig_entries.append(dict(e))
        self._dirty = True
        self._btn_save.setEnabled(True)
        self._populate_list(select=(new_c1, new_c2))

    def _on_dup(self):
        if not self._selected_pair:
            return
        c1, c2 = self._selected_pair
        pair_entries = self._entries_for_pair(c1, c2)
        if not pair_entries:
            return
        new_c1, new_c2 = "new_chr", "new_chr"
        for _, e in pair_entries:
            new_e = dict(e)
            new_e["char1"] = new_c1
            new_e["char2"] = new_c2
            self._entries.append(new_e)
            self._orig_entries.append(dict(new_e))
        self._dirty = True
        self._btn_save.setEnabled(True)
        self._populate_list(select=(new_c1, new_c2))

    def _on_delete(self):
        if not self._selected_pair:
            return
        c1, c2 = self._selected_pair
        n1 = _CHAR_NAMES.get(c1, c1)
        n2 = _CHAR_NAMES.get(c2, c2)
        reply = QMessageBox.question(
            self, ui_text("ui_speaking_delete_interaction"),
            ui_text("ui_speaking_delete_all_entries_for_value_vs_value_value_valu", p0=n1, p1=n2, p2=c1, p3=c2),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        to_remove = sorted(
            [i for i, e in enumerate(self._entries)
             if e["char1"] == c1 and e["char2"] == c2],
            reverse=True,
        )
        for i in to_remove:
            del self._entries[i]
            if i < len(self._orig_entries):
                del self._orig_entries[i]
        self._dirty = True
        self._btn_save.setEnabled(True)
        self._selected_pair = None
        self._populate_list()

    # File I/O

    def _load_file(self, filepath: str):
        try:
            data, version, entries = parse_speaking_xfbin(filepath)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_assist_failed_to_open_file_value", p0=exc))
            return

        self._filepath      = filepath
        self._original_data = data
        self._version       = version
        self._entries       = entries
        self._orig_entries  = [dict(e) for e in entries]
        self._dirty         = False

        self._file_lbl.setText(os.path.basename(filepath))
        self._file_lbl.setStyleSheet(f"color: {P['text_file']};")
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)

        self._populate_list()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_speaking_open_speakinglineparam_bin_xfbin"), "",
            "XFBIN Files (*.xfbin);;All Files (*)",
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath:
            return
        try:
            save_speaking_xfbin(
                self._filepath, self._original_data,
                self._version, self._entries,
            )
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("ui_customcardparam_failed_to_save_file_value", p0=exc))
            return

        self._dirty = False
        try:
            self._original_data, self._version, saved = parse_speaking_xfbin(self._filepath)
            self._orig_entries = [dict(e) for e in saved]
        except Exception:
            self._orig_entries = [dict(e) for e in self._entries]

        self._file_lbl.setText(os.path.basename(self._filepath))
        self._file_lbl.setStyleSheet(f"color: {P['text_file']};")
        QMessageBox.information(self, ui_text("ui_assist_saved"), ui_text("ui_assist_file_saved_value", p0=self._filepath))
