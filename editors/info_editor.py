from core.design_tokens import (
    Insets,
    LayoutRole,
    Padding,
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
    ss_accent_label,
    ss_bg_dark,
    ss_dim_label,
    ss_field_label,
    ss_input_accent,
    ss_main_label,
    ss_tab_bar,
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
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import threading
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QTabBar, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics
from core.editor_file_state import set_file_label
from core.skeleton import SkeletonListRow
from parsers.info_parser import (
    parse_info_xfbin, save_info_xfbin,
    get_scene_description, make_default_collision,
    analyze_char_select, INT_FIELDS,
)
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


# Helpers

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


def _make_font(family="Segoe UI", size=12, bold=False):
    f = mono_font(size) if family == "Consolas" else ui_font(size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def _style_entry(entry, *, h=Size.CONTROL, font=None):
    configure_input(entry, height=h, font=font)
    entry.setMinimumWidth(0)
    if font:
        entry.setFont(font)


def _make_info_card(parent=None, *, margins=Insets.CARD, spacing=Size.CARD_GAP):
    return make_editor_card(parent, margins=margins, spacing=spacing)


def _style_accent_entry(entry):
    entry.setStyleSheet(ss_input_accent())


def _field_shell(label_text, hint_text="", *, label_size=12):
    frame, layout, _label, _hint = make_editor_field_shell(label_text, hint_text, label_font_size=label_size)
    return frame, layout


def _value_label(text, *, size=14, bold=True):
    label = QLabel(str(text))
    label.setFont(_make_font("Consolas", size, bold=bold))
    label.setStyleSheet(ss_accent_label())
    return label


# Shared geometry and the subject-specific canvas are kept outside the form.
from editors.info_canvas import CollisionCanvas as _InteractiveCollisionCanvas
from core.ui_collisions import (GEOMETRY_FIELDS, I32_MIN, I32_MAX, circle,
                                hit_score, identity_index, parse_integer, vertices, xml_text_valid)
from core.ui.number_input import IntegerStepper
from core.ui.value_combo import EditorValueCombo
from core.style_helpers import ss_input_validation


# Set / Collision list button widgets

class _SetButton(EditorListRow):
    def __init__(self, desc, sub_text, parent=None):
        super().__init__(parent)
        self.set_texts(desc, sub_text)


#  InfoEditor  –  main widget

class InfoEditor(QWidget):
    """Full-featured editor for info.xfbin UI collision files.

    Displays all scene sets and their collision shapes,
    allows editing, adding, deleting collisions, and provides
    analysis of the character select screen layout.
    """

    _load_done_signal = pyqtSignal(str, object, list, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t = lang_func

        self._raw_data = None
        self._sets = []
        self._meta = None
        self._current_set = None
        self._current_coll = None
        self._set_buttons = []
        self._coll_buttons = []
        self._coll_button_groups = {}
        self._coll_tabs = []
        self._updating_coll_tabs = False
        self._fields = {}
        self._interactive_canvas = None
        self._computed_labels = {}
        self._vis_coord_label = None

        self._filepath = None
        self._dirty = False
        self._original_collisions = {}
        self._view_state = None
        self._geometry_undo = []
        self._geometry_redo = []

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path))
        install_editor_chrome(self)

    # UI construction

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        configure_layout(root_layout, LayoutRole.ROOT)

        # Toolbar
        top = EditorToolbar()
        top_layout = top.content_layout

        open_btn = QPushButton(self.t("btn_open_file"))
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(self._load_file)
        open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label)

        top_layout.addStretch()


        root_layout.addWidget(top)

        sep = EditorSeparator(accent=True)


        root_layout.addWidget(sep)

        # Main area: left sidebar (scenes) + collision tabs + editor
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Left sidebar: scene set list
        left_panel = self._build_set_list()
        main_layout.addWidget(left_panel)

        # Separator
        sep_l = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(sep_l)

        # Tab widget — "Collisions" tab (collision list + editor)
        right_panel = QWidget()
        right_panel.setStyleSheet(ss_bg_dark())
        right_layout = QVBoxLayout(right_panel)
        configure_layout(right_layout, LayoutRole.ROOT)

        coll_tabs_bar = self._build_collision_tabs_bar()
        right_layout.addWidget(coll_tabs_bar)

        sep_tabs = EditorSeparator()


        right_layout.addWidget(sep_tabs)

        # Right panel: editor (scrollable)
        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_content = QWidget()
        self._editor_content.setMinimumWidth(0)
        self._editor_content.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_content)
        self._editor_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_content)
        right_layout.addWidget(self._editor_scroll, 1)

        # Placeholder
        self._editor_layout.addStretch()
        self._placeholder = make_empty_state(
            self._editor_content,
            title=self.t("no_file_loaded"),
            text=self.t("placeholder_info"),
            icon_name="fa6s.object-group",
        )
        self._editor_layout.addWidget(self._placeholder, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

        main_layout.addWidget(right_panel, 1)

        root_layout.addWidget(main, 1)

    def _build_set_list(self):
        panel = EditorSidebar()


        layout = panel.content_layout


        # Search
        self._set_search_entry = QLineEdit()
        configure_search(self._set_search_entry)
        self._set_search_entry.textChanged.connect(self._filter_set_list)
        layout.addWidget(self._set_search_entry)

        # Actions
        actions = EditorActionRow()

        al = actions.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._add_set_btn = QPushButton(self.t("btn_add_scene"))
        configure_button(self._add_set_btn, height=Size.COMPACT_CONTROL)
        self._add_set_btn.setEnabled(False)
        self._add_set_btn.clicked.connect(self._add_new_set)
        self._add_set_btn.setProperty("designAction", 'new')
        al.addWidget(self._add_set_btn, 1)

        self._del_set_btn = QPushButton(self.t("btn_delete"))
        configure_button(self._del_set_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_set_btn.setEnabled(False)
        self._del_set_btn.clicked.connect(self._delete_set)
        self._del_set_btn.setProperty("designAction", 'delete')
        al.addWidget(self._del_set_btn, 1)

        layout.addWidget(actions)

        # Scrollable set list
        self._set_scroll = QScrollArea()


        self._set_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._set_scroll, transparent=True)
        self._set_list_widget = QWidget()
        self._set_list_widget.setMinimumWidth(0)
        self._set_list_widget.setStyleSheet(ss_transparent())
        self._set_list_layout = QVBoxLayout(self._set_list_widget)
        self._set_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        configure_layout(self._set_list_layout, LayoutRole.LIST)
        self._set_scroll.setWidget(self._set_list_widget)
        layout.addWidget(self._set_scroll, 1)

        return panel

    def _build_collision_tabs_bar(self):
        bar = EditorToolbar()
        layout = bar.content_layout

        self._coll_tab_widget = QTabBar()
        self._coll_tab_widget.setFont(ui_font(TypeSize.CODE))
        self._coll_tab_widget.setExpanding(False)
        self._coll_tab_widget.setDrawBase(False)
        self._coll_tab_widget.setUsesScrollButtons(True)
        self._coll_tab_widget.setStyleSheet(ss_tab_bar())
        self._coll_tab_widget.currentChanged.connect(self._on_collision_tab_changed)
        layout.addWidget(self._coll_tab_widget, 1)

        btn_font = ui_font(TypeSize.BODY)

        self._add_coll_btn = QPushButton(self.t("btn_new"))
        configure_button(self._add_coll_btn, height=Size.COMPACT_CONTROL)
        self._add_coll_btn.setEnabled(False)
        self._add_coll_btn.clicked.connect(self._add_collision)
        self._add_coll_btn.setProperty("designAction", 'new')
        layout.addWidget(self._add_coll_btn)

        self._dup_coll_btn = QPushButton(self.t("btn_duplicate"))
        configure_button(self._dup_coll_btn, height=Size.COMPACT_CONTROL)
        self._dup_coll_btn.setEnabled(False)
        self._dup_coll_btn.clicked.connect(self._duplicate_collision)
        self._dup_coll_btn.setProperty("designAction", 'duplicate')
        layout.addWidget(self._dup_coll_btn)

        self._del_coll_btn = QPushButton(self.t("btn_delete"))
        configure_button(self._del_coll_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_coll_btn.setEnabled(False)
        self._del_coll_btn.clicked.connect(self._delete_collision)
        self._del_coll_btn.setProperty("designAction", 'delete')
        layout.addWidget(self._del_coll_btn)

        return bar

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_info"), game_files_dialog_dir(target_patterns="info.xfbin"),
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        create_backup_on_open(path)
        self._file_label.setText(self.t("loading"))
        self._show_set_skeleton()

        def worker():
            try:
                raw_data, sets, meta = parse_info_xfbin(path)
            except Exception as e:
                self._load_error_signal.emit(str(e))
                return
            self._load_done_signal.emit(path, raw_data, sets, meta)

        threading.Thread(target=worker, daemon=True).start()

    def _show_set_skeleton(self):
        _clear_layout(self._set_list_layout)
        self._set_buttons = []
        for _ in range(12):
            skel = SkeletonListRow(self._set_list_widget)
            self._set_list_layout.addWidget(skel)

    def _on_load_error(self, msg):
        _clear_layout(self._set_list_layout)
        self._file_label.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.setEnabled(True)
        set_file_label(self._file_label, self._filepath, dirty=True)

    def _on_load_done(self, path, raw_data, sets, meta):
        self._fields = {}
        self._original_collisions = {id(c): copy.deepcopy(c) for scene in sets for c in scene['collisions']}
        self._view_state = None
        self._geometry_undo, self._geometry_redo = [], []
        self._raw_data = raw_data
        self._sets = sets
        self._meta = meta
        self._filepath = path
        self._dirty = False
        self._current_set = None
        self._current_coll = None
        set_file_label(self._file_label, path)
        self._save_btn.setEnabled(True)
        self._add_set_btn.setEnabled(True)
        self._del_set_btn.setEnabled(True)
        self._populate_set_list()
        if not sets:
            _clear_layout(self._editor_layout)
            self._interactive_canvas = None
            self._add_coll_btn.setEnabled(False)
            self._dup_coll_btn.setEnabled(False)
            self._del_coll_btn.setEnabled(False)

    def _save_file(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not self._raw_data or not save_path:
            return
        if not self._apply_fields():
            return False
        try:
            save_info_xfbin(save_path, self._raw_data, self._sets, self._meta)
            commit_save_path(self, save_path)
            self._dirty = False
            set_file_label(self._file_label, save_path)
            return True
        except Exception as e:
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=e))
            return False

    # Set list

    def _scene_description(self, name):
        if name.startswith('ccSceneMainModePage'):
            return self.t('info_main_page', page=name[len('ccSceneMainModePage'):])
        if name in ('PresetWindowSelectionP1', 'PresetWindowSelectionP2'):
            return self.t('info_preset_scene', player=name[-1])
        key = 'info_scene_' + name
        caption = self.t(key)
        return get_scene_description(name) if caption == key else caption

    def _populate_set_list(self):
        _clear_layout(self._set_list_layout)
        self._set_buttons = []

        for s in self._sets:
            desc = self._scene_description(s['name'])
            sub_text = s["name"]

            btn = _SetButton(desc, sub_text, self._set_list_widget)
            btn.clicked.connect(lambda _checked=False, ss=s: self._select_set(ss))
            self._set_list_layout.addWidget(btn)
            self._set_buttons.append((btn, s))

        self._filter_set_list()
        if self._sets:
            self._select_set(self._sets[0])

    def _filter_set_list(self):
        query = self._set_search_entry.text().lower()
        for btn, s in self._set_buttons:
            desc = self._scene_description(s['name']).lower()
            match = query in s['name'].lower() or query in desc or any(query in c['name'].lower() for c in s['collisions'])
            btn.setVisible(match)

    def _select_set(self, s):
        if not self._apply_fields():
            return False
        self._fields = {}
        self._view_state = None
        self._current_set = s
        self._current_coll = None
        for btn, ss in self._set_buttons:
            btn.set_selected(ss is s)

        self._add_coll_btn.setEnabled(True)
        self._dup_coll_btn.setEnabled(bool(s['collisions']))
        self._del_coll_btn.setEnabled(bool(s['collisions']))
        self._populate_coll_list()
        if s['collisions']:
            self._select_collision(s['collisions'][0])
        else:
            self._build_set_overview()

    # Collision list

    def _coll_tab_label(self, idx, coll):
        cname = coll.get('name', '') or self.t("coll_unnamed")
        return f"#{idx:02d} {cname}"

    def _populate_coll_list(self, preferred_coll=None):
        current_tab = self._coll_tab_widget.currentIndex() if hasattr(self, '_coll_tab_widget') else 0
        self._updating_coll_tabs = True
        while self._coll_tab_widget.count():
            self._coll_tab_widget.removeTab(0)
        self._coll_buttons = []
        self._coll_button_groups = {}
        self._coll_tabs = []
        if not self._current_set:
            self._updating_coll_tabs = False
            return

        preferred_tab = -1
        for i, coll in enumerate(self._current_set['collisions']):
            self._coll_tab_widget.addTab(self._coll_tab_label(i, coll))
            self._coll_tabs.append(coll)
            if preferred_coll is not None and coll is preferred_coll:
                preferred_tab = i

        if preferred_tab >= 0:
            self._coll_tab_widget.setCurrentIndex(preferred_tab)
        elif self._coll_tab_widget.count():
            self._coll_tab_widget.setCurrentIndex(min(current_tab, self._coll_tab_widget.count() - 1))
        self._updating_coll_tabs = False

    def _refresh_collision_tabs(self, preferred_coll=None):
        self._populate_coll_list(preferred_coll=preferred_coll or self._current_coll)

    def _on_collision_tab_changed(self, idx):
        if self._updating_coll_tabs or idx < 0 or idx >= len(self._coll_tabs):
            return
        self._select_collision(self._coll_tabs[idx])

    def _select_collision(self, coll):
        if not self._apply_fields():
            self._updating_coll_tabs = True
            self._coll_tab_widget.setCurrentIndex(identity_index(self._coll_tabs, self._current_coll))
            self._updating_coll_tabs = False
            return False
        if self._current_coll is coll and 'type' in self._fields:
            return True
        if (self._interactive_canvas is not None and self._interactive_canvas.isVisible()
                and identity_index(self._interactive_canvas._collisions, coll) >= 0):
            self._view_state = self._interactive_canvas.view_state()
        self._current_coll = coll
        self._dup_coll_btn.setEnabled(True)
        self._del_coll_btn.setEnabled(True)
        idx = identity_index(self._coll_tabs, coll)
        self._updating_coll_tabs = True
        self._coll_tab_widget.setCurrentIndex(idx)
        self._updating_coll_tabs = False
        self._build_collision_editor(coll)
        return True

    def _field_text(self, widget):
        return widget.value_text() if isinstance(widget, EditorValueCombo) else widget.text()

    def _apply_fields(self):
        if not self._fields:
            return True
        pending, invalid = {}, []
        for key, widget in self._fields.items():
            try:
                text = self._field_text(widget)
                if key in INT_FIELDS:
                    pending[key] = parse_integer(text)
                else:
                    if not xml_text_valid(text):
                        raise ValueError('XML text')
                    pending[key] = text
                widget.setStyleSheet(ss_input_validation(False))
            except ValueError:
                widget.setStyleSheet(ss_input_validation(True))
                invalid.append(key)
        if hasattr(self, '_validation_label'):
            self._validation_label.setText(self.t('info_invalid', fields=', '.join(invalid)) if invalid else '')
            self._validation_label.setVisible(bool(invalid))
        if invalid:
            return False
        changed = False
        for key, value in pending.items():
            target = self._current_set if key == '_set_name' else self._current_coll
            field = 'name' if key == '_set_name' else key
            if target is not None and target.get(field) != value:
                target[field] = value
                changed = True
        if changed:
            self._mark_dirty()
            self._update_coll_list_labels()
            for button, scene in self._set_buttons:
                if scene is self._current_set:
                    button.set_texts(self._scene_description(scene['name']), scene['name'])
                    break
        return True

    # Set overview (shown when set selected, no collision selected)

    def _show_scene_overview(self):
        if self._current_set is not None and self._apply_fields():
            self._current_coll = None
            self._dup_coll_btn.setEnabled(False)
            self._del_coll_btn.setEnabled(False)
            self._build_set_overview()

    def _build_set_overview(self):
        self._dup_coll_btn.setEnabled(False)
        self._del_coll_btn.setEnabled(False)
        self._vis_coord_label = None
        self._interactive_canvas = None
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet(ss_dim_label())
        self._validation_label.hide()
        self._pending_section_title = None

        s = self._current_set
        if not s:
            return

        desc = self._scene_description(s['name'])

        # Set header
        hdr, hdr_layout = _make_info_card()
        add_editor_card_title(hdr_layout, self.t("label_scene_name"), "fa6s.object-group", desc)
        hdr_layout.addWidget(self._validation_label)

        hdr_inner = QWidget()
        hdr_inner.setStyleSheet(ss_transparent())
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(*Insets.NONE)
        hdr_grid.setColumnStretch(0, 1)
        hdr_grid.setColumnStretch(1, 1)

        # Scene name (editable)
        name_w, name_l = _field_shell(self.t("label_scene_name"))
        e_name = QLineEdit()
        e_name.setText(s['name'])
        _style_entry(e_name, h=Size.LARGE_CONTROL, font=_make_font("Consolas", 16, bold=True))
        _style_accent_entry(e_name)
        name_l.addWidget(e_name)
        self._fields['_set_name'] = e_name
        e_name.textChanged.connect(self._apply_fields)
        hdr_grid.addWidget(name_w, 0, 0)

        # Description (read-only)
        desc_w, desc_l = _field_shell(self.t("label_description"))
        lbl3 = QLabel(desc)
        lbl3.setWordWrap(True)
        lbl3.setMinimumWidth(0)
        lbl3.setFont(_make_font("Segoe UI", 15, bold=True))
        lbl3.setStyleSheet(ss_main_label())
        lbl3.setContentsMargins(*Insets.GRID_TITLE)
        desc_l.addWidget(lbl3)
        hdr_grid.addWidget(desc_w, 0, 1)

        hdr_layout.addWidget(hdr_inner)
        self._editor_layout.addWidget(hdr)

        # Stats
        self._add_section(self.t("section_statistics"))
        stats_panel, sp_layout = _make_info_card()
        self._apply_pending_section_title(sp_layout)

        sg = QWidget()
        sg.setStyleSheet(ss_transparent())
        sg_grid = QGridLayout(sg)
        sg_grid.setContentsMargins(*Insets.NONE)

        collisions = s['collisions']
        unique_types = set(str(c.get('type', 0)) for c in collisions)

        stats = [
            (self.t("stats_types_used"), ", ".join(sorted(unique_types)) if unique_types else self.t("stats_types_none")),
        ]
        for i, (label, value) in enumerate(stats):
            fw, fl = _field_shell(label)
            vl = _value_label(value, size=20)
            fl.addWidget(vl)
            sg_grid.addWidget(fw, 0, i)
            sg_grid.setColumnStretch(i, 1)

        sp_layout.addWidget(sg)
        self._editor_layout.addWidget(stats_panel)

        # Collision name breakdown
        if collisions:
            self._add_section(self.t("section_coll_names"))
            names_panel, np_layout = _make_info_card()
            self._apply_pending_section_title(np_layout)

            name_counts = {}
            for c in collisions:
                n = c.get('name', '') or self.t("coll_unnamed")
                name_counts[n] = name_counts.get(n, 0) + 1

            for n, count in sorted(name_counts.items()):
                row_w = QWidget()
                row_w.setStyleSheet(ss_transparent())
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(0, 1, 0, 1)
                rl.setSpacing(Size.GAP)
                nl = QLabel(n)
                nl.setFont(_make_font("Consolas", 12))
                nl.setStyleSheet(ss_main_label())
                rl.addWidget(nl)
                rl.addStretch()
                np_layout.addWidget(row_w)

            self._editor_layout.addWidget(names_panel)

        # Visual map for this set
        if collisions:
            self._add_section(self.t("section_visual_layout"))
            self._build_visual_map(collisions)

        # Special analysis for character select
        if s['name'] == ui_text("ui_info_ccscenebattleselectchar"):
            self._add_section(self.t("section_css_analysis"))
            self._build_css_analysis()

        # Bottom spacer
        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)

    def _build_visual_map(self, collisions):
        self._build_interactive_map(collisions, None)

    def _build_css_analysis(self):
        """Build character select screen analysis."""
        analysis = analyze_char_select(self._sets)
        if not analysis:
            self._pending_section_title = None
            return

        panel, p_layout = _make_info_card()
        self._apply_pending_section_title(p_layout)

        inner = QWidget()
        inner.setStyleSheet(ss_transparent())
        ig = QGridLayout(inner)
        ig.setContentsMargins(*Insets.NONE)

        # Stats
        stats = [
            (self.t("css_face_icon_slots"), str(analysis['face_icon_count'])),
            (self.t("css_grid_rows"), str(analysis['row_count'])),
            (self.t("css_typical_size"), f"{analysis['typical_size'][0]}x{analysis['typical_size'][1]}"),
        ]
        for i, (label, value) in enumerate(stats):
            fw, fl = _field_shell(label)
            vl = _value_label(value, size=20)
            fl.addWidget(vl)
            ig.addWidget(fw, 0, i)
            ig.setColumnStretch(i, 1)

        # Row breakdown
        row_info = QWidget()
        row_info.setStyleSheet(ss_transparent())
        ri_layout = QVBoxLayout(row_info)
        ri_layout.setContentsMargins(8, 8, 8, 0)
        ri_layout.setSpacing(1)
        for y_val in analysis['y_values']:
            row_colls = analysis['rows'][y_val]
            rl = QLabel(ui_text("ui_info_row_y_value_value_slots_x_value_value", p0=y_val, p1=len(row_colls), p2=row_colls[0]['x'], p3=row_colls[-1]['x'] + row_colls[-1]['w']))
            rl.setFont(_make_font("Consolas", 11))
            rl.setStyleSheet(ss_field_label())
            ri_layout.addWidget(rl)
        ig.addWidget(row_info, 1, 0, 1, 3)

        p_layout.addWidget(inner)
        self._editor_layout.addWidget(panel)

    # Authored geometry workspace

    def _build_interactive_map(self, collisions, selected_coll):
        panel, layout = _make_info_card()
        add_editor_card_title(layout, self.t('info_workspace'), 'fa6s.vector-square')
        tools = QWidget()
        tool_grid = configure_layout(QGridLayout(tools), LayoutRole.GRID)
        tool_index = 0
        for key, callback in (('info_fit', lambda: self._interactive_canvas.fit()),
                              ('info_undo_drag', self._undo_geometry),
                              ('info_redo_drag', self._redo_geometry)):
            button = configure_button(QPushButton(self.t(key)), height=Size.COMPACT_CONTROL)
            button.clicked.connect(callback)
            tool_grid.addWidget(button, tool_index // 2, tool_index % 2)
            tool_grid.setColumnStretch(tool_index % 2, 1)
            tool_index += 1
            if key == 'info_undo_drag': button.setProperty('designAction', 'undo')
            if key == 'info_redo_drag': button.setProperty('designAction', 'redo')
            if key == 'info_undo_drag': self._undo_btn = button
            if key == 'info_redo_drag': self._redo_btn = button
        layout.addWidget(tools)
        options = EditorActionRow()
        compare = configure_button(QPushButton(self.t('info_compare')), height=Size.COMPACT_CONTROL)
        compare.setCheckable(True)
        compare.setChecked(True)
        # Checked captions use the common bold state; reserve their measured width.
        compare.setMinimumWidth(QFontMetrics(ui_font(TypeSize.BODY, QFont.Weight.Bold)).horizontalAdvance(compare.text())
                                + 2 * Padding.BUTTON_X)
        compare.toggled.connect(lambda value: self._set_canvas_option('show_original', value))
        options.content_layout.addWidget(compare)
        snap = QComboBox()
        configure_input(snap)
        for value in (1, 5, 10):
            snap.addItem(self.t('info_snap', value=value), value)
        snap.currentIndexChanged.connect(lambda _: self._set_canvas_option('snap', snap.currentData()))
        snap.setToolTip(self.t('info_snap_hint'))
        options.content_layout.addWidget(snap)
        options.content_layout.addStretch()
        layout.addWidget(options)
        self._interactive_canvas = _InteractiveCollisionCanvas()
        self._interactive_canvas.setToolTip(self.t('info_canvas_help'))
        self._interactive_canvas.set_data(collisions, selected_coll, self._original_collisions.get(id(selected_coll)))
        if self._view_state:
            self._interactive_canvas.restore_view(self._view_state)
        self._interactive_canvas.can_edit = self._apply_fields
        self._interactive_canvas.fields_changed.connect(self._on_canvas_drag)
        self._interactive_canvas.selection_requested.connect(self._select_collision)
        self._interactive_canvas.gesture_finished.connect(self._remember_geometry)
        self._interactive_canvas.cursor_changed.connect(self._show_cursor)
        layout.addWidget(self._interactive_canvas)
        self._vis_coord_label = QLabel(self.t('info_canvas_help'))
        self._vis_coord_label.setFont(ui_font(TypeSize.HINT))
        self._vis_coord_label.setStyleSheet(ss_dim_label())
        self._vis_coord_label.setWordWrap(True)
        layout.addWidget(self._vis_coord_label)
        self._editor_layout.addWidget(panel)
        self._refresh_history_buttons()

    def _set_canvas_option(self, name, value):
        setattr(self._interactive_canvas, name, value)
        self._interactive_canvas.update()

    def _show_cursor(self, x, y, hits):
        if self._current_coll is not None:
            name = self._current_coll['name']
            group = [c for c in self._current_set['collisions'] if c['name'] == name]
            index = next((i for i, c in enumerate(group) if hit_score(c, x, y) >= 0), -1)
            result = self.t('info_group_hit', name=name, index=index)
        else:
            result = ', '.join(f"#{i} {self._current_set['collisions'][i]['name']}" for i in hits) or self.t('info_no_hit')
        self._vis_coord_label.setText(self.t('info_cursor_hits', x=x, y=y, hits=result))

    def _remember_geometry(self, coll, before):
        keys = ('type', *GEOMETRY_FIELDS)
        if any(coll[k] != before[k] for k in keys):
            self._geometry_undo.append((coll, {k: before[k] for k in keys}, {k: coll[k] for k in keys}))
            self._geometry_redo.clear()
        self._refresh_history_buttons()

    def _refresh_history_buttons(self):
        self._undo_btn.setEnabled(bool(self._geometry_undo))
        self._redo_btn.setEnabled(bool(self._geometry_redo))

    def _prune_geometry_history(self):
        valid = {id(c) for scene in self._sets for c in scene['collisions']}
        self._original_collisions = {key: value for key, value in self._original_collisions.items() if key in valid}
        self._geometry_undo[:] = [item for item in self._geometry_undo if id(item[0]) in valid]
        self._geometry_redo[:] = [item for item in self._geometry_redo if id(item[0]) in valid]

    def _history_geometry(self, source, destination, index):
        if not source or not self._apply_fields():
            return
        item = source.pop()
        coll = item[0]
        scene = next((s for s in self._sets if identity_index(s['collisions'], coll) >= 0), None)
        if scene is None:
            self._refresh_history_buttons()
            return
        destination.append(item)
        coll.update(item[index])
        # Clear the old form before navigating, so it cannot overwrite the undo.
        self._fields = {}
        if self._current_set is not scene:
            self._select_set(scene)
        self._select_collision(coll)
        self._mark_dirty()

    def _undo_geometry(self):
        self._history_geometry(self._geometry_undo, self._geometry_redo, 1)

    def _redo_geometry(self):
        self._history_geometry(self._geometry_redo, self._geometry_undo, 2)

    def _restore_original(self):
        coll = self._current_coll
        original = self._original_collisions.get(id(coll))
        if coll is None or original is None or not self._apply_fields():
            return
        before = copy.deepcopy(coll)
        coll.update({k: original[k] for k in ('type', *GEOMETRY_FIELDS)})
        self._remember_geometry(coll, before)
        self._on_canvas_drag()
        if 'type' in self._fields:
            self._fields = {}
            self._select_collision(coll)

    def _on_canvas_drag(self):
        self._mark_dirty()
        for key in GEOMETRY_FIELDS:
            if key in self._fields:
                edit = self._fields[key]
                edit.blockSignals(True)
                edit.setText(str(self._current_coll[key]))
                edit.blockSignals(False)
        self._update_computed_labels()

    def _update_computed_labels(self):
        coll = self._current_coll
        if coll is None or not self._computed_labels:
            return
        if coll['type'] == 1:
            x, y, radius = circle(coll)
            value = self.t('info_circle_geometry', x=x, y=y, radius=radius)
        elif coll['type'] in (0, 2):
            value = ' \u2192 '.join(f'({x}, {y})' for x, y in vertices(coll))
        else:
            value = self.t('info_unknown_shape')
        self._computed_labels['geometry'].setText(value)
        self._offset_panel.setEnabled(coll['type'] == 2 or coll['type'] not in (0, 1, 2))
        self._interactive_canvas.update()

    def _update_coll_list_labels(self):
        if self._current_set is None or self._current_coll is None:
            return
        idx = identity_index(self._current_set['collisions'], self._current_coll)
        if 0 <= idx < self._coll_tab_widget.count():
            self._coll_tab_widget.setTabText(idx, self._coll_tab_label(idx, self._current_coll))

    def _on_form_change(self):
        if self._apply_fields():
            self._update_computed_labels()

    def _build_collision_editor(self, coll):
        _clear_layout(self._editor_layout)
        self._fields, self._computed_labels = {}, {}
        self._interactive_canvas = None
        header, hl = _make_info_card()
        add_editor_card_title(hl, self.t('info_identity'), 'fa6s.object-group')
        scene_name = QLineEdit(self._current_set['name'])
        configure_input(scene_name)
        scene_name.setToolTip(self.t('info_scene_hint'))
        self._fields['_set_name'] = scene_name
        hl.addWidget(scene_name)
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet(ss_dim_label())
        self._validation_label.setVisible(False)
        hl.addWidget(self._validation_label)
        identity = QWidget()
        grid = configure_layout(QGridLayout(identity), LayoutRole.GRID)
        choices = [(i, self.t(f'info_shape_{i}')) for i in (0, 1, 2)]
        type_edit = EditorValueCombo(choices, coll['type'])
        names = sorted({c['name'] for s in self._sets for c in s['collisions']})
        name_edit = EditorValueCombo([(name, name) for name in names], coll['name'])
        self._fields.update(type=type_edit, name=name_edit)
        for column, (label, widget, hint) in enumerate(((self.t('info_type_label'), type_edit, self.t('info_type_hint')),
                                                       (self.t('label_coll_name'), name_edit, self.t('info_name_hint')))):
            frame, fl = _field_shell(label)
            widget.setToolTip(hint)
            fl.addWidget(widget)
            grid.addWidget(frame, 0, column)
            grid.setColumnStretch(column, 1)
        hl.addWidget(identity)
        self._editor_layout.addWidget(header)
        self._build_interactive_map(self._current_set['collisions'], coll)
        for title, keys in (('section_pos_size', ('x', 'y', 'w', 'h')),
                            ('info_corner_offsets', ('rtoX', 'rtoY', 'lboX', 'lboY'))):
            panel, layout = _make_info_card()
            add_editor_card_title(layout, self.t(title), 'fa6s.vector-square')
            content = QWidget()
            grid = configure_layout(QGridLayout(content), LayoutRole.GRID)
            for i, key in enumerate(keys):
                hint = self.t('info_hint_' + key)
                field, fl = _field_shell(self.t('info_field_' + key), hint)
                edit = configure_input(QLineEdit(str(coll[key])))
                edit.setToolTip(hint)
                fl.addWidget(IntegerStepper(edit, I32_MIN, I32_MAX))
                self._fields[key] = edit
                grid.addWidget(field, i // 2, i % 2)
                grid.setColumnStretch(i % 2, 1)
            layout.addWidget(content)
            self._editor_layout.addWidget(panel)
            if title == 'info_corner_offsets': self._offset_panel = panel
        panel, layout = _make_info_card()
        add_editor_card_title(layout, self.t('info_geometry'), 'fa6s.ruler-combined')
        label = QLabel()
        label.setFont(mono_font(TypeSize.CODE))
        label.setStyleSheet(ss_main_label())
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        self._computed_labels['geometry'] = label
        self._editor_layout.addWidget(panel)
        for widget in self._fields.values():
            signal = widget.editTextChanged if isinstance(widget, EditorValueCombo) else widget.textChanged
            signal.connect(self._on_form_change)
        self._update_computed_labels()

    # Add / Duplicate / Delete

    def _add_new_set(self):
        if self._raw_data is None:
            return
        if not self._apply_fields():
            return
        new_set = {
            'name': 'ccNewScene',
            'collisions': [make_default_collision()],
        }
        self._sets.append(new_set)
        self._mark_dirty()
        self._populate_set_list()
        self._select_set(new_set)

    def _delete_set(self):
        if self._raw_data is None or not self._current_set:
            return
        if len(self._sets) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("msg_cannot_delete_last_scene"))
            return
        if not self._apply_fields():
            return
        name = self._current_set['name']
        reply = QMessageBox.question(self, self.t("dlg_title_confirm_delete"),
                                     self.t("msg_confirm_delete_scene", name=name),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        self._sets.pop(identity_index(self._sets, self._current_set))
        self._prune_geometry_history()
        self._current_set = None
        self._current_coll = None
        self._mark_dirty()
        self._populate_set_list()

    def _add_collision(self):
        if not self._current_set:
            return
        if not self._apply_fields():
            return
        coll = make_default_collision()

        # Smart defaults: copy name from last collision in set
        if self._current_set['collisions']:
            last = self._current_set['collisions'][-1]
            coll['name'] = last.get('name', 'NewCollision')
            coll['type'] = last['type']
            # Position below the last one
            coll['x'] = last.get('x', 0)
            coll['y'] = max(I32_MIN, min(I32_MAX, last['y'] + last['h'] + 6))
            coll['w'] = last.get('w', 100)
            coll['h'] = last.get('h', 50)
            coll['rtoX'] = last.get('rtoX', 10)
            coll['rtoY'] = last.get('rtoY', -10)
            coll['lboX'] = last.get('lboX', -10)
            coll['lboY'] = last.get('lboY', 10)

        self._current_set['collisions'].append(coll)
        self._mark_dirty()
        self._populate_coll_list()
        self._select_collision(coll)

    def _duplicate_collision(self):
        if not self._current_set or not self._current_coll:
            return
        if not self._apply_fields():
            return
        coll = copy.deepcopy(self._current_coll)
        # Offset slightly
        coll['x'] = min(I32_MAX, coll['x'] + 10)
        coll['y'] = min(I32_MAX, coll['y'] + 10)
        self._current_set['collisions'].append(coll)
        self._mark_dirty()
        self._populate_coll_list()
        self._select_collision(coll)

    def _delete_collision(self):
        if not self._current_set or not self._current_coll:
            return
        if not self._apply_fields():
            return
        colls = self._current_set['collisions']
        if len(colls) <= 0:
            return
        idx = identity_index(colls, self._current_coll)
        cname = self._current_coll.get('name', '')
        reply = QMessageBox.question(self, self.t("dlg_title_confirm_delete"),
                                     self.t("msg_confirm_delete_coll", idx=idx, name=cname),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        colls.pop(idx)
        self._prune_geometry_history()
        self._current_coll = None
        self._mark_dirty()
        self._populate_coll_list()
        if colls:
            self._select_collision(colls[min(idx, len(colls) - 1)])
        else:
            self._build_set_overview()

    # Helpers

    def _add_section(self, title):
        self._pending_section_title = title

    def _apply_pending_section_title(self, layout):
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        if section_title:
            layout.setSpacing(max(layout.spacing(), 8))
            add_editor_card_title(layout, section_title, "fa6s.object-group")
