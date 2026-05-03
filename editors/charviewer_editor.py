"""editors/charviewer_editor.py  –  Full editor for CharViewerParam.bin.xfbin."""

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
    ss_btn, ss_toolbar, ss_sep, ss_input, ss_panel,
    ss_scrollarea, ss_section_label, ss_field_label,
    ss_placeholder, ss_file_label,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label
from parsers.charviewer_parser import (
    parse_charviewer_xfbin,
    save_charviewer_xfbin,
    make_default_entry,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir

_PART_NAMES = {
    0: ui_text("ui_charviewer_all_none"),
    1: ui_text("ui_charviewer_part_1"), 2: ui_text("ui_charviewer_part_2"), 3: ui_text("ui_charviewer_part_3"), 4: ui_text("ui_charviewer_part_4"),
    5: ui_text("ui_charviewer_part_5"), 6: ui_text("ui_charviewer_part_6"), 7: ui_text("ui_charviewer_part_7"), 8: ui_text("ui_charviewer_part_8"),
}

_DLC_NAMES = {
    0:     ui_text("ui_charviewer_base_game"),
    10000: ui_text("ui_charviewer_dlc_0"),  10001: ui_text("ui_charviewer_dlc_1"),  10002: ui_text("ui_charviewer_dlc_2"),  10003: ui_text("ui_charviewer_dlc_3"),
    10004: ui_text("ui_charviewer_dlc_4"),  10005: ui_text("ui_charviewer_dlc_5"),  10006: ui_text("ui_charviewer_dlc_6"),  10007: ui_text("ui_charviewer_dlc_7"),
    10008: ui_text("ui_charviewer_dlc_8"),  10009: ui_text("ui_charviewer_dlc_9"),  10010: ui_text("ui_charviewer_dlc_10"), 10011: ui_text("ui_charviewer_dlc_11"),
}

_UNLOCK_NAMES = {
    0: ui_text("ui_charviewer_0_default_free"),
    1: ui_text("ui_charviewer_1_unlockable"),
    2: ui_text("ui_charviewer_2_shop_purchase"),
    3: ui_text("ui_charviewer_3_dlc_unlock"),
    4: ui_text("ui_charviewer_4_special"),
    5: ui_text("ui_charviewer_5_special_condition"),
    6: ui_text("ui_charviewer_6_shop_alt"),
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


class CharViewerEditor(QWidget):
    """Embedded editor for CharViewerParam.bin.xfbin."""

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

        # Editor scroll area
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

        self._show_placeholder(ui_text("ui_charviewer_open_a_charviewerparam_bin_xfbin_file_to_begin_editing"))
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
        self._lbl_file.setStyleSheet(f"color: {P['text_dim']}; background: transparent; text-decoration: none;")
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

        # Search box
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

        # Action buttons
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

        # Scrollable entry list
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
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
            if txt and txt not in e["viewer_id"].lower() \
                    and txt not in e["chara_code"].lower() \
                    and txt not in e["char_viewer_id"].lower():
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

        vid_lbl = QLabel(e["viewer_id"] or e["char_viewer_id"])
        vid_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        vid_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        vid_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(vid_lbl)

        char_code = e["chara_code"]
        resolved_key = f"char_{char_code}"
        resolved = self._t(resolved_key)
        sub_text = f"{char_code} • {resolved}" if resolved != resolved_key else char_code

        code_lbl = QLabel(sub_text)
        code_lbl.setFont(QFont("Consolas", 11))
        code_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        code_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(code_lbl)

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

    def _add_combo(self, grid: QGridLayout, row: int, col: int,
                   label: str, options: dict, current_val, key: str) -> QComboBox:
        cb = QComboBox()
        cb.setFixedHeight(30)
        cb.setStyleSheet(ss_input())
        for v, n in options.items():
            cb.addItem(n, v)
        for i in range(cb.count()):
            if cb.itemData(i) == current_val:
                cb.setCurrentIndex(i)
                break

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        cl.addWidget(lbl)
        cl.addWidget(cb)

        grid.addWidget(container, row, col)
        grid.setColumnStretch(col, 1)
        self._detail_widgets[key] = cb
        cb.currentIndexChanged.connect(lambda: None if self._loading_detail else self._save_current_entry())
        return cb

    def _build_editor(self, e: dict):
        self._clear_editor()
        self._detail_widgets = {}
        self._loading_detail = True

        # Identity
        self._add_section(ui_text("skill_section_identity"))
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_charviewer_char_viewer_id"),      e["char_viewer_id"],    "char_viewer_id")
        self._add_le(g, 0, 1, ui_text("ui_charviewer_viewer_id"),           e["viewer_id"],         "viewer_id")
        self._add_le(g, 0, 2, ui_text("ui_charviewer_custom_list_title"),   e["custom_list_title"], "custom_list_title")
        self._add_le(g, 1, 0, ui_text("ui_charviewer_character_code"),      e["chara_code"],        "chara_code")
        self._add_le(g, 1, 1, ui_text("ui_charviewer_model_code"),          e["model_code"],        "model_code")
        self._editor_layout.addWidget(card)

        # Animations
        self._add_section(ui_text("skill_filter_anm"))
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_charviewer_face_animation"),   e["face_anim"],  "face_anim")
        self._add_le(g, 0, 1, ui_text("ui_charviewer_idle_animation_1"), e["idle_anim1"], "idle_anim1")
        self._add_le(g, 0, 2, ui_text("ui_charviewer_idle_animation_2"), e["idle_anim2"], "idle_anim2")
        for pi in range(1, 6):
            r = pi  # rows 1..5
            self._add_le(g, r, 0, f"Pose {pi} Start", e[f"pose{pi}_st"], f"pose{pi}_st")
            self._add_le(g, r, 1, f"Pose {pi} Loop",  e[f"pose{pi}_lp"], f"pose{pi}_lp")
            self._add_le(g, r, 2, f"Pose {pi} End",   e[f"pose{pi}_ed"], f"pose{pi}_ed")
        self._add_le(g, 6, 0, ui_text("ui_charviewer_object_1"),       e["object1"], "object1")
        self._add_le(g, 6, 1, ui_text("ui_charviewer_object_2"),       e["object2"], "object2")
        self._add_le(g, 6, 2, ui_text("ui_charviewer_object_3"),       e["object3"], "object3")
        self._add_le(g, 7, 0, ui_text("ui_charviewer_anim_21"),        e["anim21"],            "anim21")
        self._add_le(g, 7, 1, ui_text("ui_charviewer_char_id_ref"),    e["anim22_char_id"],    "anim22_char_id")
        self._add_le(g, 7, 2, ui_text("ui_charviewer_char_tints_ref"), e["anim23_char_tints"], "anim23_char_tints")
        self._add_le(g, 8, 0, ui_text("ui_charviewer_char_ids_ref"),   e["anim24_char_ids"],   "anim24_char_ids")
        self._add_le(g, 8, 1, ui_text("ui_charviewer_model_ids_ref"),  e["anim25_model_ids"],  "anim25_model_ids")
        self._add_le(g, 8, 2, ui_text("ui_charviewer_anim_26"),        e["anim26"],            "anim26")
        self._add_le(g, 9, 0, ui_text("ui_charviewer_anim_27"),        e["anim27"],            "anim27")
        self._editor_layout.addWidget(card)

        # Camera
        self._add_section(ui_text("ui_charviewer_camera"))
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_charviewer_starting_zoom"),        f"{e['cam_zoom']:.6g}",      "cam_zoom")
        self._add_le(g, 0, 1, ui_text("ui_charviewer_starting_y"),           f"{e['cam_y']:.6g}",         "cam_y")
        self._add_le(g, 0, 2, ui_text("ui_charviewer_starting_x_unused"),  f"{e['cam_unk']:.6g}",       "cam_unk")
        self._add_le(g, 1, 0, ui_text("ui_charviewer_anchor_y"),             f"{e['cam_anchor_y']:.6g}",  "cam_anchor_y")
        self._add_le(g, 1, 1, ui_text("ui_charviewer_anchor_x"),             f"{e['cam_anchor_x']:.6g}",  "cam_anchor_x")
        self._add_le(g, 1, 2, ui_text("ui_charviewer_rotate_y_lower_limit"), f"{e['cam_rot_y_min']:.6g}", "cam_rot_y_min")
        self._add_le(g, 2, 0, ui_text("ui_charviewer_starting_z_rotation"),  f"{e['cam_rot_z']:.6g}",     "cam_rot_z")
        self._add_le(g, 2, 1, ui_text("ui_charviewer_zoom_in_limit"),        f"{e['cam_zoom_in']:.6g}",   "cam_zoom_in")
        self._add_le(g, 2, 2, ui_text("ui_charviewer_zoom_out_limit"),       f"{e['cam_zoom_out']:.6g}",  "cam_zoom_out")
        self._editor_layout.addWidget(card)

        # DLC / Shop
        self._add_section(ui_text("ui_charviewer_dlc_shop"))
        card, g = self._add_card()
        self._add_le(g, 0, 0, ui_text("ui_charviewer_custom_card_id"),         e["custom_card"],    "custom_card")
        self._add_le(g, 0, 1, ui_text("ui_charviewer_custom_icon_path"),       e["icon_path"],      "icon_path")
        self._add_le(g, 0, 2, ui_text("ui_charviewer_medal_preview_image"),    e["medal_img"],      "medal_img")
        self._add_le(g, 1, 0, ui_text("ui_charviewer_extra_costume_title_id"), e["extra_costume"],  "extra_costume")
        self._add_le(g, 1, 1, ui_text("ui_charviewer_card_detail_id"),         e["card_detail"],    "card_detail")
        self._add_le(g, 2, 0, ui_text("ui_charviewer_dlc_id"),                 str(e["dlc_id"]),    "dlc_id")
        self._add_le(g, 2, 1, ui_text("ui_charviewer_patch"),                str(e["patch_id"]),  "patch_id")
        self._add_le(g, 2, 2, ui_text("ui_charviewer_shop_price"),             str(e["shop_price"]), "shop_price")
        self._add_combo(g, 3, 0, ui_text("ui_charviewer_unlock_condition"), _UNLOCK_NAMES,
                        e["unlock_condition"], "unlock_condition")
        self._editor_layout.addWidget(card)

        # Advanced
        self._add_section(ui_text("ui_charviewer_advanced"))
        card, g = self._add_card()
        part_opts = {v: f"{v} – {n}" for v, n in _PART_NAMES.items()}
        self._add_combo(g, 0, 0, ui_text("ui_charviewer_part_3d_shop"), part_opts, e["part"], "part")
        self._add_le(g, 0, 1, ui_text("ui_charviewer_menu1_index_char"),   str(e["menu1_index"]), "menu1_index")
        self._add_le(g, 0, 2, ui_text("ui_charviewer_menu2_index_3d_list"),  str(e["menu2_index"]), "menu2_index")
        self._add_le(g, 1, 0, ui_text("ui_charviewer_unk_int32"),   str(e["unk"]),  "unk")
        self._add_le(g, 1, 1, ui_text("ui_charviewer_unk2_uint64"), str(e["unk2"]), "unk2")
        self._add_le(g, 1, 2, ui_text("ui_charviewer_unk3_uint64"), str(e["unk3"]), "unk3")
        self._add_le(g, 2, 0, ui_text("ui_charviewer_unk4_uint32"), str(e["unk4"]), "unk4")
        self._editor_layout.addWidget(card)

        # Bottom padding
        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()

        self._loading_detail = False

    # Dynamic save

    def _save_current_entry(self):
        if self._current_idx < 0 or self._loading_detail:
            return
        e = self._entries[self._current_idx]

        def _txt(key, fallback="") -> str:
            w = self._detail_widgets.get(key)
            if isinstance(w, QLineEdit):
                return w.text()
            if isinstance(w, QComboBox):
                return w.currentData()
            return fallback

        def _flt(key, fallback=0.0) -> float:
            try:
                return float(_txt(key, str(fallback)))
            except (ValueError, TypeError):
                return fallback

        def _int(key, fallback=0) -> int:
            try:
                val = _txt(key, str(fallback))
                return int(val)
            except (ValueError, TypeError):
                return fallback

        # Identity
        e["char_viewer_id"]    = _txt("char_viewer_id")
        e["viewer_id"]         = _txt("viewer_id")
        e["custom_list_title"] = _txt("custom_list_title")
        e["chara_code"]        = _txt("chara_code")
        e["model_code"]        = _txt("model_code")

        # Animations
        e["face_anim"]  = _txt("face_anim")
        e["idle_anim1"] = _txt("idle_anim1")
        e["idle_anim2"] = _txt("idle_anim2")
        for pi in range(1, 6):
            e[f"pose{pi}_st"] = _txt(f"pose{pi}_st")
            e[f"pose{pi}_lp"] = _txt(f"pose{pi}_lp")
            e[f"pose{pi}_ed"] = _txt(f"pose{pi}_ed")
        e["object1"]           = _txt("object1")
        e["object2"]           = _txt("object2")
        e["object3"]           = _txt("object3")
        e["anim21"]            = _txt("anim21")
        e["anim22_char_id"]    = _txt("anim22_char_id")
        e["anim23_char_tints"] = _txt("anim23_char_tints")
        e["anim24_char_ids"]   = _txt("anim24_char_ids")
        e["anim25_model_ids"]  = _txt("anim25_model_ids")
        e["anim26"]            = _txt("anim26")
        e["anim27"]            = _txt("anim27")

        # Camera
        e["cam_zoom"]      = _flt("cam_zoom")
        e["cam_y"]         = _flt("cam_y")
        e["cam_unk"]       = _flt("cam_unk")
        e["cam_anchor_y"]  = _flt("cam_anchor_y")
        e["cam_anchor_x"]  = _flt("cam_anchor_x")
        e["cam_rot_y_min"] = _flt("cam_rot_y_min")
        e["cam_rot_z"]     = _flt("cam_rot_z")
        e["cam_zoom_in"]   = _flt("cam_zoom_in")
        e["cam_zoom_out"]  = _flt("cam_zoom_out")

        # DLC / Shop
        e["custom_card"]      = _txt("custom_card")
        e["icon_path"]        = _txt("icon_path")
        e["medal_img"]        = _txt("medal_img")
        e["extra_costume"]    = _txt("extra_costume")
        e["card_detail"]      = _txt("card_detail")
        e["dlc_id"]           = _int("dlc_id")
        e["patch_id"]         = _int("patch_id")
        e["shop_price"]       = _int("shop_price")
        e["unlock_condition"] = _txt("unlock_condition")

        # Advanced
        e["part"]        = _txt("part")
        e["menu1_index"] = _int("menu1_index")
        e["menu2_index"] = _int("menu2_index")
        e["unk"]         = _int("unk")
        e["unk2"]        = _int("unk2")
        e["unk3"]        = _int("unk3")
        e["unk4"]        = _int("unk4")

        self._mark_dirty()

        # Refresh the button labels if viewer_id or chara_code changed
        for btn, bi in self._entry_buttons:
            if bi == self._current_idx:
                labels = btn.findChildren(QLabel)
                if len(labels) >= 2:
                    labels[0].setText(e["viewer_id"] or e["char_viewer_id"])
                    char_code = e["chara_code"]
                    resolved_key = f"char_{char_code}"
                    resolved = self._t(resolved_key)
                    sub_text = (f"{char_code} • {resolved}"
                                if resolved != resolved_key else char_code)
                    labels[1].setText(sub_text)
                break

    # File operations

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_charviewer_open_charviewerparam_bin_xfbin"),
            game_files_dialog_dir(self._filepath or "", "CharViewerParam.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if not path:
            return
        create_backup_on_open(path)
        try:
            raw, version, entries = parse_charviewer_xfbin(path)
        except Exception as ex:
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(ex))
            return
        self._filepath = path
        self._raw      = raw
        self._version  = version
        self._entries  = entries
        self._dirty    = False
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
        if not self._filepath:
            path, _ = QFileDialog.getSaveFileName(
                self, ui_text("ui_charviewer_save_charviewerparam_bin_xfbin"),
                ui_text("ui_charviewer_charviewerparam_bin_xfbin"),
                "XFBIN Files (*.xfbin);;All Files (*)"
            )
            if not path:
                return
            self._filepath = path
            set_file_label(self._lbl_file, path)
        self._do_save(self._filepath)

    def _do_save(self, path: str):
        try:
            save_charviewer_xfbin(path, self._raw, self._version, self._entries)
            self._raw   = bytearray(open(path, "rb").read())
            self._dirty = False
            set_file_label(self._lbl_file, path)
            QMessageBox.information(self, ui_text("ui_assist_saved"),
                                    ui_text("ui_charviewer_saved_value_entries_to_value", p0=len(self._entries), p1=path))
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
        new_e["char_viewer_id"] = new_e["char_viewer_id"] + "_copy"
        new_e["viewer_id"]      = new_e["viewer_id"] + "_copy"
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
            ui_text("ui_charviewer_delete_entry_value", p0=e['char_viewer_id']),
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
