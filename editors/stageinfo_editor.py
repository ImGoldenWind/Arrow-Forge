"""editors/stageinfo_editor.py  –  Editor for StageInfo.bin.xfbin."""

from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    Radius,
    radius,
    error_color,
    ui_font,
)
from core.style_helpers import (
    make_empty_state,
    ss_bg_dark,
    ss_tab_widget,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_file_label,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog, QMessageBox,
    QTabWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt

from core.themes import P
from core.editor_file_state import set_file_label
from parsers.stageinfo_parser import (
    parse_stageinfo_xfbin, save_stageinfo_xfbin,
    STAGE_PARAM_SIZE,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
from editors.stageinfo_forms import _GeneralTab, _ParamsTab, _ClumpsTab, StageFieldError


# Local UI helpers

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


def _color_preview_style(rgba=None, *, invalid=False):
    if invalid:
        bg = P.get("input_bg", P["bg_card"])
        border = error_color()
    else:
        r, g, b, a = rgba
        bg = f"rgba({r}, {g}, {b}, {a})"
        border = P["border"]
    return (
        f"QPushButton {{ background-color: {bg}; border: 1px solid {border}; border-radius: {radius(Radius.BUTTON)}; }}"
        f"QPushButton:hover {{ border: 1px solid {P['accent']}; }}"
    )


def _entry_btn(title, subtitle, selected, on_click):
    btn = EditorListRow()

    btn.setMinimumWidth(0)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


    title_text = str(title)
    name_lbl = btn.add_title(_truncate(title_text, 24))


    name_lbl.setToolTip(title_text)


    if subtitle:
        subtitle_text = str(subtitle)
        sub_lbl = btn.add_subtitle(_truncate(subtitle_text, 28), value_font=ui_font(TypeSize.CODE))


        sub_lbl.setToolTip(subtitle_text)


    btn.set_selected(selected)
    btn.clicked.connect(on_click)
    return btn


# Main editor widget

class StageInfoEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda k, **kw: k)
        self._embedded = embedded
        if not embedded:
            from core.ui.opengl_surface import prepare_opengl_window
            prepare_opengl_window(self)
        self._filepath = None
        self._raw = None
        self._result = None
        self._dirty = False
        self._current_idx = -1
        self._stage_btns = []

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # Toolbar
        top = EditorToolbar()
        tl = top.content_layout

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._open_file)
        self._btn_open.setProperty("designAction", 'open')
        tl.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._save_file)
        tl.addWidget(self._btn_save)

        self._file_lbl = QLabel(ui_text("xfa_no_file"))

        configure_file_label(self._file_lbl)
        tl.addWidget(self._file_lbl)
        tl.addStretch()

        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar
        list_frame = EditorSidebar()


        list_vlay = list_frame.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        list_vlay.addWidget(self._search)

        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        self._btn_add = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add.setEnabled(False)
        configure_button(self._btn_add, height=Size.COMPACT_CONTROL)
        self._btn_add.clicked.connect(self._add_stage)
        self._btn_add.setProperty("designAction", 'new')
        actions_layout.addWidget(self._btn_add, 1)

        self._btn_dup = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup.setEnabled(False)
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.clicked.connect(self._dup_stage)
        self._btn_dup.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton(ui_text("btn_delete"))
        self._btn_del.setEnabled(False)
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.clicked.connect(self._del_stage)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_del, 1)

        list_vlay.addWidget(actions_frame)

        self._list_scroll = QScrollArea()


        configure_scrollarea(self._list_scroll, transparent=True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setMinimumWidth(0)
        self._list_widget.setStyleSheet(ss_transparent())
        self._list_layout = QVBoxLayout(self._list_widget)
        configure_layout(self._list_layout, LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        list_vlay.addWidget(self._list_scroll)

        main_layout.addWidget(list_frame)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        # Right panel
        right = QWidget()
        right.setStyleSheet(ss_bg_dark())
        right_lay = QVBoxLayout(right)
        configure_layout(right_lay, LayoutRole.ROOT)

        self._placeholder_wrap = QWidget(right)
        self._placeholder_wrap.setStyleSheet(ss_transparent())
        self._placeholder_layout = QVBoxLayout(self._placeholder_wrap)
        configure_layout(self._placeholder_layout, LayoutRole.ROOT)
        self._show_placeholder(
            ui_text("ui_stageinfo_open_a_stageinfo_bin_xfbin_file_to_begin_editing"),
            title=ui_text("no_file_loaded"),
            icon_name="fa6s.map-location-dot",
        )
        right_lay.addWidget(self._placeholder_wrap, 1)

        self._tabs = QTabWidget()
        self._tabs.setFont(ui_font(TypeSize.CODE))
        self._tabs.setStyleSheet(ss_tab_widget())
        self._tabs.setVisible(False)

        self._tab_general = _GeneralTab()
        self._tab_params  = _ParamsTab()
        self._tab_clumps  = _ClumpsTab()

        self._tab_general.changed.connect(self._on_data_changed)
        self._tab_params.changed.connect(self._on_data_changed)
        self._tab_clumps.changed.connect(self._on_data_changed)
        self._tab_clumps.path_added.connect(self._tab_general.ensure_path)
        self._tabs.currentChanged.connect(self._tab_changed)

        self._tabs.addTab(self._tab_general, ui_text("ui_stageinfo_general"))
        self._tabs.addTab(self._tab_params,  ui_text("ui_stageinfo_params"))
        self._tabs.addTab(self._tab_clumps,  ui_text("ui_stageinfo_clumps"))
        self._tabs.setTabIcon(0, qta.icon("fa6s.circle-info", color=P["accent"]))
        self._tabs.setTabIcon(1, qta.icon("fa6s.sliders", color=P["accent"]))
        self._tabs.setTabIcon(2, qta.icon("fa6s.cubes", color=P["accent"]))

        right_lay.addWidget(self._tabs, 1)

        main_layout.addWidget(right, 1)
        root.addWidget(main, 1)

    def _show_placeholder(self, text, *, title=None, icon_name="fa6s.list"):
        _clear_layout(self._placeholder_layout)
        card = make_empty_state(
            self._placeholder_wrap,
            title=title or ui_text("ui_model_viewer_select_item"),
            text=text,
            icon_name=icon_name,
        )
        self._placeholder_layout.addStretch()
        self._placeholder_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._placeholder_layout.addStretch()
        self._placeholder_wrap.setVisible(True)

    # File I/O

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("ui_stageinfo_open_stageinfo_bin_xfbin"), game_files_dialog_dir(target_patterns="StageInfo.bin.xfbin"),
            "XFBIN Files (*.xfbin);;All Files (*)"
        )
        if path:
            if self._dirty:
                reply = QMessageBox.question(self, ui_text('unsaved_changes_title'),
                    ui_text('proj_unsaved_hint'),
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                if reply == QMessageBox.StandardButton.Save and not self._save_file():
                    return
            self._load(path)

    def _load(self, path):
        create_backup_on_open(path)
        try:
            raw, result = parse_stageinfo_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), str(exc))
            return

        self._filepath = path
        self._raw      = raw
        self._result   = result
        self._dirty    = False
        self._current_idx = -1

        set_file_label(self._file_lbl, path)
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(False)
        self._btn_del.setEnabled(False)

        self._show_placeholder(ui_text("ui_stageinfo_select_a_stage"))
        self._tabs.setVisible(False)

        for tab in (self._tab_general, self._tab_params, self._tab_clumps):
            tab.source_path = path
        self._rebuild_stage_list()
        if self._result['stages']:
            self._on_stage_selected(0)

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._result is None:
            return False
        if not self._flush_current(show_errors=True):
            return False
        try:
            save_stageinfo_xfbin(save_path, self._raw, self._result)
            commit_save_path(self, save_path)
            self._dirty = False
            set_file_label(self._file_lbl, save_path)
            return True
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_assist_save_error'), str(exc))
            return False

    # Stage list

    def _rebuild_stage_list(self):
        _clear_layout(self._list_layout)
        self._stage_btns = []
        for i, s in enumerate(self._result['stages']):
            label = s['code'] if s['code'] else f"Stage {i:02d}"
            subtitle = f"#{i:02d}"
            btn = _entry_btn(
                label, subtitle,
                selected=(i == self._current_idx),
                on_click=lambda _, idx=i: self._on_stage_selected(idx),
            )
            self._list_layout.insertWidget(self._list_layout.count(), btn)
            self._stage_btns.append((btn, i))
        self._list_layout.addStretch()
        self._filter_list()

    def _filter_list(self):
        if self._result is None:
            return
        q = self._search.text().lower()
        for btn, i in self._stage_btns:
            if i >= len(self._result['stages']):
                continue
            s = self._result['stages'][i]
            btn.setVisible(not q or q in s['code'].lower() or q in f"{i:02d}")

    def _on_stage_selected(self, idx):
        if not self._flush_current(show_errors=True):
            return False
        self._current_idx = idx
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)

        for btn, i in self._stage_btns:
            btn.set_selected(i == idx)

        stage = self._result['stages'][idx]
        self._tab_general.load_stage(stage)
        self._tab_params.load_stage(stage)
        self._tab_clumps.load_stage(stage)

        self._placeholder_wrap.setVisible(False)
        self._tabs.setVisible(True)

    def _flush_current(self, *, show_errors=False):
        if self._current_idx < 0 or self._result is None:
            return True
        stage = self._result['stages'][self._current_idx]
        pending = copy.deepcopy(stage)
        try:
            self._tab_general.collect(pending)
            self._tab_params.collect(pending)
            self._tab_clumps.collect(pending)
        except StageFieldError as error:
            if show_errors:
                tab = next(t for t in (self._tab_general, self._tab_params, self._tab_clumps)
                           if t.isAncestorOf(error.field))
                self._tabs.setCurrentWidget(tab)
                tab._error(error)
            return False
        for clump, updated in zip(stage['clumps'], pending.pop('clumps')):
            clump.update(updated)
        stage.update(pending)
        for btn, i in self._stage_btns:
            if i == self._current_idx:
                lbls = btn.findChildren(QLabel)
                if lbls:
                    label = stage['code'] if stage['code'] else f"Stage {i:02d}"
                    lbls[0].setText(_truncate(label, 24))
                    lbls[0].setToolTip(label)
                break
        return True

    def _unique_code(self, base, *, copy_suffix=False):
        existing = {s['code'] for s in self._result['stages']}
        for index in range(len(existing) + 2):
            suffix = ('_copy' if copy_suffix else '') + (str(index + 1) if index else '')
            value = base[:23 - len(suffix)] + suffix
            if value not in existing:
                return value

    def _add_stage(self):
        if self._result is None:
            return
        if not self._flush_current(show_errors=True):
            return
        new_stage = {
            'code':   self._unique_code('STAGE_NEW'),
            'paths':  ['data/stage/new.xfbin'],
            'clumps': [{
                'xfbin_path': 'data/stage/new.xfbin',
                'clump_name': 'new_clump00',
                'unk_name':   '',
                'unk2_name':  '',
                'skip_data':  b'\x00' * 16,
                'val1': 0x3C,
                'val2': 0x78,
            }],
            'params': bytearray(STAGE_PARAM_SIZE),
        }
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _dup_stage(self):
        if self._result is None or self._current_idx < 0:
            return
        if not self._flush_current(show_errors=True):
            return
        src = self._result['stages'][self._current_idx]
        new_stage = copy.deepcopy(src)
        new_stage['code'] = self._unique_code(src['code'], copy_suffix=True)
        self._result['stages'].append(new_stage)
        self._rebuild_stage_list()
        self._on_stage_selected(len(self._result['stages']) - 1)
        self._mark_dirty()

    def _del_stage(self):
        if self._result is None or not self._result['stages']:
            return
        row = self._current_idx
        if row < 0:
            return
        code = self._result['stages'][row]['code']
        reply = QMessageBox.question(
            self, ui_text("ui_stageinfo_delete_stage"),
            ui_text("ui_stageinfo_remove_stage_value_value", p0=row, p1=code),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._current_idx = -1
        self._btn_dup.setEnabled(False)
        self._btn_del.setEnabled(False)
        del self._result['stages'][row]
        self._tabs.setVisible(False)
        self._show_placeholder(ui_text("ui_stageinfo_select_a_stage"))
        self._rebuild_stage_list()
        self._mark_dirty()

    def _tab_changed(self, index):
        if index == 2 and self._current_idx >= 0:
            self._tab_clumps.refresh_choices(self._tab_general.current_paths())
        if index == 1 and self._current_idx >= 0:
            pending = copy.deepcopy(self._result['stages'][self._current_idx])
            try:
                self._tab_general.collect(pending)
                self._tab_clumps.collect(pending)
            except StageFieldError:
                return
            self._tab_params._map_preview.set_context(pending, self._tab_params.source_path)

    # Dirty state

    def _on_data_changed(self):
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self._btn_save.setEnabled(True)
        set_file_label(self._file_lbl, self._filepath, dirty=True)
