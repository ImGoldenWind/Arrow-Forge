import os
import threading
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QScrollArea, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_input, ss_sep, ss_accent_sep, ss_search, ss_scrollarea, ss_scrollarea_transparent,
    ss_accent_label, ss_bg_dark, ss_bg_panel, ss_dim_label, ss_field_label,
    ss_file_label, ss_main_label, ss_panel_title, ss_sidebar_frame, ss_transparent,
    make_editor_card, make_empty_state, add_editor_card_title, make_editor_field_shell,
    TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from parsers.mainmodeparam_parser import (
    parse_mainmodeparam, save_mainmodeparam,
    make_default_panel, PANEL_TYPE_NAMES,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Layout helpers

def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "…"

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


def _lbl(text, dim=False, bold=False, size=12):
    w = QLabel(text)
    w.setFont(QFont("Segoe UI", size,
                    QFont.Weight.Bold if bold else QFont.Weight.Normal))
    w.setStyleSheet(ss_dim_label() if dim else ss_main_label())
    return w


def _le(value='', width=None):
    w = QLineEdit(str(value))
    w.setFont(QFont("Consolas", 12))
    w.setFixedHeight(28)
    w.setStyleSheet(ss_input())
    w.setMinimumWidth(0)
    w.setCursorPosition(0)
    if width:
        w.setFixedWidth(width)
    return w


def _combo(items, idx=0):
    w = QComboBox()
    w.setFont(QFont("Segoe UI", 12))
    w.addItems(items)
    w.setCurrentIndex(idx)
    w.setStyleSheet(ss_input())
    w.setMinimumWidth(0)
    w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    return w


def _section(title, color=None):
    lbl = QLabel(title)
    lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    lbl.setStyleSheet(ss_accent_label() if color else ss_panel_title())
    lbl.setContentsMargins(0, 8, 0, 2)
    return lbl


def _row(label, widget, grid, row, note=None):
    field, layout, _label, _hint = make_editor_field_shell(label, note or "")
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout.addWidget(widget)
    compact = bool(grid.property("compact"))
    grid.addWidget(field, row if compact else row // 2, 0 if compact else row % 2)


def _grid(compact=False):
    g = QGridLayout()
    g.setProperty("compact", compact)
    g.setContentsMargins(0, 4, 0, 0)
    g.setHorizontalSpacing(16)
    g.setVerticalSpacing(10)
    g.setColumnStretch(0, 1)
    if not compact:
        g.setColumnStretch(1, 1)
    return g


# Panel list item

class PanelItem(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, idx, panel, parent=None):
        super().__init__(parent)
        self.setObjectName("MainModePanelItem")
        self._idx = idx
        self._update_style(selected=False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(54)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 5)
        lay.setSpacing(1)

        typ       = panel.get('type', 0)
        tc        = self._type_color(typ)
        panel_id  = panel.get('ptr_panel_id', '') or f'Panel {idx + 1}'
        player_id = panel.get('ptr_player_id', '') or '???'
        enemy_id  = panel.get('ptr_enemy_id',  '') or '???'
        total_idx = panel.get('total_idx', 0)
        type_name = PANEL_TYPE_NAMES.get(typ, str(typ))

        title_text = ui_text("ui_mainmodeparam_value_value", p0=total_idx, p1=panel_id)
        t = QLabel(_truncate(title_text, 24))
        t.setFont(QFont(P.get("font_ui", "Segoe UI"), 11, QFont.Weight.Bold))
        t.setToolTip(title_text)
        t.setStyleSheet(ss_main_label())
        t.setMinimumWidth(0)
        t.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        subtitle_text = ui_text("ui_mainmodeparam_value_vs_value_value", p0=player_id, p1=enemy_id, p2=type_name)
        s = QLabel(_truncate(subtitle_text, 32))
        s.setFont(QFont(P.get("font_ui", "Segoe UI"), 10))
        s.setToolTip(subtitle_text)
        s.setStyleSheet(f"color: {tc}; background: transparent;")
        s.setMinimumWidth(0)
        s.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        lay.addWidget(t)
        lay.addWidget(s)

    @staticmethod
    def _type_color(typ):
        # 0=Normal → dim, 1=Extra → secondary, 2=Boss → accent
        return {0: P['text_dim'], 1: P['secondary'], 2: P['accent']}.get(typ, P['text_dim'])

    def _update_style(self, selected: bool):
        bg = P.get("sidebar_item_selected_bg", P["bg_card"]) if selected else "transparent"
        hover = P.get("sidebar_item_hover_bg", P["bg_card_hov"])
        border = P.get("accent", P["border"]) if selected else "transparent"
        if selected:
            self.setStyleSheet(
                f"QFrame#MainModePanelItem {{ background: {bg}; border-radius: 6px; border: 1px solid {border}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#MainModePanelItem {{ background: {bg}; border-radius: 6px; border: 1px solid transparent; }}"
                f"QFrame#MainModePanelItem:hover {{ background: {hover}; }}"
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
        self._last_editor_compact = None

        self._sig_done.connect(self._on_load_done)
        self._sig_error.connect(self._on_load_error)
        self._build_ui()

    # UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        # top bar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
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
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))

        tl.addStretch(1)

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        # main area
        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        ml = QHBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(286)
        sidebar.setStyleSheet(ss_sidebar_frame())
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(6, 8, 6, 6)
        sl.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self.t("search_placeholder"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont(P.get("font_ui", "Segoe UI"), 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_list)
        sl.addWidget(self._search)

        # action buttons row
        act = QWidget()
        act.setStyleSheet(ss_transparent())
        al = QHBoxLayout(act)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFont(QFont(P.get("font_ui", "Segoe UI"), 10))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_panel)

        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFont(QFont(P.get("font_ui", "Segoe UI"), 10))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_panel)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFont(QFont(P.get("font_ui", "Segoe UI"), 10))
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
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_inner = QWidget()
        self._list_inner.setMinimumWidth(0)
        self._list_inner.setStyleSheet(ss_transparent())
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
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(12, 12, 12, 16)
        self._editor_layout.setSpacing(8)
        self._editor_scroll.setWidget(self._editor_widget)
        ml.addWidget(self._editor_scroll, 1)

        root.addWidget(main, 1)
        self._show_placeholder()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("no_file_loaded"),
            text=ui_text("ui_mainmodeparam_open_a_mainmodeparam_bin_xfbin_file_to_begin_editing"),
            icon_name="fa6s.diagram-project",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
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
        self._file_lbl.setStyleSheet(ss_file_label())

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
        set_file_label(self._file_lbl, path)
        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._current = -1
        self._rebuild_list()
        self._show_placeholder()
        if self._panels:
            QTimer.singleShot(50, lambda: self._select_panel(0))

    def _on_load_error(self, msg):
        set_file_label_empty(self._file_lbl, self.t("no_file_loaded"))
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
            set_file_label(self._file_lbl, self._filepath)
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
                grp.setStyleSheet(ss_accent_label() + f"border-top: 1px solid {P['border']};")
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

    def _is_compact_editor(self):
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _prep_card(self, card):
        card.setMinimumWidth(0)
        card.setMaximumWidth(1040)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _prep_summary_field(self, frame, editor):
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _summary_field(self, label, value):
        frame, layout, _label, _hint = make_editor_field_shell(label)
        edit = QLineEdit(str(value))
        edit.setReadOnly(True)
        edit.setFixedHeight(30)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        edit.setCursorPosition(0)
        self._prep_summary_field(frame, edit)
        layout.addWidget(edit)
        return frame

    def _build_header_card(self, panel):
        panel_id = panel.get('ptr_panel_id', '') or f"Panel {self._current + 1}"
        typ = int(panel.get('type', 0))
        type_name = PANEL_TYPE_NAMES.get(typ, str(typ))
        subtitle = ui_text(
            "ui_mainmodeparam_value_vs_value_value",
            p0=panel.get('ptr_player_id', '') or "???",
            p1=panel.get('ptr_enemy_id', '') or "???",
            p2=type_name,
        )
        card, layout = make_editor_card(self._editor_widget, margins=(16, 14, 16, 14), spacing=10)
        self._prep_card(card)
        add_editor_card_title(
            layout,
            panel_id,
            "fa6s.map-location-dot",
            subtitle=subtitle,
            icon_size=20,
        )
        inner = QWidget(card)
        inner.setStyleSheet(ss_transparent())
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        columns = 1 if self._is_compact_editor() else 3
        summary = [
            (ui_text("ui_mainmodeparam_part_jojo_arc"), panel.get('part', 0)),
            (ui_text("ui_mainmodeparam_stage_id"), panel.get('ptr_stage_id', '')),
            (ui_text("ui_mainmodeparam_panel_type"), type_name),
        ]
        for idx, (label, value) in enumerate(summary):
            grid.addWidget(self._summary_field(label, value), idx // columns, idx % columns)
            grid.setColumnStretch(idx % columns, 1)
        layout.addWidget(inner)
        return card

    # Form builder

    def _build_form(self, panel):
        _clear_layout(self._editor_layout)
        self._fields = {}
        compact = self._is_compact_editor()
        self._last_editor_compact = compact

        typ = panel.get('type', 0)
        self._editor_layout.addWidget(self._build_header_card(panel))

        # Basic Information
        basic_title = ui_text("ui_mainmodeparam_basic_information")
        g = _grid(compact)
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

        self._editor_layout.addWidget(self._wrap(g, basic_title, "fa6s.circle-info"))

        # Player Information
        player_title = ui_text("ui_mainmodeparam_player_information")
        g = _grid(compact); r = 0
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
        self._editor_layout.addWidget(self._wrap(g, player_title, "fa6s.user"))

        # Enemy Information
        enemy_title = ui_text("ui_mainmodeparam_enemy_information")
        g = _grid(compact); r = 0
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
        self._editor_layout.addWidget(self._wrap(g, enemy_title, "fa6s.user-ninja"))

        # Special Rules
        rules_title = ui_text("ui_mainmodeparam_special_rules")
        g = _grid(compact)
        for r, (key, note) in enumerate([
            ('spec_rule_1', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_2', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_3', ui_text("ui_mainmodeparam_battle_modifier_1_disabled")),
            ('spec_rule_4', ui_text("ui_mainmodeparam_rule_4")),
        ]):
            w = _le(panel.get(key, -1))
            self._fields[key] = w
            _row(f"Special Rule {r + 1}", w, g, r, note)
        self._editor_layout.addWidget(self._wrap(g, rules_title, "fa6s.gavel"))

        # Secret Missions
        missions_title = ui_text("ui_mainmodeparam_secret_missions")
        missions_card, missions_layout = make_editor_card(self._editor_widget, margins=(16, 14, 16, 16), spacing=10)
        self._prep_card(missions_card)
        add_editor_card_title(missions_layout, missions_title, "fa6s.medal")
        mission_keys = [
            ('m1_cond', 'm1_unk', 'ptr_m1_reward', 'm1_gold'),
            ('m2_cond', 'm2_unk', 'ptr_m2_reward', 'm2_gold'),
            ('m3_cond', 'm3_unk', 'ptr_m3_reward', 'm3_gold'),
            ('m4_cond', 'm4_unk', 'ptr_m4_reward', 'm4_gold'),
        ]
        for mi, (ck, uk, rk, gk) in enumerate(mission_keys):
            mf = QFrame()
            mf.setStyleSheet(ss_transparent() + f"border-top: 1px solid {P['border']};")
            mfl = QVBoxLayout(mf)
            mfl.setContentsMargins(0, 10, 0, 0)
            mfl.setSpacing(8)

            ml2 = QLabel(ui_text("ui_mainmodeparam_mission_value", p0=mi + 1))
            ml2.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            ml2.setStyleSheet(ss_field_label())
            mfl.addWidget(ml2)

            g = QGridLayout()
            g.setProperty("compact", compact)
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(5)
            g.setColumnStretch(0, 1)
            if not compact:
                g.setColumnStretch(1, 1)

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
            inner.setStyleSheet(ss_transparent())
            inner.setLayout(g)
            mfl.addWidget(inner)
            missions_layout.addWidget(mf)
        self._editor_layout.addWidget(missions_card)

        # Additional Data
        extra_title = ui_text("ui_mainmodeparam_additional_data")
        g = _grid(compact)
        for r, (key, label, note) in enumerate([
            ('extra_unk1', ui_text("ui_mainmodeparam_unknown_a"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('extra_unk2', ui_text("ui_mainmodeparam_unknown_b"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('extra_unk3', ui_text("ui_mainmodeparam_unknown_c"),          ui_text("ui_mainmodeparam_unknown_uint32")),
            ('total_idx',  ui_text("ui_mainmodeparam_total_panel_index"),  ui_text("ui_mainmodeparam_global_index_used_by_the_game")),
        ]):
            w = _le(panel.get(key, 0))
            self._fields[key] = w
            _row(label, w, g, r, note)
        self._editor_layout.addWidget(self._wrap(g, extra_title, "fa6s.database"))

        self._editor_layout.addStretch()
        self._editor_scroll.verticalScrollBar().setValue(0)

    def _wrap(self, layout, title=None, icon_name=None):
        f, flay = make_editor_card(self._editor_widget, margins=(16, 14, 16, 16), spacing=10)
        self._prep_card(f)
        if title:
            add_editor_card_title(flay, title, icon_name)
        inner = QWidget()
        inner.setStyleSheet(ss_transparent())
        inner.setLayout(layout)
        flay.addWidget(inner)
        return f

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current < 0 or self._last_editor_compact is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_editor_compact:
            return
        self._flush_panel()
        QTimer.singleShot(0, self._rebuild_current_panel_for_width)

    def _rebuild_current_panel_for_width(self):
        if 0 <= self._current < len(self._panels):
            self._build_form(self._panels[self._current])
