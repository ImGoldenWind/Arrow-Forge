"""Visual NFH bitmap and inline icon authoring workspace."""
import copy
import os

from PIL import Image
from PyQt6.QtCore import Qt, QTimer, QRect, QSignalBlocker, QSortFilterProxyModel, QThreadPool
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLayout, QBoxLayout,
    QLineEdit, QLabel, QPushButton, QScrollArea, QComboBox, QTabWidget,
    QCheckBox, QFontComboBox, QFileDialog, QMessageBox, QSizePolicy,
)

from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.themes import P
from core.style_helpers import (
    ss_bg_dark, ss_dim_label, ss_check, ss_tab_widget,
    make_editor_card, make_editor_field_shell, make_empty_state, add_editor_card_title,
)
from core.ui.editor_widgets import (
    EditorToolbar, EditorSidebar, EditorSeparator, EditorActionRow, EditorFilterCombo,
    configure_layout, configure_button, configure_input, configure_search,
    configure_tabs, configure_file_label, configure_scrollarea, configure_card,
    fit_scroll_page,
)
from core.ui.editor_chrome import install_editor_chrome, EditorSidebarPane
from core.ui.editor_actions import install_file_actions, commit_save_path, editor_path, refresh_file_actions
from core.ui.record_list import RecordListModel, EditorRecordList
from core.ui.image_preview import ImagePreview, ImageLoadSignals, ImageLoadJob
from core.ui.value_combo import EditorValueCombo
from core.ui.number_input import IntegerStepper, FloatStepper, SliderInput
from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings
from core.translations import ui_text, current_language
from core.font_tools import (
    icon_string, icon_reference_choices, glyph_at,
    icon_resource_variants, icon_crop, glyph_control_values, glyph_record_data,
    icon_control_values, icon_record_data,
)
from core.gallery_tools import data_root, load_image
from parsers.font_xfbin_parser import (
    FontRecord, load_font_xfbin, save_font_xfbin, set_nfh_metadata,
    atlas_png_bytes, crop_nfh_glyph_image, replace_nfh_glyph_image,
    replace_nfh_atlas_same_size,
)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class FontEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t, self._embedded = t, embedded
        self._doc = self._original = None
        self._current_idx = None
        self._fields, self._grids = {}, []
        self._validation = None
        self._catalog_rows = []
        self._preview_scrolls = []
        self._dirty = self._loading_detail = self._syncing_selection = False
        self._image_pool = QThreadPool(self)
        self._image_pool.setMaxThreadCount(1)
        self._image_signals = ImageLoadSignals(self)
        self._image_signals.finished.connect(self._icon_loaded)
        self._image_running = False
        self._image_pending = None
        self._image_token = 0
        self._icon_key = None
        self._icon_image = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._reflow)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._refresh_previews)
        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setStyleSheet(ss_bg_dark())
        top = EditorToolbar()
        self._btn_open = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._btn_open.setProperty('designAction', 'open')
        self._btn_open.clicked.connect(self._do_open)
        self._btn_save = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._do_save)
        self._file_label = configure_file_label(QLabel(ui_text('no_file_loaded')))
        for widget in (self._btn_open, self._btn_save, self._file_label):
            top.content_layout.addWidget(widget)
        top.content_layout.addStretch()
        root.addWidget(top)
        root.addWidget(EditorSeparator(accent=True))
        body = configure_layout(QHBoxLayout(), LayoutRole.ROOT)
        sidebar = EditorSidebar(width=220)
        self._search = configure_search(QLineEdit())
        self._search.setToolTip(ui_text('font_search_hint'))
        self._search.textChanged.connect(self._filter_list)
        sidebar.content_layout.addWidget(self._search)
        self._bitmap_filter = EditorFilterCombo()
        self._bitmap_filter.setToolTip(ui_text('font_bitmap_filter'))
        self._bitmap_filter.setAccessibleName(ui_text('font_bitmap_filter'))
        self._bitmap_filter.addItem(ui_text('font_bitmap_filter'), None)
        self._bitmap_filter.addItem(ui_text('font_with_bitmap'), 'bitmap')
        self._bitmap_filter.addItem(ui_text('ui_font_atlas_section_no_bitmap'), 'empty')
        self._bitmap_filter.currentIndexChanged.connect(self._filter_list)
        sidebar.content_layout.addWidget(self._bitmap_filter)
        self._model = RecordListModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterRole(Qt.ItemDataRole.DisplayRole)
        self._entry_scroll = EditorRecordList(self._proxy, self._describe_row)
        self._entry_scroll.selectionModel().currentChanged.connect(self._catalog_changed)
        sidebar.content_layout.addWidget(self._entry_scroll, 1)
        body.addWidget(sidebar)
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_widget = QWidget()
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_widget), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        body.addWidget(self._editor_scroll, 1)
        preview_sidebar = EditorSidebar(width=Size.SIDEBAR_DEFAULT)
        self._preview_tabs = configure_tabs(QTabWidget())
        self._preview_tabs.setStyleSheet(ss_tab_widget())
        preview_sidebar.content_layout.addWidget(self._preview_tabs, 1)
        self._preview_pane = EditorSidebarPane(preview_sidebar, self, edge='right', label='preview')
        self._preview_pane.hide()
        body.addWidget(self._preview_pane)
        root.addLayout(body, 1)
        self._show_placeholder(ui_text('ui_font_open_file_to_begin'))

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(title=ui_text('no_file_loaded'), text=text),
                                      0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_font_open_title'),
            game_files_dialog_dir(target_patterns=('*.fnt.xfbin', 'xfgame_cmn_*.xfbin', 'iconfontParam.bin.xfbin')),
            ui_text('ui_font_file_filter'))
        if path:
            self._load(path)

    def _load(self, path):
        if not self._apply_current_record(show_errors=True):
            return False
        try:
            doc = load_font_xfbin(path)
            create_backup_on_open(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_load_error', error=exc))
            return False
        self._preview_timer.stop()
        self._image_token += 1
        self._image_pending = None
        self._icon_key = None
        self._icon_image = None
        self._doc, self._original = doc, copy.deepcopy(doc)
        self._root = data_root(path, load_settings().get('game_files_dir', ''))
        self._current_idx = None
        self._fields = {}
        self._dirty = False
        self._btn_save.setEnabled(False)
        set_file_label(self._file_label, path)
        with QSignalBlocker(self._search), QSignalBlocker(self._bitmap_filter):
            self._search.clear()
            self._bitmap_filter.setCurrentIndex(0)
        self._bitmap_filter.setVisible(doc.kind == 'nfh_font')
        self._populate_list()
        refresh_file_actions(self, loaded=True)
        if self._entry_count():
            self._select_entry(0)
        else:
            self._build_editor(None)
        return True

    def _do_save(self, target_path=None):
        if self._doc is None or not self._apply_current_record(show_errors=True):
            return False
        path = target_path or editor_path(self)
        try:
            save_font_xfbin(self._doc, path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))
            return False
        commit_save_path(self, path)
        self._dirty = False
        self._btn_save.setEnabled(False)
        set_file_label(self._file_label, path)
        return True

    _save_file = _do_save

    def _entry_count(self):
        return len(self._doc.glyph_records if self._doc.kind == 'nfh_font' else self._doc.icon_records) if self._doc else 0

    def _row(self, idx):
        if self._doc.kind == 'nfh_font':
            r = self._doc.glyph_records[idx]
            title = r.glyph_char if r.glyph_char and not r.glyph_char.isspace() else ui_text(
                'ui_font_glyph_space_title' if r.glyph_code == 32 else 'ui_font_glyph_nonprinting_title')
            subtitle = f'U+{r.glyph_code:04X} · {r.atlas_width}×{r.atlas_height} · ({r.atlas_x}, {r.atlas_y})'
            tag = 'bitmap' if r.has_atlas_rect else 'empty'
            return (f'{idx} {title} {subtitle} {r.glyph_code}', idx, title, subtitle, tag)
        title = icon_string(self._doc, idx, 0) or ui_text('ui_font_unresolved')
        subtitle = icon_string(self._doc, idx, 2) or ui_text('ui_font_unresolved')
        return (f'{idx} {title} {subtitle} {icon_string(self._doc, idx, 1)}', idx, title, subtitle, 'icon')

    def _populate_list(self):
        self._catalog_rows = [self._row(i) for i in range(self._entry_count())]
        self._filter_list()

    def _describe_row(self, index):
        row = index.data(Qt.ItemDataRole.UserRole)
        return row[2], row[3], row[0]

    def _filter_list(self, *_):
        import re
        query = re.escape(self._search.text().strip())
        tag = self._bitmap_filter.currentData() if self._doc and self._doc.kind == 'nfh_font' else None
        # A derived tag lives only in this filter string, never in a visible title.
        self._syncing_selection = True
        rows = self._catalog_rows
        if tag:
            rows = [r for r in rows if r[4] == tag]
        self._model.reset_rows(rows)
        self._proxy.setFilterRegularExpression(query)
        self._sync_selection()
        self._syncing_selection = False

    def _sync_selection(self):
        for row in range(self._model.rowCount()):
            if self._model.rows[row][1] == self._current_idx:
                self._entry_scroll.setCurrentIndex(self._proxy.mapFromSource(self._model.index(row, 0)))
                return
        self._entry_scroll.setCurrentIndex(self._proxy.index(-1, 0))

    def _catalog_changed(self, current, previous):
        if self._syncing_selection or not current.isValid():
            return
        if not self._select_entry(current.data(Qt.ItemDataRole.UserRole)[1]):
            self._syncing_selection = True
            self._sync_selection()
            self._syncing_selection = False

    def _select_entry(self, idx):
        if not 0 <= idx < self._entry_count() or not self._apply_current_record(show_errors=True):
            return False
        self._current_idx = idx
        self._syncing_selection = True
        self._sync_selection()
        self._syncing_selection = False
        self._build_editor(idx)
        return True

    def _card(self, title, hint='', *, target=None):
        card, layout = make_editor_card()
        configure_card(card, vertical_policy=QSizePolicy.Policy.Maximum)
        add_editor_card_title(layout, title, 'fa6s.font')
        if hint:
            label = QLabel(hint)
            label.setWordWrap(True)
            label.setFont(ui_font(TypeSize.HINT))
            label.setStyleSheet(ss_dim_label())
            layout.addWidget(label)
        (target if target is not None else self._editor_layout).addWidget(card)
        return layout

    def _preview_tab(self, title):
        scroll = configure_scrollarea(QScrollArea())
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        layout = configure_layout(QVBoxLayout(page), LayoutRole.FIELD)
        scroll.setWidget(page)
        self._preview_tabs.addTab(scroll, title)
        self._preview_scrolls.append(scroll)
        return layout

    def _grid(self, layout):
        grid = configure_layout(QGridLayout(), LayoutRole.GRID)
        layout.addLayout(grid)
        self._grids.append((grid, []))
        return grid

    def _field(self, grid, key, caption, widget, tooltip=''):
        frame, layout, label, _ = make_editor_field_shell(caption)
        label.setVisible(bool(caption))
        label.setBuddy(widget.lineEdit() if isinstance(widget, EditorValueCombo) else widget)
        widget.setMinimumWidth(0)
        widget.setAccessibleName(caption)
        widget.setToolTip(tooltip)
        frame.setToolTip(tooltip)
        layout.addWidget(widget)
        self._grids[-1][1].append(frame)
        grid.addWidget(frame, grid.count(), 0)
        if key:
            self._fields[key] = widget
        return widget

    def _number(self, grid, key, caption, value, minimum=0, maximum=0xffffffff, *, floating=False, step=0.1, tooltip=''):
        edit = configure_input(QLineEdit(str(value)), monospace=True)
        stepper = FloatStepper(edit, step) if floating else IntegerStepper(edit, minimum, maximum)
        self._field(grid, key, caption, stepper, tooltip)
        self._fields[key] = edit
        edit.setAccessibleName(caption)
        edit.setToolTip(tooltip)
        edit.textChanged.connect(self._on_field_changed)
        return edit

    def _text(self, grid, key, caption, value, tooltip=''):
        edit = configure_input(QLineEdit(value))
        edit.textChanged.connect(self._on_field_changed)
        return self._field(grid, key, caption, edit, tooltip)

    def _button(self, text, slot, *, accent=False):
        button = configure_button(QPushButton(ui_text(text)), accent=accent)
        button.clicked.connect(slot)
        return button

    def _build_editor(self, idx):
        self._preview_timer.stop()
        self._image_token += 1
        self._image_pending = None
        self._icon_key = None
        self._icon_image = None
        self._loading_detail = True
        preview_tab = self._preview_tabs.currentIndex()
        while self._preview_tabs.count():
            page = self._preview_tabs.widget(0)
            self._preview_tabs.removeTab(0)
            page.deleteLater()
        self._preview_scrolls = []
        _clear_layout(self._editor_layout)
        self._fields, self._grids = {}, []
        self._validation = None
        if self._doc.kind == 'nfh_font':
            self._build_nfh(idx)
        elif idx is not None:
            self._build_icon(idx)
        else:
            self._show_placeholder(ui_text('font_no_records'))
        self._editor_layout.addStretch()
        self._preview_pane.setVisible(self._preview_tabs.count() > 0)
        if preview_tab >= 0:
            self._preview_tabs.setCurrentIndex(min(preview_tab, self._preview_tabs.count()-1))
        self._loading_detail = False
        self._reflow()
        self._refresh_previews()

    def _build_nfh(self, idx):
        if idx is not None:
            r = self._doc.glyph_records[idx]
            layout = self._card(f'{ui_text("ui_font_selected_glyph")} · U+{r.glyph_code:04X}')
            grid = self._grid(layout)
            for key, caption, value, maximum in (
                ('x', 'X', r.atlas_x, 65535), ('y', 'Y', r.atlas_y, 65535),
                ('w', ui_text('font_bitmap_width'), r.atlas_width, 255),
                ('h', ui_text('font_bitmap_height'), r.atlas_height, 255)):
                self._number(grid, key, caption, value, maximum=maximum, tooltip=ui_text('font_rect_hint'))
            self._number(grid, 'advance', ui_text('font_advance'), glyph_control_values(r)['advance'],
                         floating=True, step=1/64, tooltip=ui_text('font_advance_hint'))
            self._build_authoring(r, layout)
            actions = self._grid(layout)
            for key, callback in (('ui_font_export_png', self._export_glyph_png),
                                   ('ui_font_replace_glyph_png', self._replace_glyph_png)):
                self._field(actions, None, '', self._button(key, callback))
            self._build_validation(layout)

            previews = self._preview_tab(ui_text('font_tab_glyph'))
            preview_layout = self._card(ui_text('font_tab_glyph'), target=previews)
            self._comparison = configure_input(QComboBox(), monospace=False)
            self._comparison.setMinimumContentsLength(1)
            self._comparison.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            for key in ('current', 'original', 'split'):
                self._comparison.addItem(ui_text('font_compare_' + key), key)
            self._comparison.currentIndexChanged.connect(self._refresh_previews)
            preview_layout.addWidget(self._comparison)
            self._glyph_preview = ImagePreview(minimum_height=128, maximum_height=144, compact=True)
            self._glyph_preview.set_checkerboard(True)
            self._glyph_preview.set_smooth(False)
            preview_layout.addWidget(self._glyph_preview)
            self._glyph_status = QLabel()
            self._glyph_status.setWordWrap(True)
            self._glyph_status.setStyleSheet(ss_dim_label())
            preview_layout.addWidget(self._glyph_status)
            draft_layout = self._card(ui_text('font_replacement_preview'), target=previews)
            self._draft_preview = ImagePreview(minimum_height=128, maximum_height=144, compact=True)
            self._draft_preview.set_checkerboard(True)
            self._draft_preview.set_smooth(False)
            draft_layout.addWidget(self._draft_preview)
            previews.addStretch()

        layout = self._card(ui_text('ui_font_family'), ui_text('font_metadata_hint'))
        grid = self._grid(layout)
        self._text(grid, 'family', ui_text('ui_font_family'), self._doc.family)
        self._text(grid, 'style', ui_text('font_style'), self._doc.style)
        if idx is None:
            self._build_validation(layout)
        atlas_tab = self._preview_tab(ui_text('ui_font_atlas'))
        layout = self._card(ui_text('ui_font_atlas'), target=atlas_tab)
        self._atlas_preview = ImagePreview(minimum_height=180, maximum_height=320, compact=True)
        self._atlas_preview.setToolTip(ui_text('font_atlas_hint'))
        self._atlas_image = None
        self._atlas_outline = None
        self._atlas_preview.set_checkerboard(True)
        self._atlas_preview.set_smooth(False)
        self._atlas_preview.view.pixel_pick = True
        self._atlas_preview.view.pixel_clicked.connect(self._atlas_clicked)
        layout.addWidget(self._atlas_preview)
        self._atlas_status = QLabel()
        self._atlas_status.setWordWrap(True)
        self._atlas_status.setStyleSheet(ss_dim_label())
        layout.addWidget(self._atlas_status)
        for key, callback in (('ui_font_export_png', self._export_atlas_png),
                               ('ui_font_export_ntp3', self._export_atlas_ntp3),
                               ('ui_font_replace_same_size', self._replace_atlas)):
            layout.addWidget(self._button(key, callback))
        atlas_tab.addStretch()

    def _build_authoring(self, record, layout):
        layout.addWidget(EditorSeparator())
        grid = self._grid(layout)
        self._glyph_font_combo = configure_input(QFontComboBox(), monospace=False)
        self._glyph_font_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._glyph_font_combo.setMinimumContentsLength(1)
        self._glyph_font_combo.setToolTip(ui_text('font_author_hint'))
        self._field(grid, None, ui_text('ui_font_windows_font'), self._glyph_font_combo)
        self._glyph_replacement_edit = configure_input(QLineEdit(record.glyph_char), monospace=False)
        self._field(grid, None, ui_text('ui_font_replacement_text'), self._glyph_replacement_edit)
        self._glyph_size_slider = SliderInput(ui_text('font_author_size'), 1, 256, max(1, record.atlas_height or 32))
        self._glyph_size_spin = self._glyph_size_slider.input
        layout.addWidget(self._glyph_size_slider)
        self._glyph_bold_check = QCheckBox(ui_text('ui_font_bold'))
        self._glyph_italic_check = QCheckBox(ui_text('ui_font_italic'))
        checks = self._font_checks = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        for check in (self._glyph_bold_check, self._glyph_italic_check):
            check.setFont(ui_font(TypeSize.BODY))
            check.setStyleSheet(ss_check())
            check.toggled.connect(self._refresh_draft)
            checks.addWidget(check)
        checks.addStretch()
        layout.addLayout(checks)
        self._draw_apply = self._button('font_apply_replacement', self._apply_windows_font_to_glyph, accent=True)
        self._draw_apply.setToolTip(ui_text('font_author_hint'))
        layout.addWidget(self._draw_apply)
        for signal in (self._glyph_font_combo.currentFontChanged, self._glyph_replacement_edit.textChanged,
                       self._glyph_size_spin.valueChanged):
            signal.connect(self._refresh_draft)

    def _build_icon(self, idx):
        r = self._doc.icon_records[idx]
        values = icon_control_values(r)
        layout = self._card(ui_text('ui_font_selected_icon'))
        layout.parentWidget().setToolTip(ui_text('font_icon_hint'))
        grid = self._grid(layout)
        for field, key in enumerate(('font_icon_tag', 'font_icon_path', 'font_icon_chunk')):
            choices = icon_reference_choices(self._doc, idx, field)
            if field:
                choices.insert(0, (0, ui_text('font_inherit')))
            combo = EditorValueCombo(choices, r.fields[field])
            self._field(grid, f'field_{field}', ui_text(key), combo, ui_text('font_reference_hint'))
            combo.currentTextChanged.connect(self._on_field_changed)
        resolved = QLabel('\n'.join(icon_string(self._doc, idx, f) or '—' for f in (0, 1, 2)))
        resolved.setWordWrap(True)
        resolved.setMinimumWidth(0)
        resolved.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        resolved.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        resolved.setStyleSheet(ss_dim_label())
        layout.addWidget(resolved)
        grid = self._grid(layout)
        for field in range(3, 11):
            if field in (9, 10):
                check = QCheckBox()
                check.setFont(ui_font(TypeSize.BODY))
                check.setStyleSheet(ss_check())
                check.setChecked(bool(r.fields[field]))
                self._field(grid, f'field_{field}', ui_text(f'font_icon_field_{field}'), check,
                            ui_text('font_tint_hint' if field == 9 else 'font_restriction_hint'))
                check.toggled.connect(self._on_field_changed)
                continue
            floating = field in (7, 8)
            value = values[f'field_{field}']
            self._number(grid, f'field_{field}', ui_text(f'font_icon_field_{field}'), value,
                         -(1 << 31) if field < 7 else 0, (1 << 31)-1 if field < 7 else 0xffffffff,
                         floating=floating, tooltip=ui_text('font_icon_float_hint' if floating else 'font_icon_integer_hint'))
        self._build_validation(layout)
        preview = self._preview_tab(ui_text('font_tab_icon'))
        layout = self._card(ui_text('font_tab_icon'), target=preview)
        self._variant = configure_input(QComboBox(), monospace=False)
        self._variant.setMinimumContentsLength(1)
        self._variant.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._variant.setAccessibleName(ui_text('font_resource_variant'))
        self._variant.currentIndexChanged.connect(self._refresh_previews)
        layout.addWidget(self._variant)
        self._icon_preview = ImagePreview(minimum_height=192, maximum_height=320, compact=True)
        self._icon_preview.setToolTip(ui_text('font_icon_preview_hint'))
        self._icon_preview.set_checkerboard(True)
        self._icon_preview.set_smooth(False)
        layout.addWidget(self._icon_preview)
        self._icon_status = QLabel()
        self._icon_status.setWordWrap(True)
        self._icon_status.setMinimumWidth(0)
        self._icon_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._icon_status.setStyleSheet(ss_dim_label())
        layout.addWidget(self._icon_status)
        self._variant_reference = None
        preview.addStretch()

    def _build_validation(self, layout):
        self._validation = QLabel()
        self._validation.setWordWrap(True)
        self._validation.setStyleSheet(ss_dim_label())
        layout.addWidget(self._validation)
        layout.addWidget(self._button('font_apply_fields', lambda: self._apply_and_refresh(), accent=True))

    def _draft_data(self):
        idx = self._current_idx
        if idx is None:
            return None
        r = (self._doc.glyph_records if self._doc.kind == 'nfh_font' else self._doc.icon_records)[idx]
        if self._doc.kind == 'nfh_font':
            structured = glyph_record_data(self._doc, idx, {key: self._fields[key].text()
                                            for key in ('x', 'y', 'w', 'h', 'advance')})
        else:
            values = {}
            for field in range(11):
                widget = self._fields[f'field_{field}']
                if isinstance(widget, QCheckBox):
                    value = widget.isChecked()
                else:
                    value = widget.value_text() if isinstance(widget, EditorValueCombo) else widget.text()
                values[f'field_{field}'] = value
            structured = icon_record_data(r, values)
        return structured

    def _apply_current_record(self, show_errors=False):
        if self._doc is None or not self._fields:
            return True
        try:
            data = self._draft_data()
            record_changed = False
            # Validate both metadata fields before changing the document.
            if self._doc.kind == 'nfh_font':
                family, style = (self._fields[k].text() for k in ('family', 'style'))
                for text in (family, style):
                    if len(text.encode('ascii')) >= 32 or '\0' in text:
                        raise ValueError(ui_text('font_metadata_error'))
            if data is not None:
                r = (self._doc.glyph_records if self._doc.kind == 'nfh_font' else self._doc.icon_records)[self._current_idx]
                record_changed = data != r.data
                r.data[:] = data
                self._doc.payload[r.offset:r.offset + len(data)] = data
            if self._doc.kind == 'nfh_font' and (family, style) != (self._doc.family, self._doc.style):
                set_nfh_metadata(self._doc, family, style)
            self._sync_fields()
            if record_changed:
                self._refresh_catalog_record()
            return True
        except Exception as exc:
            if self._validation is not None:
                self._validation.setText(ui_text('ui_font_apply_error', error=exc))
            if show_errors:
                QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('ui_font_apply_error', error=exc))
            return False

    def _sync_fields(self):
        if self._current_idx is None:
            return
        r = (self._doc.glyph_records if self._doc.kind == 'nfh_font' else self._doc.icon_records)[self._current_idx]
        values = glyph_control_values(r) if self._doc.kind == 'nfh_font' else icon_control_values(r)
        for key, value in values.items():
            widget = self._fields[key]
            with QSignalBlocker(widget):
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, EditorValueCombo):
                    index = widget.findData(str(value))
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        widget.setCurrentIndex(-1)
                        widget.setEditText(str(value))
                elif widget.text() != str(value):
                    widget.setText(str(value))
        self._validation.clear()

    def _apply_and_refresh(self):
        if self._apply_current_record(show_errors=True):
            self._refresh_previews()

    def _refresh_catalog_record(self):
        if self._doc.kind == 'nfh_font':
            self._catalog_rows[self._current_idx] = self._row(self._current_idx)
        else:
            # A resource reference can also change subsequent inherited rows.
            self._catalog_rows = [self._row(i) for i in range(self._entry_count())]
        self._filter_list()

    def _on_field_changed(self, *_):
        if not self._loading_detail:
            self._mark_dirty()
            self._preview_timer.start()

    def _mark_dirty(self):
        self._dirty = True
        if self._doc:
            set_file_label(self._file_label, self._doc.path, dirty=True)
            self._btn_save.setEnabled(True)

    def _refresh_previews(self, *_):
        if self._loading_detail or self._doc is None:
            return
        # ImagePreview initially hides its view. Re-measure after the newly
        # visible pixel surface has invalidated Qt's layout caches.
        self._resize_timer.start()
        try:
            data = self._draft_data()
            if self._validation is not None:
                self._validation.clear()
        except Exception as exc:
            if self._validation is not None:
                self._validation.setText(ui_text('ui_font_apply_error', error=exc))
            return
        if self._doc.kind != 'nfh_font':
            self._refresh_icon(data)
            return
        atlas = self._doc.atlas
        if self._atlas_image is not atlas.pil_image:
            self._atlas_preview.set_image(atlas.pil_image, preserve_view=True)
            self._atlas_image = atlas.pil_image
            self._atlas_outline = None
        self._atlas_status.setText(ui_text('ui_font_atlas_info_value', width=atlas.width, height=atlas.height,
                                         fmt=atlas.pixel_format, size=len(atlas.data)) +
                                   ('\n' + atlas.edit_error if atlas.edit_error else ''))
        if data is None:
            return
        r = FontRecord(self._current_idx, 0, data)
        image = atlas.pil_image.crop((r.atlas_x, r.atlas_y, r.atlas_x+r.atlas_width, r.atlas_y+r.atlas_height)) if r.has_atlas_rect and atlas.pil_image else None
        original = crop_nfh_glyph_image(self._original, self._current_idx)
        mode = self._comparison.currentData()
        if mode == 'original':
            image = original
        elif mode == 'split' and image is not None and original is not None:
            board = Image.new('RGBA', (max(original.width, image.width), original.height + image.height + 4))
            board.paste(original, (0, 0))
            board.paste(image, (0, original.height + 4))
            image = board
        self._glyph_preview.set_image(image, preserve_view=True)
        self._glyph_status.setText(ui_text('font_no_bitmap') if image is None else '')
        self._glyph_status.setVisible(image is None)
        if self._atlas_outline is not None:
            self._atlas_preview.view.scene().removeItem(self._atlas_outline)
            self._atlas_outline = None
        if r.has_atlas_rect and atlas.pil_image:
            pen = QPen(QColor(P['accent']))
            pen.setCosmetic(True)
            item = self._atlas_preview.view.scene().addRect(r.atlas_x, r.atlas_y, r.atlas_width, r.atlas_height, pen)
            item.setZValue(1)
            self._atlas_outline = item
        self._refresh_draft()

    def _refresh_icon(self, data):
        draft = copy.copy(self._doc)
        draft.icon_records = list(self._doc.icon_records)
        record = copy.copy(draft.icon_records[self._current_idx])
        record.data = data
        draft.icon_records[self._current_idx] = record
        reference, name = (icon_string(draft, self._current_idx, f) for f in (1, 2))
        try:
            if reference != self._variant_reference:
                from core.movelist_text import LANGUAGES
                variants = icon_resource_variants(self._root, reference,
                                                  LANGUAGES.get(current_language(), 'eng'))
                with QSignalBlocker(self._variant):
                    self._variant.clear()
                    for path in variants:
                        self._variant.addItem(path, path)
                self._variant_reference = reference
            path = self._variant.currentData()
            self._variant.setVisible(self._variant.count() > 1)
            key = (path, name)
            if key != self._icon_key:
                self._image_token += 1
                self._icon_key = key
                self._icon_image = None
                self._icon_preview.set_image(None)
                if not path:
                    self._icon_status.setText(ui_text('font_icon_missing', path=reference))
                    return
                self._icon_status.setText(ui_text('loading'))
                self._image_pending = (self._image_token, self._root, path, name)
                self._start_icon_job()
            elif self._icon_image is not None:
                self._icon_preview.set_image(icon_crop(self._icon_image, data), preserve_view=True)
                self._icon_status.setText(path + ' · ' + name)
        except Exception as exc:
            self._icon_preview.set_image(None)
            self._icon_status.setText(ui_text('font_preview_error', error=exc))

    def _start_icon_job(self):
        if self._image_running or self._image_pending is None:
            return
        token, root, path, name = self._image_pending
        self._image_pending = None
        self._image_running = True
        self._image_pool.start(ImageLoadJob(self._image_signals, token, 'icon', root, path, name, None,
                                            loader=load_image))

    def _icon_loaded(self, token, kind, image, names, error):
        self._image_running = False
        if token == self._image_token and self._doc and self._doc.kind == 'iconfont_param':
            self._icon_image = image
            if error:
                self._icon_status.setText(ui_text('font_preview_error', error=error))
            else:
                self._refresh_previews()
        self._start_icon_job()

    def _refresh_draft(self, *_):
        if self._loading_detail or not self._doc or self._doc.kind != 'nfh_font' or self._current_idx is None:
            return
        self._resize_timer.start()
        try:
            r = FontRecord(self._current_idx, 0, self._draft_data())
            text = self._glyph_replacement_edit.text()
            enabled = bool(r.has_atlas_rect and text and self._doc.atlas.pil_image and not self._doc.atlas.edit_error)
            image = self._render_windows_font_glyph(text, r.atlas_width, r.atlas_height) if enabled else None
            self._draft_preview.set_image(image)
            self._draw_apply.setEnabled(enabled)
        except Exception:
            self._draw_apply.setEnabled(False)

    def _atlas_clicked(self, point):
        if not self._apply_current_record(show_errors=True):
            return
        idx = glyph_at(self._doc, point.x(), point.y())
        if idx is not None:
            self._select_entry(idx)
            self._entry_scroll.scrollTo(self._entry_scroll.currentIndex())

    def _restore_record(self):
        if self._current_idx is None:
            return
        records = self._doc.glyph_records if self._doc.kind == 'nfh_font' else self._doc.icon_records
        originals = self._original.glyph_records if self._doc.kind == 'nfh_font' else self._original.icon_records
        r, old = records[self._current_idx], originals[self._current_idx]
        r.data[:] = old.data
        self._doc.payload[r.offset:r.offset+len(r.data)] = r.data
        self._sync_fields()
        self._mark_dirty()
        self._refresh_catalog_record()
        self._refresh_previews()

    def _reflow(self):
        if self._doc and self._doc.kind == 'nfh_font' and self._current_idx is not None:
            margins = self._editor_layout.contentsMargins()
            card_margins = self._font_checks.parentWidget().layout().contentsMargins()
            available = (self._editor_scroll.viewport().width() - margins.left() - margins.right()
                         - card_margins.left() - card_margins.right())
            required = (self._glyph_bold_check.minimumSizeHint().width()
                        + self._glyph_italic_check.minimumSizeHint().width() + self._font_checks.spacing())
            self._font_checks.setDirection(QBoxLayout.Direction.LeftToRight if available >= required
                                           else QBoxLayout.Direction.TopToBottom)
        columns = 1 if self._editor_scroll.viewport().width() < 600 else 2
        for grid, frames in self._grids:
            while grid.count():
                grid.takeAt(0)
            for index, frame in enumerate(frames):
                grid.addWidget(frame, index // columns, index % columns)
            for col in range(2):
                grid.setColumnStretch(col, 1 if col < columns else 0)
        fit_scroll_page(self._editor_scroll)
        for scroll in self._preview_scrolls:
            fit_scroll_page(scroll)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()


    def _export_atlas_png(self):
        if self._doc is None or self._doc.atlas is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_png"),
            os.path.splitext(self._doc.path)[0] + ".png",
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(atlas_png_bytes(self._doc))
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _export_atlas_ntp3(self):
        if self._doc is None or self._doc.atlas is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_ntp3"),
            os.path.splitext(self._doc.path)[0] + ".nut",
            ui_text("ui_font_ntp3_filter"),
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self._doc.atlas.data)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _replace_atlas(self):
        if self._doc is None or self._doc.atlas is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_font_replace_same_size"),
            game_files_dialog_dir(os.path.dirname(self._doc.path)),
            ui_text("ui_font_ntp3_filter"),
        )
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            replace_nfh_atlas_same_size(self._doc, data)
            self._mark_dirty()
            self._refresh_previews()
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replace_error", error=exc))

    def _export_glyph_png(self):
        if self._doc is None or self._current_idx is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        crop = crop_nfh_glyph_image(self._doc, self._current_idx)
        if crop is None:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_font_export_glyph_png"),
            os.path.splitext(self._doc.path)[0] + f"_glyph_{self._current_idx}.png",
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            crop.save(path, "PNG")
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))

    def _replace_glyph_png(self):
        if self._doc is None or self._current_idx is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        record = self._doc.glyph_records[self._current_idx]
        if not record.has_atlas_rect:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_font_replace_glyph_png"),
            game_files_dialog_dir(os.path.dirname(self._doc.path)),
            ui_text("ui_font_png_filter"),
        )
        if not path:
            return
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
            replace_nfh_glyph_image(self._doc, self._current_idx, image)
            self._mark_dirty()
            self._refresh_previews()
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replace_glyph_error", error=exc))

    def _apply_windows_font_to_glyph(self):
        if self._doc is None or self._current_idx is None:
            return
        if not self._apply_current_record(show_errors=True):
            return
        record = self._doc.glyph_records[self._current_idx]
        if not record.has_atlas_rect:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_glyph_no_rect"))
            return
        text = self._glyph_replacement_edit.text() if self._glyph_replacement_edit is not None else ""
        if not text:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_replacement_empty"))
            return
        try:
            image = self._render_windows_font_glyph(text, record.atlas_width, record.atlas_height)
            replace_nfh_glyph_image(self._doc, self._current_idx, image)
            self._mark_dirty()
            self._refresh_previews()
        except Exception as exc:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_font_render_error", error=exc))

    def _render_windows_font_glyph(self, char: str, width: int, height: int) -> Image.Image:
        if self._glyph_font_combo is None or self._glyph_size_spin is None:
            raise ValueError(ui_text("ui_font_controls_not_ready"))
        qimage = QImage(width, height, QImage.Format.Format_RGBA8888)
        qimage.fill(Qt.GlobalColor.transparent)

        font = QFont(self._glyph_font_combo.currentFont())
        font.setPixelSize(self._glyph_size_spin.value())
        if self._glyph_bold_check is not None:
            font.setBold(self._glyph_bold_check.isChecked())
        if self._glyph_italic_check is not None:
            font.setItalic(self._glyph_italic_check.isChecked())

        painter = QPainter(qimage)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, char)
        painter.end()
        return self._qimage_to_pil(qimage)

    def _qimage_to_pil(self, image: QImage) -> Image.Image:
        qimage = image.convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = qimage.bits()
        ptr.setsize(qimage.bytesPerLine() * qimage.height())
        return Image.frombytes(
            "RGBA",
            (qimage.width(), qimage.height()),
            bytes(ptr),
            "raw",
            "RGBA",
            qimage.bytesPerLine(),
        )
