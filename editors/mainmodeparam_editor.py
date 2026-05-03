import os
import threading
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QScrollArea, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_input, ss_sep, ss_search, ss_scrollarea, ss_scrollarea_transparent,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from parsers.mainmodeparam_parser import (
    parse_mainmodeparam, save_mainmodeparam,
    make_default_panel, PANEL_TYPE_NAMES,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Layout helpers

def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _lbl(text, dim=False, bold=False, size=12):
    w = QLabel(text)
    w.setFont(QFont("Segoe UI", size,
                    QFont.Weight.Bold if bold else QFont.Weight.Normal))
    w.setStyleSheet(
        f"color: {P['text_dim'] if dim else P['text_main']}; background: transparent;"
    )
    return w


def _le(value='', width=None):
    w = QLineEdit(str(value))
    w.setFont(QFont("Consolas", 12))
    w.setFixedHeight(28)
    w.setStyleSheet(ss_input())
    if width:
        w.setFixedWidth(width)
    return w


def _combo(items, idx=0):
    w = QComboBox()
    w.setFont(QFont("Segoe UI", 12))
    w.addItems(items)
    w.setCurrentIndex(idx)
    w.setStyleSheet(ss_input())
    return w


def _section(title, color=None):
    color = color or P['secondary']
    lbl = QLabel(title)
    lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    lbl.setContentsMargins(20, 10, 0, 2)
    return lbl


def _row(label, widget, grid, row, note=None):
    grid.addWidget(_lbl(label, dim=True), row, 0)
    grid.addWidget(widget, row, 1)
    if note:
        n = _lbl(f"  {note}", dim=True, size=10)
        n.setWordWrap(True)
        grid.addWidget(n, row, 2)


def _grid():
    g = QGridLayout()
    g.setContentsMargins(16, 8, 16, 8)
    g.setHorizontalSpacing(12)
    g.setVerticalSpacing(6)
    g.setColumnStretch(1, 1)
    g.setColumnStretch(2, 1)
    return g


# Panel list item

class PanelItem(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, idx, panel, parent=None):
        super().__init__(parent)
        self._idx = idx
        self._update_style(selected=False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(1)

        typ       = panel.get('type', 0)
        tc        = self._type_color(typ)
        panel_id  = panel.get('ptr_panel_id', '') or f'Panel {idx + 1}'
        player_id = panel.get('ptr_player_id', '') or '???'
        enemy_id  = panel.get('ptr_enemy_id',  '') or '???'
        total_idx = panel.get('total_idx', 0)
        type_name = PANEL_TYPE_NAMES.get(typ, str(typ))

        t = QLabel(ui_text("ui_mainmodeparam_value_value", p0=total_idx, p1=panel_id))
        t.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {P['text_main']}; background: transparent;")

        s = QLabel(ui_text("ui_mainmodeparam_value_vs_value_value", p0=player_id, p1=enemy_id, p2=type_name))
        s.setFont(QFont("Segoe UI", 10))
        s.setStyleSheet(f"color: {tc}; background: transparent;")

        lay.addWidget(t)
        lay.addWidget(s)

    @staticmethod
    def _type_color(typ):
        # 0=Normal → dim, 1=Extra → secondary, 2=Boss → accent
        return {0: P['text_dim'], 1: P['secondary'], 2: P['accent']}.get(typ, P['text_dim'])

    def _update_style(self, selected: bool):
        if selected:
            self.setStyleSheet(
                f"QFrame {{ background: {P['bg_card']}; border-radius: 6px; border: none; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: transparent; border-radius: 6px; border: none; }}"
                f"QFrame:hover {{ background: {P['bg_card_hov']}; }}"
            )

    def set_selected(self, v):
        self._update_style(selected=v)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)
        super().mousePressEvent(e)


# Editor

class MainModeParamEditor(QWidget):
    _sig_done  = pyqtSignal(str, object, object)
    _sig_error = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t         = lang_func
        self._raw      = None
        self._result   = None
        self._filepath = None
        self._panels   = []
        self._current  = -1
        self._items    = []
        self._fields   = {}

        self._sig_done.connect(self._on_load_done)
        self._sig_error.connect(self._on_load_error)
        self._build_ui()

    # UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # top bar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)

        self._open_btn = QPushButton(self.t("btn_open_file"))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._load_file)
        tl.addWidget(self._open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)

        self._file_lbl = QLabel(self.t("no_file_loaded"))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(f"color: {P['text_dim']};")
        tl.addWidget(self._file_lbl)

        tl.addStretch(1)

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        # main area
        main = QWidget()
        ml = QHBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(272)
        sidebar.setStyleSheet(f"QFrame {{ background: {P['bg_panel']}; }}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(6, 8, 6, 6)
        sl.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self.t("search_placeholder"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_list)
        sl.addWidget(self._search)

        # action buttons row
        act = QWidget()
        act.setStyleSheet("background: transparent;")
        al = QHBoxLayout(act)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFont(QFont("Segoe UI", 10))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_panel)

        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFont(QFont("Segoe UI", 10))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_panel)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFont(QFont("Segoe UI", 10))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_panel)

        al.addWidget(self._add_btn, 1)
        al.addWidget(self._dup_btn, 1)
        al.addWidget(self._del_btn, 1)
        sl.addWidget(act)

        # panel list
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._list_inner = QWidget()
        self._list_inner.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_inner)
        sl.addWidget(self._list_scroll, 1)

        ml.addWidget(sidebar)

        div = QFrame()
        div.setFixedWidth(1)
        div.setStyleSheet(ss_sep())
        ml.addWidget(div)

        # editor area
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 16)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        ml.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)
        self._show_placeholder()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        lbl = QLabel(ui_text("ui_mainmodeparam_open_a_mainmodeparam_bin_xfbin_file_to_begin_editing"))
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_mainmodeparam"), game_files_dialog_dir(target_patterns="MainModeParam.bin.xfbin"),
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return
        create_backup_on_open(path)
        self._file_lbl.setText(self.t("loading"))

        def _worker():
            try:
                raw, result = parse_mainmodeparam(path)
                self._sig_done.emit(path, raw, result)
            except Exception as e:
                self._sig_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path, raw, result):
        self._raw      = raw
        self._result   = result
        self._panels   = result['panels']
        self._filepath = path
        self._file_lbl.setText(os.path.basename(path))
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._current = -1
        self._rebuild_list()
        self._show_placeholder()
        if self._panels:
            QTimer.singleShot(50, lambda: self._select_panel(0))

    def _on_load_error(self, msg):
        self._file_lbl.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"),
                             self.t("msg_load_error", error=msg))

    def _save_file(self):
        if not self._raw or not self._result:
            return
        if self._current >= 0:
            self._flush_panel()
        try:
            save_mainmodeparam(self._filepath, self._raw, self._result)
            QMessageBox.information(
                self, self.t("dlg_title_success"),
                self.t("msg_save_success", path=self._filepath) +
                f"\n\n{len(self._panels)} panels written."
            )
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                 self.t("msg_save_error", error=e))

    # Panel list

    def _rebuild_list(self, keep_scroll=False):
        scroll_val = self._list_scroll.verticalScrollBar().value() if keep_scroll else 0
        _clear_layout(self._list_layout)
        self._items = []

        current_part = None
        for i, panel in enumerate(self._panels):
            part = panel.get('part', 0)
            if part != current_part:
                current_part = part
                grp = _lbl(f"  PART {part}", bold=True, size=11)
                grp.setFixedHeight(24)
                grp.setStyleSheet(
                    f"color: {P['accent']}; background: {P['bg_panel']}; "
                    f"border-top: 1px solid {P['border']};"
                )
                self._list_layout.addWidget(grp)

            item = PanelItem(i, panel)
            item.clicked.connect(self._select_panel)
            self._list_layout.addWidget(item)
            self._items.append((item, panel))

        self._list_layout.addStretch()

        if 0 <= self._current < len(self._items):
            self._items[self._current][0].set_selected(True)

        if keep_scroll:
            QTimer.singleShot(0, lambda: self._list_scroll.verticalScrollBar().setValue(scroll_val))

    def _filter_list(self, text):
        q = text.strip().lower()
        for item, panel in self._items:
            if not q:
                item.show()
            else:
                hay = ' '.join([
                    str(panel.get('ptr_panel_id', '')),
                    str(panel.get('ptr_player_id', '')),
                    str(panel.get('ptr_enemy_id',  '')),
                    str(panel.get('ptr_stage_id',  '')),
                    str(panel.get('total_idx', '')),
                ]).lower()
                item.setVisible(q in hay)

    # Panel CRUD

    def _select_panel(self, index):
        if self._current >= 0:
            self._flush_panel()
            if self._current < len(self._items):
                self._items[self._current][0].set_selected(False)

        self._current = index
        if 0 <= index < len(self._items):
            self._items[index][0].set_selected(True)
            self._dup_btn.setEnabled(True)
            self._del_btn.setEnabled(True)

        self._build_form(self._panels[index])

    def _add_panel(self):
        if self._current >= 0:
            self._flush_panel()

        ref_panel = self._panels[self._current] if 0 <= self._current < len(self._panels) else None
        new = make_default_panel()
        if ref_panel:
            new['part'] = ref_panel.get('part', 1)
            new['page'] = ref_panel.get('page', 1)

        max_idx = max((p.get('total_idx', 0) for p in self._panels), default=0)
        new['total_idx'] = max_idx + 1

        insert_at = (self._current + 1) if self._current >= 0 else len(self._panels)
        self._panels.insert(insert_at, new)
        self._result['count'] = len(self._panels)

        self._current = -1
        self._rebuild_list()
        self._select_panel(insert_at)

        if insert_at < len(self._items):
            QTimer.singleShot(30, lambda: self._list_scroll.ensureWidgetVisible(
                self._items[insert_at][0]))

    def _duplicate_panel(self):
        if self._current < 0:
            return
        self._flush_panel()

        src = self._panels[self._current]
        new = make_default_panel(reference=src)
        new['ptr_panel_id'] = ''

        max_idx = max((p.get('total_idx', 0) for p in self._panels), default=0)
        new['total_idx'] = max_idx + 1

        insert_at = self._current + 1
        self._panels.insert(insert_at, new)
        self._result['count'] = len(self._panels)

        self._current = -1
        self._rebuild_list()
        self._select_panel(insert_at)

        if insert_at < len(self._items):
            QTimer.singleShot(30, lambda: self._list_scroll.ensureWidgetVisible(
                self._items[insert_at][0]))

    def _delete_panel(self):
        if self._current < 0:
            return
        panel_id = self._panels[self._current].get('ptr_panel_id', '') or f'#{self._current}'
        ans = QMessageBox.question(
            self, self.t("dlg_title_confirm_delete"),
            self.t("msg_confirm_delete_item", name=panel_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        del self._panels[self._current]
        self._result['count'] = len(self._panels)

        new_sel = min(self._current, len(self._panels) - 1)
        self._current = -1
        self._fields  = {}
        self._rebuild_list()

        if self._panels:
            self._select_panel(new_sel)
        else:
            self._dup_btn.setEnabled(False)
            self._del_btn.setEnabled(False)
            self._show_placeholder()

    # Form flush

    def _flush_panel(self):
        if self._current < 0 or not self._fields:
            return
        panel = self._panels[self._current]
        for key, widget in self._fields.items():
            try:
                if isinstance(widget, QComboBox):
                    panel[key] = widget.currentIndex()
                elif isinstance(widget, QLineEdit):
                    raw_val = widget.text()
                    orig    = panel.get(key)
                    if isinstance(orig, int):
                        panel[key] = int(raw_val) if raw_val.strip() else 0
                    else:
                        panel[key] = raw_val
            except (ValueError, TypeError):
                pass

    # Form builder

    def _build_form(self, panel):
        _clear_layout(self._editor_layout)
        self._fields = {}

        typ = panel.get('type', 0)

        # Basic Information
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_basic_information"), P['accent']))
        g = _grid()
        r = 0

        for key, label, note, is_str in [
            ('part',         ui_text("ui_mainmodeparam_part_jojo_arc"),    ui_text("ui_mainmodeparam_1_phantom_blood_2_battle_tendency"), False),
            ('ptr_panel_id', ui_text("ui_mainmodeparam_panel_id"),            ui_text("ui_mainmodeparam_unique_identifier_e_g_panel_15_01"),  True),
            ('page',         ui_text("ui_mainmodeparam_page"),                ui_text("ui_mainmodeparam_chapter_page_within_the_arc"),          False),
            ('ptr_boss_id',  ui_text("ui_mainmodeparam_boss_panel_id"),       ui_text("ui_mainmodeparam_boss_variant_panel_reference"),         True),
            ('unk1',         ui_text("ui_mainmodeparam_hidden_field_1"),      ui_text("ui_mainmodeparam_unknown_uint64_usually_0"),           False),
            ('unk2',         ui_text("ui_mainmodeparam_hidden_field_2"),      ui_text("ui_mainmodeparam_unknown_uint64_usually_0"),           False),
        ]:
            w = _le(panel.get(key, '' if is_str else 0))
            self._fields[key] = w
            _row(label, w, g, r, note); r += 1

        w = _le(panel.get('gold_reward', 0))
        self._fields['gold_reward'] = w
        _row(ui_text("ui_mainmodeparam_gold_reward"), w, g, r, ui_text("ui_mainmodeparam_gold_earned_for_winning_this_battle")); r += 1

        cb = _combo([ui_text("ui_mainmodeparam_normal"), ui_text("skill_param_extra"), ui_text("ui_mainmodeparam_boss")], idx=min(typ, 2))
        self._fields['type'] = cb
        _row(ui_text("ui_mainmodeparam_panel_type"), cb, g, r, ui_text("ui_mainmodeparam_normal_0_extra_1_boss_2")); r += 1

        for direction, key in [(ui_text("ui_mainmodeparam_above"),  'ptr_up'),   (ui_text("ui_mainmodeparam_below"), 'ptr_down'),
                                (ui_text("ui_mainmodeparam_left"),   'ptr_left'), (ui_text("ui_mainmodeparam_right"), 'ptr_right')]:
            w = _le(panel.get(key, ''))
            self._fields[key] = w
            _row(f"{direction} Panel ID", w, g, r, ui_text("ui_mainmodeparam_navigation_link_empty_none")); r += 1

        w = _le(panel.get('disp_diff', 0))
        self._fields['disp_diff'] = w
        _row(ui_text("ui_mainmodeparam_display_difficulty"), w, g, r, ui_text("ui_mainmodeparam_stars_shown_in_ui_actual_value_1")); r += 1

        w = _le(panel.get('cpu_level', 0))
        self._fields['cpu_level'] = w
        _row(ui_text("ui_mainmodeparam_cpu_level"), w, g, r, ui_text("ui_mainmodeparam_ai_difficulty_setting")); r += 1

        w = _le(panel.get('ptr_stage_id', ''))
        self._fields['ptr_stage_id'] = w
        _row(ui_text("ui_mainmodeparam_stage_id"), w, g, r, ui_text("ui_mainmodeparam_battle_stage_identifier")); r += 1

        w = _le(panel.get('unk3', 0))
        self._fields['unk3'] = w
        _row(ui_text("ui_mainmodeparam_hidden_field_3"), w, g, r, ui_text("ui_mainmodeparam_unknown_uint64")); r += 1

        fsp = int(panel.get('first_speak', 0))
        cb  = _combo([ui_text("ui_mainmodeparam_player_0"), ui_text("ui_mainmodeparam_enemy_1")], idx=min(fsp, 1))
        self._fields['first_speak'] = cb
        _row(ui_text("ui_mainmodeparam_first_to_speak"), cb, g, r, ui_text("ui_mainmodeparam_who_opens_the_battle_dialogue")); r += 1

        self._editor_layout.addWidget(self._wrap(g))

        # Player Information
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_player_information"), P['secondary']))
        g = _grid(); r = 0
        for label, key, note in [
            (ui_text("ui_mainmodeparam_player_id"),             'ptr_player_id',  ui_text("ui_mainmodeparam_character_id_e_g_1dio01")),
            (ui_text("ui_mainmodeparam_player_assist_id"),      'ptr_plyr_asst',  ui_text("ui_mainmodeparam_support_character_id_empty_none")),
            (ui_text("ui_mainmodeparam_player_start_dialogue"), 'ptr_plyr_btlst', ui_text("ui_mainmodeparam_dialogue_id_played_before_battle")),
            (ui_text("ui_mainmodeparam_player_string_14"),      'ptr_str14',      ui_text("ui_mainmodeparam_unknown_string_field")),
            (ui_text("ui_mainmodeparam_player_win_dialogue"),   'ptr_plyr_win',   ui_text("ui_mainmodeparam_dialogue_id_played_after_winning")),
        ]:
            w = _le(panel.get(key, ''))
            self._fields[key] = w
            _row(label, w, g, r, note); r += 1
        self._editor_layout.addWidget(self._wrap(g))

        # Enemy Information
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_enemy_information"), P['highlight']))
        g = _grid(); r = 0
        for label, key, note in [
            (ui_text("ui_mainmodeparam_enemy_id"),              'ptr_enemy_id',   ui_text("ui_mainmodeparam_character_id_of_the_opponent")),
            (ui_text("ui_mainmodeparam_enemy_assist_id"),       'ptr_enmy_asst',  ui_text("ui_mainmodeparam_enemy_support_character_id")),
            (ui_text("ui_mainmodeparam_enemy_start_dialogue"),  'ptr_enmy_btlst', ui_text("ui_mainmodeparam_enemy_pre_battle_dialogue_id")),
            (ui_text("ui_mainmodeparam_enemy_string_19"),       'ptr_str19',      ui_text("ui_mainmodeparam_unknown_string_field")),
            (ui_text("ui_mainmodeparam_enemy_win_dialogue"),    'ptr_enmy_win',   ui_text("ui_mainmodeparam_enemy_win_dialogue_id")),
        ]:
            w = _le(panel.get(key, ''))
            self._fields[key] = w
            _row(label, w, g, r, note); r += 1
        self._editor_layout.addWidget(self._wrap(g))

        # Special Rules
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_special_rules"), P['accent_dim']))
        g = _grid()
        for r, (key, note) in enumerate([
            ('spec_rule_1', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_2', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_3', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_4', ui_text("ui_mainmodeparam_rule_4")),
        ]):
            w = _le(panel.get(key, -1))
            self._fields[key] = w
            _row(f"Special Rule {r + 1}", w, g, r, note)
        self._editor_layout.addWidget(self._wrap(g))

        # Secret Missions
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_secret_missions"), P['secondary']))
        mission_keys = [
            ('m1_cond', 'm1_unk', 'ptr_m1_reward', 'm1_gold'),
            ('m2_cond', 'm2_unk', 'ptr_m2_reward', 'm2_gold'),
            ('m3_cond', 'm3_unk', 'ptr_m3_reward', 'm3_gold'),
            ('m4_cond', 'm4_unk', 'ptr_m4_reward', 'm4_gold'),
        ]
        for mi, (ck, uk, rk, gk) in enumerate(mission_keys):
            mf = QFrame()
            mf.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
            mfl = QVBoxLayout(mf)
            mfl.setContentsMargins(16, 10, 16, 10)
            mfl.setSpacing(6)

            ml2 = QLabel(ui_text("ui_mainmodeparam_mission_value", p0=mi + 1))
            ml2.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            ml2.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            mfl.addWidget(ml2)

            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(5)
            g.setColumnStretch(1, 1)
            g.setColumnStretch(2, 1)

            wc = _le(panel.get(ck, -1))
            wu = _le(panel.get(uk,  0))
            wr = _le(panel.get(rk, ''))
            wg = _le(panel.get(gk,  0))
            self._fields[ck] = wc
            self._fields[uk] = wu
            self._fields[rk] = wr
            self._fields[gk] = wg
            _row(ui_text("ui_mainmodeparam_condition"),   wc, g, 0, ui_text("ui_mainmodeparam_mission_type_id_1_disabled"))
            _row(ui_text("ui_mainmodeparam_reward_type"), wu, g, 1, ui_text("ui_mainmodeparam_category_6_card_7_art_etc"))
            _row(ui_text("ui_mainmodeparam_reward_id"),   wr, g, 2, ui_text("ui_mainmodeparam_item_identifier_string"))
            _row(ui_text("ui_mainmodeparam_gold_reward"), wg, g, 3, ui_text("ui_mainmodeparam_gold_for_completing_this_mission"))

            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            inner.setLayout(g)
            mfl.addWidget(inner)
            self._editor_layout.addWidget(mf)

        # Additional Data
        self._editor_layout.addWidget(_section(ui_text("ui_mainmodeparam_additional_data"), P['text_dim']))
        g = _grid()
        for r, (key, label, note) in enumerate([
            ('extra_unk1', ui_text("ui_mainmodeparam_unknown_a"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('extra_unk2', ui_text("ui_mainmodeparam_unknown_b"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('extra_unk3', ui_text("ui_mainmodeparam_unknown_c"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('total_idx',  ui_text("ui_mainmodeparam_total_panel_index"),  ui_text("ui_mainmodeparam_global_index_used_by_the_game")),
        ]):
            w = _le(panel.get(key, 0))
            self._fields[key] = w
            _row(label, w, g, r, note)
        self._editor_layout.addWidget(self._wrap(g))

        self._editor_layout.addStretch()
        self._editor_scroll.verticalScrollBar().setValue(0)

    @staticmethod
    def _wrap(layout):
        f = QFrame()
        f.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner.setLayout(layout)
        flay = QVBoxLayout(f)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(0)
        flay.addWidget(inner)
        return f
