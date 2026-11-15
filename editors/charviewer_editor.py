"""CharViewer gallery editor: file-backed choices and native lens inspection."""
import copy
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, QEvent
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QVBoxLayout,
    QHBoxLayout, QFileDialog, QMessageBox, QScrollArea, QSizePolicy,
    QTabWidget, QSlider,
)
from core.design_tokens import LayoutRole, Size
from core.style_helpers import (
    make_editor_field_shell, make_editor_grid_card, make_empty_state,
    ss_bg_dark, ss_transparent, ss_dim_label, ss_input_validation, ss_slider, ss_tab_widget,
)
from core.ui.editor_widgets import (
    EditorActionRow, EditorListRow, EditorSeparator, EditorSidebar, EditorToolbar,
    EditorFilterCombo, configure_button, configure_file_label, configure_input,
    configure_layout, configure_scrollarea, configure_search, configure_tabs,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, install_file_actions, refresh_file_actions
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper
from core.ui.message_preview import MessagePreview, message_lookup
from core.ui.angle_comparison import AngleComparison
from core.ui.vector_comparison import VectorComparison
from core.editor_file_state import set_file_label
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.charviewer_tools import (
    INTEGER_RANGES, ANIMATION_KEYS, MESSAGE_KEYS, LIST_KEYS, parse_field,
    data_root, viewer_index, field_choices, clamp_fov, camera_offset,
)
from parsers.charviewer_parser import (
    parse_charviewer_xfbin, save_charviewer_xfbin, make_default_entry, _FLOAT_KEYS,
)


def _part_names():
    return {i: ui_text('ui_charviewer_all_none' if i == 0 else f'ui_charviewer_part_{i}') for i in range(9)}


def _dlc_names(entries):
    # Only names already shipped in Arrow Forge or values present in this file.
    names = {0: ui_text('ui_charviewer_base_game')}
    for i in range(12):
        names[10000 + i] = ui_text(f'ui_charviewer_dlc_{i}')
    return {v: f'{v} \u2014 {names.get(v, ui_text("hit_custom"))}'
            for v in sorted(set(names) | {e['dlc_id'] for e in entries})}


def _unlock_names(entries):
    # Native flag conversion is known; full unlock requirements are not.
    names = {1: ui_text('cv_unlock_flag', mask='0x01'),
             2: ui_text('cv_unlock_flag', mask='0x40'),
             3: ui_text('ui_charviewer_3_dlc_unlock'),
             4: ui_text('cv_unlock_flag', mask='0x20')}
    return {v: f'{v} \u2014 {names.get(v, ui_text("cv_unlock_other"))}'
            for v in sorted(set(names) | {0, 5, 6} | {e['unlock_condition'] for e in entries})}


class CharViewerEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or ui_text
        self._embedded = embedded
        self._filepath = self._raw = None
        self._version = 1000
        self._entries = []
        self._originals = {}
        self._dirty = self._loading_detail = False
        self._current_idx = -1
        self._entry_buttons = []
        self._visible_indices = []
        self._detail_widgets = {}
        self._form_grids = []
        self._filter_text = ''
        self._index = {}
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=self._do_save)
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        toolbar = EditorToolbar()
        self._btn_open = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._btn_open.setProperty('designAction', 'open')
        self._btn_open.clicked.connect(self._on_open)
        self._btn_save = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save.setEnabled(False)
        self._lbl_file = configure_file_label(QLabel(ui_text('xfa_no_file')))
        toolbar.content_layout.addWidget(self._btn_open)
        toolbar.content_layout.addWidget(self._btn_save)
        toolbar.content_layout.addWidget(self._lbl_file, 1)
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        main = QWidget()
        body = configure_layout(QHBoxLayout(main), LayoutRole.ROOT)
        body.addWidget(self._build_sidebar())
        body.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._content = QWidget()
        self._content.installEventFilter(self)
        self._editor_layout = configure_layout(QVBoxLayout(self._content), LayoutRole.PAGE)
        body.addWidget(self._content, 1)
        root.addWidget(main, 1)
        self._show_placeholder(ui_text('ui_charviewer_open_a_charviewerparam_bin_xfbin_file_to_begin_editing'))
        self.setStyleSheet(ss_bg_dark())

    def _build_sidebar(self):
        sidebar = EditorSidebar()
        layout = sidebar.content_layout
        self._search_box = configure_search(QLineEdit())
        self._search_box.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_box)
        self._part_filter = EditorFilterCombo()
        self._part_filter.addItem(ui_text('ui_charviewer_part_3d_shop'), None)
        for value, text in _part_names().items():
            self._part_filter.addItem(text, value)
        self._part_filter.currentIndexChanged.connect(self._rebuild_list)
        layout.addWidget(self._part_filter)
        self._dlc_filter = EditorFilterCombo()
        self._dlc_filter.addItem(ui_text('ui_charviewer_dlc_id'), None)
        self._dlc_filter.currentIndexChanged.connect(self._rebuild_list)
        layout.addWidget(self._dlc_filter)
        actions = EditorActionRow()
        for attr, key, action, callback in (
            ('_btn_add', 'btn_new', 'new', self._on_add),
            ('_btn_dup', 'btn_duplicate', 'duplicate', self._on_duplicate),
            ('_btn_del', 'btn_delete', 'delete', self._on_delete),
        ):
            button = configure_button(QPushButton(ui_text(key)), height=Size.COMPACT_CONTROL, danger=action == 'delete')
            button.setProperty('designAction', action)
            button.setEnabled(False)
            button.clicked.connect(callback)
            setattr(self, attr, button)
            actions.content_layout.addWidget(button, 1)
        layout.addWidget(actions)
        self._list_scroll = configure_scrollarea(QScrollArea(), transparent=True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        self._list_layout = configure_layout(QVBoxLayout(container), LayoutRole.LIST)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(container)
        layout.addWidget(self._list_scroll, 1)
        return sidebar

    def _clear_editor(self):
        self._detail_widgets = {}
        self._form_grids = []
        self._applied_columns = None
        self._tabs = None
        self._lens = None
        self._position_plot = None
        while self._editor_layout.count():
            item = self._editor_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._validation_label = None

    def _show_placeholder(self, text):
        self._clear_editor()
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._content,
            title=ui_text('no_file_loaded') if self._raw is None else ui_text('ui_dictionaryparam_select_an_entry_to_edit'),
            text=text, icon_name='fa6s.eye'), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _character_name(self, e):
        code = e['chara_code']
        key = f'char_{code}'
        text = self._t(key)
        return code if text == key else text

    def _rebuild_list(self, *_):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        query = self._search_box.text().casefold()
        self._filter_text = query
        self._entry_buttons, self._visible_indices = [], []
        for i, e in enumerate(self._entries):
            if self._part_filter.currentData() is not None and e['part'] != self._part_filter.currentData():
                continue
            if self._dlc_filter.currentData() is not None and e['dlc_id'] != self._dlc_filter.currentData():
                continue
            haystack = ' '.join((e['char_viewer_id'], e['viewer_id'], e['chara_code'],
                                 e['model_code'], self._character_name(e))).casefold()
            if query not in haystack:
                continue
            button = EditorListRow()
            button.set_texts(self._character_name(e) or e['char_viewer_id'],
                             f'{e["char_viewer_id"]} \u2014 {e["viewer_id"]}', title_limit=27, subtitle_limit=30)
            button.set_selected(i == self._current_idx)
            button.clicked.connect(lambda _, index=i: self._select_entry(index))
            self._list_layout.insertWidget(self._list_layout.count() - 1, button)
            self._entry_buttons.append((button, i))
            self._visible_indices.append(i)

    def _on_filter_changed(self):
        self._rebuild_list()

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._apply_current_entry(mark_dirty=False):
            return False
        self._current_idx = idx
        for button, i in self._entry_buttons:
            button.set_selected(i == idx)
            if i == idx:
                self._list_scroll.ensureWidgetVisible(button)
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self._build_editor(self._entries[idx])
        return True

    def _add_tab(self, title):
        scroll = configure_scrollarea(QScrollArea())
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = configure_layout(QVBoxLayout(container), LayoutRole.PAGE)
        scroll.setWidget(container)
        self._tabs.addTab(scroll, title)
        return layout

    def _card(self, page, title, icon='fa6s.sliders', hint=''):
        card, grid = make_editor_grid_card(title=title, icon_name=icon)
        page.addWidget(card)
        fields = []
        label = None
        if hint:
            label = QLabel(hint)
            label.setWordWrap(True)
            label.setStyleSheet(ss_dim_label())
            grid.addWidget(label, 0, 0, 1, 3)
        self._form_grids.append((grid, fields, label))
        return grid

    def _field(self, grid, key, label, *, options=None, hint=''):
        value = self._form_entry[key]
        choices = options
        if choices is None and key not in INTEGER_RANGES and key not in _FLOAT_KEYS:
            rows = [e for e in self._entries if e['viewer_id'] == self._form_entry['viewer_id']] if key in ANIMATION_KEYS else self._entries
            choices = field_choices(rows, key, self._index)
        if choices is not None:
            iterable = choices.items() if isinstance(choices, dict) else choices
            widget = EditorValueCombo(iterable, value)
        else:
            widget = configure_input(QLineEdit(), monospace=True)
            widget.setText(repr(value) if key in _FLOAT_KEYS else str(value))
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        widget.setAccessibleName(label)
        widget.setProperty('charViewerField', key)
        self._detail_widgets[key] = widget
        self._initial_text[key] = self._text(widget)
        help_text = hint or ui_text('cv_reference_help' if key not in INTEGER_RANGES and key not in _FLOAT_KEYS else 'cv_number_help')
        if key in INTEGER_RANGES:
            low, high = INTEGER_RANGES[key]
            help_text += '\n' + ui_text('cv_storage_range', low=low, high=high)
        widget.setToolTip(help_text)
        shell, body, _, _ = make_editor_field_shell(label)
        control = widget
        if key in INTEGER_RANGES and options is None:
            control = IntegerStepper(widget, *INTEGER_RANGES[key])
        body.addWidget(control)
        if key in MESSAGE_KEYS:
            edit = widget.lineEdit() if isinstance(widget, QComboBox) else widget
            body.addWidget(MessagePreview(edit, message_lookup(self)))
        for owner, fields, _ in self._form_grids:
            if owner is grid:
                fields.append(shell)
                break
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._save_current_entry)
            if key in ('part', 'dlc_id'):
                widget.activated.connect(self._refresh_filters)
                widget.lineEdit().editingFinished.connect(self._refresh_filters)
        else:
            widget.textChanged.connect(self._save_current_entry)
        return widget

    @staticmethod
    def _text(widget):
        return widget.value_text() if isinstance(widget, EditorValueCombo) else widget.text()

    def _build_editor(self, entry):
        from parsers.charviewer_parser import _STR_FIELDS, _NUM_FIELDS
        self._loading_detail = True
        old_tab = self._tabs.currentIndex() if self._tabs is not None else 0
        self._clear_editor()
        self._form_entry = copy.deepcopy(entry)
        self._initial_text = {}
        self._field_offsets = {key: off for off, key in _STR_FIELDS}
        self._field_offsets.update({key: off for off, key, _ in _NUM_FIELDS})
        self._root = data_root(self._filepath, load_settings().get('game_files_dir', ''))
        self._index, self._asset_path = viewer_index(self._root, entry['viewer_id'])
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet(ss_dim_label())
        self._validation_label.hide()
        self._editor_layout.addWidget(self._validation_label)
        self._tabs = configure_tabs(QTabWidget())
        self._tabs.setStyleSheet(ss_tab_widget())
        self._editor_layout.addWidget(self._tabs, 1)

        identity = self._add_tab(ui_text('skill_section_identity'))
        grid = self._card(identity, ui_text('cv_gallery_entry'), 'fa6s.id-card')
        for key, label in (
            ('char_viewer_id', 'ui_charviewer_char_viewer_id'),
            ('chara_code', 'ui_charviewer_character_code'), ('model_code', 'ui_charviewer_model_code'),
            ('viewer_id', 'ui_charviewer_viewer_id'), ('custom_list_title', 'ui_charviewer_custom_list_title'),
        ):
            options = None
            if key in ('chara_code', 'model_code'):
                options = []
                for value, _ in field_choices(self._entries, key):
                    name = self._t(f'char_{value}')
                    options.append((value, f'{value} \u2014 {name}' if name != f'char_{value}' else value))
            if key == 'viewer_id' and self._root:
                options = sorted({p.stem for p in (self._root / 'spc_viewer').glob('*.xfbin')}
                                 | {e['viewer_id'] for e in self._entries if e['viewer_id']})
                options = [(v, v) for v in options]
            self._field(grid, key, ui_text(label), options=options)
        grid = self._card(identity, ui_text('cv_gallery_order'), 'fa6s.list')
        self._field(grid, 'part', ui_text('ui_charviewer_part_3d_shop'), options=_part_names())
        for key in ('menu1_index', 'menu2_index'):
            self._field(grid, key, ui_text('cv_' + key), hint=ui_text('cv_' + key + '_help'))
        identity.addStretch()

        poses = self._add_tab(ui_text('cv_poses'))
        grid = self._card(poses, ui_text('cv_idle'), 'fa6s.person-running', ui_text('cv_pose_help'))
        for key, label in (('face_anim', 'ui_charviewer_face_animation'),
                           ('idle_anim1', 'ui_charviewer_idle_animation_1'), ('idle_anim2', 'ui_charviewer_idle_animation_2')):
            self._field(grid, key, ui_text(label))
        self._asset_label = QLabel()
        self._asset_label.setWordWrap(True)
        self._asset_label.setStyleSheet(ss_dim_label())
        poses.addWidget(self._asset_label)
        self._refresh_asset_label()
        reload_resources = configure_button(QPushButton(ui_text('cv_reload_resources')))
        reload_resources.clicked.connect(self._reload_resources)
        poses.addWidget(reload_resources)
        self._detail_widgets['viewer_id'].lineEdit().editingFinished.connect(self._reload_resources)
        for i in range(1, 6):
            grid = self._card(poses, ui_text('cv_pose', index=i), 'fa6s.person-running')
            for phase in ('st', 'lp', 'ed'):
                self._field(grid, f'pose{i}_{phase}', ui_text('cv_phase_' + phase))
        poses.addStretch()

        camera = self._add_tab(ui_text('ui_charviewer_camera'))
        grid = self._card(camera, ui_text('cv_camera_position'), 'fa6s.camera', ui_text('cv_camera_help'))
        for key in ('cam_pos_z', 'cam_zoom', 'cam_y', 'cam_unk', 'cam_anchor_y', 'cam_anchor_x', 'cam_rot_y_min', 'cam_rot_z'):
            self._field(grid, key, ui_text('cv_' + key), hint=ui_text('cv_camera_help'))
        position_card, position_grid = make_editor_grid_card(title=ui_text('cv_camera_offset'),
            icon_name='fa6s.camera', subtitle=ui_text('cv_camera_offset_help'))
        self._position_plot = VectorComparison(ui_text('cv_depth_axis'), ui_text('cv_height_axis'),
            ui_text('cv_original'), ui_text('cv_current'), ui_text('cv_offset_unavailable'))
        position_grid.addWidget(self._position_plot, 0, 0)
        camera.addWidget(position_card)
        grid = self._card(camera, ui_text('cv_lens'), 'fa6s.camera', ui_text('cv_lens_help'))
        for key in ('cam_zoom_in', 'cam_zoom_out'):
            self._field(grid, key, ui_text('cv_' + key), hint=ui_text('cv_lens_help'))
        lens_card, lens_grid = make_editor_grid_card(title=ui_text('cv_lens_probe'), icon_name='fa6s.camera')
        camera.addWidget(lens_card)
        self._probe = configure_input(QLineEdit('45'), monospace=True)
        self._probe.setAccessibleName(ui_text('cv_requested_fov'))
        self._probe.setToolTip(ui_text('cv_probe_help'))
        shell, box, _, _ = make_editor_field_shell(ui_text('cv_requested_fov'), ui_text('cv_probe_help'))
        box.addWidget(self._probe)
        self._probe_slider = QSlider(Qt.Orientation.Horizontal)
        self._probe_slider.setRange(0, 1000)
        self._probe_slider.setAccessibleName(ui_text('cv_requested_fov'))
        self._probe_slider.setStyleSheet(ss_slider())
        self._probe_slider.setToolTip(ui_text('cv_probe_slider_help'))
        box.addWidget(self._probe_slider)
        lens_grid.addWidget(shell, 0, 0)
        self._lens = AngleComparison(ui_text('cv_original'), ui_text('cv_current'), ui_text('cv_angle_unavailable'))
        lens_grid.addWidget(self._lens, 1, 0)
        restore = configure_button(QPushButton(ui_text('cv_restore_camera')))
        restore.clicked.connect(self._restore_camera)
        camera.addWidget(restore)
        restore.hide()
        camera.addStretch()
        self._probe.textChanged.connect(self._refresh_lens)
        self._probe_slider.valueChanged.connect(self._probe_slide)

        shop = self._add_tab(ui_text('ui_charviewer_dlc_shop'))
        grid = self._card(shop, ui_text('cv_availability'), 'fa6s.store', ui_text('cv_unlock_help'))
        self._field(grid, 'dlc_id', ui_text('ui_charviewer_dlc_id'), options=_dlc_names(self._entries))
        self._field(grid, 'unlock_condition', ui_text('ui_charviewer_unlock_condition'), options=_unlock_names(self._entries))
        self._field(grid, 'shop_price', ui_text('ui_charviewer_shop_price'))
        self._field(grid, 'patch_id', ui_text('ui_charviewer_patch'), options=[(v, str(v)) for v in sorted({e['patch_id'] for e in self._entries})])
        grid = self._card(shop, ui_text('cv_gallery_art'), 'fa6s.image')
        for key, label in (('custom_card', 'ui_charviewer_custom_card_id'), ('icon_path', 'ui_charviewer_custom_icon_path'),
                           ('medal_img', 'ui_charviewer_medal_preview_image'), ('extra_costume', 'ui_charviewer_extra_costume_title_id'),
                           ('card_detail', 'ui_charviewer_card_detail_id')):
            self._field(grid, key, ui_text(label))
        shop.addStretch()

        references = self._add_tab(ui_text('cv_references'))
        grid = self._card(references, ui_text('cv_linked_resources'), 'fa6s.link', ui_text('cv_list_help'))
        for key in LIST_KEYS:
            self._field(grid, key, ui_text('cv_field_' + key), hint=ui_text('cv_list_help'))
        self._field(grid, 'resource_138', ui_text('cv_resource_138'), hint=ui_text('cv_resource_138_help'))
        references.addStretch()
        self._tabs.setCurrentIndex(min(old_tab, self._tabs.count() - 1))
        self._loading_detail = False
        self._reflow()
        self._refresh_lens()
        QTimer.singleShot(0, self._reflow)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reflow)

    def eventFilter(self, watched, event):
        if watched is getattr(self, '_content', None) and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def _reflow(self):
        if self._tabs is None:
            return
        width = self._tabs.width()
        columns = 1 if width < Size.COMPACT_BREAKPOINT else 2 if width < 1080 else 3
        if columns == self._applied_columns:
            return
        self._applied_columns = columns
        for grid, fields, hint in self._form_grids:
            # Keep controls alive: focus, partial text and native undo survive.
            if hint:
                grid.addWidget(hint, 0, 0, 1, columns)
            for i, shell in enumerate(fields):
                row, col = divmod(i, columns)
                grid.addWidget(shell, row + (1 if hint else 0), col)
            for col in range(3):
                grid.setColumnStretch(col, 1 if col < columns else 0)
                grid.setColumnMinimumWidth(col, 0)

    def _save_current_entry(self, *_):
        self._apply_current_entry(mark_dirty=True)

    def _apply_current_entry(self, *, mark_dirty):
        if self._current_idx < 0 or self._loading_detail or not self._detail_widgets:
            return True
        values, invalid = {}, []
        if mark_dirty:
            self._mark_dirty()
        for key, widget in self._detail_widgets.items():
            text = self._text(widget)
            try:
                # Untouched non-finite values and float32 payloads stay exact.
                values[key] = self._form_entry[key] if text == self._initial_text[key] else parse_field(key, text)
                stylesheet = ss_input_validation(False)
            except (ValueError, OverflowError, UnicodeError):
                invalid.append(key)
                stylesheet = ss_input_validation(True)
            if widget.styleSheet() != stylesheet:
                widget.setStyleSheet(stylesheet)
        if self._validation_label is not None:
            self._validation_label.setText(ui_text('cv_invalid', fields=', '.join(invalid)) if invalid else '')
            self._validation_label.setVisible(bool(invalid))
        if invalid:
            self._refresh_lens(invalid=True)
            return False
        entry = self._entries[self._current_idx]
        entry.update(values)
        self._refresh_lens()
        if mark_dirty:
            for button, i in self._entry_buttons:
                if i == self._current_idx:
                    button.set_texts(self._character_name(entry) or entry['char_viewer_id'],
                                     f'{entry["char_viewer_id"]} \u2014 {entry["viewer_id"]}', title_limit=27, subtitle_limit=30)
        return True

    def _refresh_asset_label(self):
        available = bool(self._index)
        self._asset_label.setText(ui_text('cv_assets_found' if available else 'cv_assets_missing', path=self._asset_path))

    def _reload_resources(self, *_):
        if self._loading_detail or not self._detail_widgets:
            return
        viewer = self._text(self._detail_widgets['viewer_id'])
        self._index, self._asset_path = viewer_index(self._root, viewer)
        rows = [e for e in self._entries if e['viewer_id'] == viewer]
        for key in (*ANIMATION_KEYS, 'resource_138'):
            widget = self._detail_widgets[key]
            text = widget.value_text()
            with QSignalBlocker(widget), QSignalBlocker(widget.lineEdit()):
                widget.clear()
                for value, caption in field_choices(rows, key, self._index):
                    widget.addItem(caption, value)
                index = widget.findData(text)
                widget.setCurrentIndex(index)
                if index < 0:
                    widget.setEditText(text)
        self._refresh_asset_label()

    def _refresh_lens(self, *_, invalid=False):
        if self._lens is None or self._loading_detail:
            return
        original = self._originals.get(id(self._entries[self._current_idx]), self._form_entry)
        try:
            fields = {key: parse_field(key, self._text(self._detail_widgets[key]))
                      for key in ('cam_zoom', 'cam_unk', 'cam_pos_z', 'cam_y')}
            self._position_plot.set_vectors(camera_offset(original), camera_offset(fields))
        except (ValueError, OverflowError):
            self._position_plot.set_vectors(None, None)
        try:
            requested = parse_field('cam_zoom_in', self._probe.text())
            low = parse_field('cam_zoom_in', self._text(self._detail_widgets['cam_zoom_in']))
            high = parse_field('cam_zoom_out', self._text(self._detail_widgets['cam_zoom_out']))
            current = clamp_fov(requested, low, high)
            before = clamp_fov(requested, original['cam_zoom_in'], original['cam_zoom_out'])
            self._lens.set_angles(before, current)
            self._probe.setStyleSheet(ss_input_validation(False))
            self._probe_slider.setEnabled(low < high)
            with QSignalBlocker(self._probe_slider):
                self._probe_slider.setValue(round(max(0, min(1, (requested - low) / (high - low))) * 1000) if low < high else 0)
        except (ValueError, OverflowError):
            self._lens.set_angles(None, None)
            self._probe.setStyleSheet(ss_input_validation(True))
            self._probe_slider.setEnabled(False)

    def _probe_slide(self, value):
        try:
            low = parse_field('cam_zoom_in', self._text(self._detail_widgets['cam_zoom_in']))
            high = parse_field('cam_zoom_out', self._text(self._detail_widgets['cam_zoom_out']))
            self._probe.setText(repr(low + (high - low) * value / 1000))
        except (ValueError, OverflowError):
            pass

    def _restore_camera(self):
        original = self._originals.get(id(self._entries[self._current_idx]))
        if original is None:
            return
        if all(self._text(self._detail_widgets[key]) == repr(original[key]) for key in _FLOAT_KEYS):
            return
        self._loading_detail = True
        for key in _FLOAT_KEYS:
            self._detail_widgets[key].setText(repr(original[key]))
        self._loading_detail = False
        self._save_current_entry()

    def _mark_dirty(self):
        self._dirty = True
        if self._filepath:
            set_file_label(self._lbl_file, self._filepath, dirty=True)

    def _refresh_filters(self, *_):
        for combo, key, caption, names in (
            (self._part_filter, 'part', 'ui_charviewer_part_3d_shop', _part_names()),
            (self._dlc_filter, 'dlc_id', 'ui_charviewer_dlc_id', _dlc_names(self._entries)),
        ):
            selected = combo.currentData()
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem(ui_text(caption), None)
                for value in sorted({e[key] for e in self._entries}):
                    combo.addItem(names.get(value, str(value)), value)
                combo.setCurrentIndex(max(0, combo.findData(selected)))
        reset = getattr(self._search_box, '_design_filter_reset', None)
        if reset:
            reset.refresh()
        self._rebuild_list()

    def _load_path(self, path):
        if not self._apply_current_entry(mark_dirty=False):
            return False
        try:
            raw, version, entries = parse_charviewer_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_charviewer_load_error'), str(exc))
            return False
        self._filepath, self._raw, self._version, self._entries = str(path), raw, version, entries
        self._originals = {id(e): copy.deepcopy(e) for e in entries}
        self._dirty = False
        self._current_idx = -1
        self._detail_widgets = {}
        set_file_label(self._lbl_file, str(path))
        with QSignalBlocker(self._search_box), QSignalBlocker(self._part_filter), QSignalBlocker(self._dlc_filter):
            self._search_box.clear()
            self._part_filter.setCurrentIndex(0)
            self._dlc_filter.setCurrentIndex(0)
        self._refresh_filters()
        self._btn_save.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_dup.setEnabled(bool(entries))
        self._btn_del.setEnabled(bool(entries))
        refresh_file_actions(self, loaded=True)
        self._rebuild_list()
        if entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text('ui_assist_no_entries_found'))
        return True

    def _on_open(self):
        if not self._apply_current_entry(mark_dirty=False):
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_charviewer_open_charviewerparam_bin_xfbin'),
            game_files_dialog_dir(self._filepath or '', 'CharViewerParam.bin.xfbin'),
            'XFBIN Files (*.xfbin);;All Files (*)')
        if path:
            create_backup_on_open(path)
            self._load_path(path)

    def _on_save(self):
        if self._filepath:
            return self._do_save(self._filepath)
        return False

    def _do_save(self, path):
        if self._raw is None or not self._apply_current_entry(mark_dirty=False):
            return False
        try:
            save_charviewer_xfbin(str(path), self._raw, self._version, self._entries)
            raw, version, saved = parse_charviewer_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('ui_assist_save_error'), str(exc))
            return False
        # Keep object identity for the original comparison, while rebasing offsets
        # after structural saves. Do not rebuild controls or erase text undo.
        for entry, stored in zip(self._entries, saved):
            entry['_offset'] = stored['_offset']
            entry['_null_fields'] = stored['_null_fields']
        self._raw, self._version = raw, version
        self._dirty = False
        commit_save_path(self, str(path))
        set_file_label(self._lbl_file, str(path))
        return True

    def _unique_id(self, source, key):
        used = {e[key] for e in self._entries}
        suffix, candidate = 1, source
        while candidate in used:
            candidate = f'{source}_{suffix}'
            suffix += 1
        return candidate

    def _reveal_entry(self, idx):
        # Structural actions must reveal the created row even with active filters.
        reset = getattr(self._search_box, '_design_filter_reset', None)
        if reset:
            reset.clear()
        else:
            self._search_box.clear()
            self._part_filter.setCurrentIndex(0)
            self._dlc_filter.setCurrentIndex(0)
        self._refresh_filters()
        self._select_entry(idx)

    def _on_add(self):
        if not self._apply_current_entry(mark_dirty=False) or self._raw is None:
            return
        entry = make_default_entry(len(self._entries))
        entry['char_viewer_id'] = self._unique_id(entry['char_viewer_id'], 'char_viewer_id')
        self._entries.append(entry)
        self._originals[id(entry)] = copy.deepcopy(entry)
        self._mark_dirty()
        self._reveal_entry(len(self._entries) - 1)

    def _on_duplicate(self):
        if self._current_idx < 0 or not self._apply_current_entry(mark_dirty=False):
            return
        entry = copy.deepcopy(self._entries[self._current_idx])
        entry.pop('_offset', None)
        entry['char_viewer_id'] = self._unique_id(entry['char_viewer_id'] + '_copy', 'char_viewer_id')
        # viewer_id is an actual asset name; duplication must keep the reference.
        idx = self._current_idx + 1
        self._entries.insert(idx, entry)
        self._originals[id(entry)] = copy.deepcopy(entry)
        self._mark_dirty()
        self._reveal_entry(idx)

    def _on_delete(self):
        if self._current_idx < 0 or not self._apply_current_entry(mark_dirty=False):
            return
        entry = self._entries[self._current_idx]
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
                ui_text('ui_charviewer_delete_entry_value', p0=entry['char_viewer_id']),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        index = self._current_idx
        self._originals.pop(id(entry), None)
        del self._entries[index]
        self._current_idx = -1
        self._detail_widgets = {}
        self._mark_dirty()
        self._rebuild_list()
        if self._visible_indices:
            self._select_entry(min(self._visible_indices, key=lambda i: abs(i - index)))
        else:
            self._btn_dup.setEnabled(False)
            self._btn_del.setEnabled(False)
            self._show_placeholder(ui_text('ui_dictionaryparam_select_an_entry_to_edit'))
