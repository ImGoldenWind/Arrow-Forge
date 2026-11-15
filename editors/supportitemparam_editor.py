from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
    ss_sidebar_btn,
    ss_transparent,
    ss_dim_label,
    ss_input_validation,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorListRow,
    EditorFilterCombo,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_field,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions
import copy
import math
import os
import struct

from PyQt6.QtCore import QEvent, QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from core.support_research import (
    effect_options, effect_name, target_options, identity_diagnostics,
    availability_options, visibility, row_description,
    packet_gate, menu_class,
)
from core.parameter_research import resolve_messages, support_value_label, support_value_hint
from parsers.supportitemparam_parser import (
    FLOAT_FIELDS,
    UINT_FIELDS,
    make_default_entry,
    parse_supportitemparam_xfbin,
    save_supportitemparam_xfbin,
)


_UINT32_MAX = 0xFFFFFFFF
_FLOAT_MIN = -3.4028234663852886e38
_FLOAT_MAX = 3.4028234663852886e38
_TEXT_KEYS = ("story_title_key", "story_hint_key", "campaign_title_key", "campaign_hint_key")
_UINT_KEYS = tuple(key for key, _offset in UINT_FIELDS)
_FLOAT_KEYS = tuple(key for key, _offset in FLOAT_FIELDS)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class SupportItemParamEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: key.format(**kw) if kw else key)
        self._embedded = embedded

        self._filepath: str | None = None
        self._raw_data: bytearray | None = None
        self._result: dict | None = None
        self._entries: list[dict] = []
        self._entry_buttons: list[tuple[QPushButton, int]] = []
        self._current_idx: int | None = None
        self._fields: dict[str, QLineEdit | QComboBox] = {}
        self._dirty = False
        self._loading_detail = False
        self._last_compact: bool | None = None
        self._active_grid_columns = 3
        self._message_cache = {}
        self._grids = {}
        self._last_columns = None
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_card_heights)

        self._uint_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self)
        self._float_validator = QRegularExpressionValidator(
            QRegularExpression(r"[-+]?(?:\d+\.?\d*|\.\d+)?(?:[eE][-+]?\d+)?"),
            self,
        )
        self._ascii_validator = QRegularExpressionValidator(QRegularExpression(r"[\x20-\x7E]{0,128}"), self)
        self._hex_validator = QRegularExpressionValidator(QRegularExpression(r"(?:[0-9A-Fa-f]{2}\s*)*"), self)

        self._build_ui()
        install_file_actions(self, self._btn_save, save_to=lambda path: self._do_save(target_path=path))
        install_editor_chrome(self)

    def _tr(self, key: str, fallback: str | None = None, **kwargs) -> str:
        value = self._t(key, **kwargs) if kwargs else self._t(key)
        return fallback if value == key and fallback is not None else value

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        top = EditorToolbar()
        top_layout = top.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._do_open)
        self._btn_open.setProperty("designAction", 'open')
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._btn_save.setEnabled(False)
        configure_button(self._btn_save, accent=True)
        self._btn_save.clicked.connect(self._do_save)
        top_layout.addWidget(self._btn_save)

        self._file_label = QLabel(self._tr("no_file_loaded", ui_text("no_file_loaded")))

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        sidebar = EditorSidebar(width=320)


        sidebar_layout = sidebar.content_layout


        self._search = QLineEdit()
        configure_search(self._search)
        self._search.textChanged.connect(self._filter_list)
        sidebar_layout.addWidget(self._search)

        self._effect_filter = EditorFilterCombo()
        self._effect_filter.addItem(ui_text('support_filter_effect'), None)
        for value, text in effect_options():
            self._effect_filter.addItem(text, value)
        self._visibility_filter = EditorFilterCombo()
        self._visibility_filter.addItem(ui_text('support_filter_visibility'), None)
        for value in ('both', 'campaign', 'hidden'):
            self._visibility_filter.addItem(ui_text('support_visibility_' + value), value)
        for combo in (self._effect_filter, self._visibility_filter):
            combo.currentIndexChanged.connect(self._filter_list)
            sidebar_layout.addWidget(combo)

        actions = EditorActionRow()

        actions_layout = actions.content_layout


        self._btn_add = self._make_action_button("btn_new", self._do_add)
        self._btn_add.setProperty("designAction", 'new')
        self._btn_dup = self._make_action_button("btn_duplicate", self._do_dup)
        self._btn_dup.setToolTip(ui_text('support_duplicate_hint'))
        self._btn_dup.setProperty("designAction", 'duplicate')
        self._btn_del = self._make_action_button("btn_delete", self._do_del, danger=True)
        self._btn_del.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._btn_add, 1)
        actions_layout.addWidget(self._btn_dup, 1)
        actions_layout.addWidget(self._btn_del, 1)
        sidebar_layout.addWidget(actions)

        self._entry_scroll = QScrollArea()


        self._entry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._entry_scroll, transparent=True)
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setMinimumWidth(0)
        self._entry_list_widget.setStyleSheet(ss_transparent())
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        configure_layout(self._entry_list_layout, LayoutRole.LIST)
        self._entry_list_layout.addStretch()
        self._no_matches = QLabel(ui_text('support_no_matches'))
        self._no_matches.setWordWrap(True)
        self._no_matches.setFont(ui_font(TypeSize.BODY))
        self._no_matches.setStyleSheet(ss_dim_label())
        self._entry_scroll.setWidget(self._entry_list_widget)
        sidebar_layout.addWidget(self._no_matches)
        self._no_matches.hide()
        sidebar_layout.addWidget(self._entry_scroll, 1)
        main_layout.addWidget(sidebar)

        divider = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()


        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._editor_scroll)
        self._editor_scroll.viewport().installEventFilter(self)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)
        main_layout.addWidget(self._editor_scroll, 1)

        self._show_placeholder(ui_text("ui_supportitemparam_open_file_to_begin_editing"))
        root.addWidget(main, 1)
        self._update_actions()

    def _make_action_button(self, key: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(self._tr(key, ui_text(key)))
        btn.setEnabled(False)
        configure_button(btn, danger=danger, height=Size.COMPACT_CONTROL)
        btn.clicked.connect(slot)
        return btn

    def _show_placeholder(self, text: str):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._grids = {}
        self._research_card = None
        card = make_empty_state(
            self._editor_widget,
            title=ui_text("ui_supportitemparam_no_entries") if self._raw_data is not None else ui_text("no_file_loaded"),
            text=text,
            icon_name="fa6s.folder-open",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _do_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_supportitemparam_open_title"),
            game_files_dialog_dir(target_patterns=("SupportItemParam.bin.xfbin", "SupportItemParam.xfbin")),
            ui_text("ui_supportitemparam_file_filter"),
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        try:
            raw, result = parse_supportitemparam_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        if self._dirty and QMessageBox.question(
            self, ui_text('dlg_title_warning'), ui_text('support_discard'),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Discard:
            return
        create_backup_on_open(path)

        self._filepath = path
        self._raw_data = raw
        self._result = result
        self._entries = result["entries"]
        self._current_idx = None
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._search.setText("")
        self._effect_filter.setCurrentIndex(0)
        self._visibility_filter.setCurrentIndex(0)
        self._message_cache.clear()
        set_file_label(self._file_label, path)
        self._populate_list()
        if self._entries:
            self._select_entry(0)
        else:
            self._show_placeholder(ui_text("ui_supportitemparam_no_entries"))
        self._update_actions()

    def _do_save(self, target_path=None):
        save_path = target_path or editor_path(self)
        if not save_path or self._raw_data is None or self._result is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        try:
            save_supportitemparam_xfbin(save_path, self._raw_data, self._result)
            with open(save_path, 'rb') as fh:
                self._raw_data = bytearray(fh.read())
            commit_save_path(self, save_path)
            self._dirty = False
            self._btn_save.setEnabled(False)
            set_file_label(self._file_label, save_path)
            QMessageBox.information(self, ui_text('dlg_title_success'), ui_text('msg_save_success', path=os.path.basename(save_path)))
        except Exception as exc:
            QMessageBox.critical(self, ui_text('dlg_title_error'), ui_text('msg_save_error', error=exc))

    def _clear_entry_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        self._entry_buttons = []

    def _populate_list(self):
        self._clear_entry_list()
        for idx, entry in enumerate(self._entries):
            btn = self._make_entry_button(idx, entry)
            self._entry_list_layout.insertWidget(self._entry_list_layout.count() - 1, btn)
            self._entry_buttons.append((btn, idx))
        self._filter_list()

    def _make_entry_button(self, idx: int, entry: dict) -> QPushButton:
        btn = EditorListRow()

        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


        layout = btn.content_layout


        title_text = self._entry_title(idx, entry)
        button_title = self._entry_button_title(idx, entry)
        subtitle_text = self._entry_subtitle(entry)
        button_subtitle = self._entry_button_subtitle(entry)
        title = btn.add_title(button_title)
        title.setProperty('supportFullText', button_title)
        title.installEventFilter(self)


        title.setToolTip(title_text)


        subtitle = btn.add_subtitle(button_subtitle, value_font=ui_font(TypeSize.CODE))
        subtitle.setProperty('supportFullText', button_subtitle)
        subtitle.installEventFilter(self)


        subtitle.setToolTip(subtitle_text)


        btn.clicked.connect(lambda checked=False, i=idx: self._select_entry(i))
        btn.setToolTip(title_text + '\n' + subtitle_text)
        return btn

    def _messages(self, *keys):
        keys = tuple(keys)
        if keys not in self._message_cache:
            self._message_cache[keys] = [text for text in resolve_messages(self._filepath, keys) if text]
        return self._message_cache[keys]

    def _item_name(self, entry):
        names = self._messages(entry.get('story_title_key', ''), entry.get('campaign_title_key', ''))
        return names[0] if names else ui_text('support_item_fallback', value=entry.get('support_id', 0))

    def _entry_title(self, idx: int, entry: dict) -> str:
        return self._item_name(entry)

    def _entry_button_title(self, idx: int, entry: dict) -> str:
        return self._item_name(entry)

    def _entry_subtitle(self, entry: dict) -> str:
        return ui_text('support_item_subtitle', value=entry.get('support_id', 0),
                       price=entry.get('price', 0), scope=ui_text('support_visibility_' + visibility(entry)))

    def _entry_button_subtitle(self, entry: dict) -> str:
        return self._entry_subtitle(entry)

    def _filter_list(self):
        query = self._search.text().lower().strip()
        visible = 0
        for btn, idx in self._entry_buttons:
            if idx >= len(self._entries):
                btn.setVisible(False)
                continue
            entry = self._entries[idx]
            haystack = " ".join(str(entry.get(key, "")) for key in (
                "support_id", "price", "tier_or_category", "display_order", "effect_type",
                "story_title_key", "story_hint_key", "campaign_title_key", "campaign_hint_key",
            )).lower()
            haystack += ' ' + ' '.join([self._item_name(entry),
                effect_name(entry.get('effect_type', 0)), effect_name(entry.get('effect_2_type', 0)),
                *self._messages(entry.get('story_hint_key', ''), entry.get('campaign_hint_key', ''))]).lower()
            effect = self._effect_filter.currentData()
            scope = self._visibility_filter.currentData()
            matches = ((not query or query in haystack)
                       and (effect is None or effect in (entry.get('effect_type'), entry.get('effect_2_type')))
                       and (scope is None or scope == visibility(entry)))
            btn.setVisible(matches)
            visible += int(matches)
        self._no_matches.setVisible(bool(self._entries) and not visible)

    def _select_entry(self, idx: int):
        if idx < 0 or idx >= len(self._entries):
            return
        if not self._apply_current_entry(show_errors=True):
            return
        self._current_idx = idx
        for btn, button_idx in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=button_idx == idx))
        self._build_editor(idx)
        self._update_actions()

    def _refresh_entry_button(self, idx: int):
        for btn, button_idx in self._entry_buttons:
            if button_idx != idx:
                continue
            labels = btn.findChildren(QLabel)
            if len(labels) >= 1:
                title_text = self._entry_title(idx, self._entries[idx])
                button_title = self._entry_button_title(idx, self._entries[idx])
                labels[0].setText(button_title)
                labels[0].setProperty('supportFullText', button_title)
                labels[0].setText(labels[0].fontMetrics().elidedText(
                    button_title, Qt.TextElideMode.ElideRight, labels[0].width()))
                labels[0].setToolTip(title_text)
            if len(labels) >= 2:
                subtitle_text = self._entry_subtitle(self._entries[idx])
                button_subtitle = self._entry_button_subtitle(self._entries[idx])
                labels[1].setText(button_subtitle)
                labels[1].setProperty('supportFullText', button_subtitle)
                labels[1].setText(labels[1].fontMetrics().elidedText(
                    button_subtitle, Qt.TextElideMode.ElideRight, labels[1].width()))
                labels[1].setToolTip(subtitle_text)
            btn.setToolTip(title_text + '\n' + subtitle_text)
            break
        self._filter_list()

    def _update_actions(self):
        loaded = self._raw_data is not None
        has_selection = self._current_idx is not None and 0 <= self._current_idx < len(self._entries)
        self._btn_add.setEnabled(loaded)
        self._btn_dup.setEnabled(loaded and has_selection)
        self._btn_del.setEnabled(loaded and has_selection)
        self._btn_save.setEnabled(loaded and self._dirty)

    def _build_editor(self, idx: int):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._grids = {}
        self._loading_detail = True
        entry = self._entries[idx]
        self._last_compact = self._is_compact_editor()
        self._last_columns = self._grid_columns(3)

        header, grid = make_editor_grid_card(
            self._editor_widget, title=self._item_name(entry), icon_name='fa6s.bag-shopping',
            subtitle=self._entry_subtitle(entry))
        self._prep_card(header)
        self._summary_title = next(label for label in header.findChildren(QLabel)
                                   if label.text() == self._item_name(entry))
        self._summary_subtitle = next(label for label in header.findChildren(QLabel)
                                      if label.text() == self._entry_subtitle(entry))
        self._active_grid_columns = 3
        self._add_uint_field(grid, 0, 0, 'support_id', entry, self._label_for_key('support_id'), self._hint_for_key('support_id'))
        self._add_uint_field(grid, 0, 1, 'price', entry, self._label_for_key('price'), self._hint_for_key('price'))
        self._add_uint_field(grid, 0, 2, 'display_order', entry, self._label_for_key('display_order'), self._hint_for_key('display_order'))
        self._editor_layout.addWidget(header)

        self._research_card, body = make_editor_card(self._editor_widget)
        self._prep_card(self._research_card)
        add_editor_card_title(body, ui_text('support_status_title'), 'fa6s.circle-info')
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setFont(ui_font(TypeSize.BODY))
        label.setStyleSheet(ss_dim_label())
        body.addWidget(label)
        self._research_card.research_label = label
        self._editor_layout.addWidget(self._research_card)

        self._add_section(ui_text('support_menu_title'))
        card = self._make_card()
        grid = self._card_grid(card)
        for col, (key, options) in enumerate((
            ('shop_marker', [(99, ui_text('support_listed')), (0, ui_text('support_not_listed'))]),
            ('unlock_or_story_flag', [(0, ui_text('support_visibility_both')), (1, ui_text('support_visibility_campaign'))]),
            ('empty_slot_marker', availability_options()),
        )):
            self._add_combo_field(grid, 0, col, key, entry, options, self._label_for_key(key), self._hint_for_key(key))
        self._editor_layout.addWidget(card)

        for second in (False, True):
            self._add_section(ui_text('param_second_effect' if second else 'support_first_effect'))
            card = self._make_card()
            grid = self._card_grid(card)
            opcode = 'effect_2_type' if second else 'effect_type'
            target = 'effect_2_target' if second else 'target_group'
            prefix = 'effect_2_value_' if second else 'effect_value_'
            self._add_combo_field(grid, 0, 0, opcode, entry, effect_options(),
                                  self._label_for_key('effect_type'), self._hint_for_key('effect_type'), colspan=2)
            self._add_combo_field(grid, 0, 2, target, entry, target_options(second=second),
                                  self._label_for_key('target_group'), self._hint_for_key('target_group'))
            for i in range(1, 6):
                self._add_float_field(grid, 1 + (i - 1) // 3, (i - 1) % 3, prefix + str(i), entry,
                                      support_value_label(entry[opcode], i), support_value_hint(entry[opcode], i))
            self._editor_layout.addWidget(card)

        self._add_section(ui_text('ui_supportitemparam_text_keys'))
        card = self._make_card()
        grid = self._card_grid(card)
        self._active_grid_columns = 2
        self._text_previews = {}
        for index, key in enumerate(_TEXT_KEYS):
            self._add_text_field(grid, index // 2, index % 2, key, entry,
                                 self._label_for_key(key), ui_text('ui_supportitemparam_text_hint'))
            preview = QLabel()
            preview.setWordWrap(True)
            preview.setTextFormat(Qt.TextFormat.PlainText)
            preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            preview.setFont(ui_font(TypeSize.HINT))
            preview.setStyleSheet(ss_dim_label())
            preview.setMinimumWidth(0)
            preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            self._fields[key].parentWidget().layout().addWidget(preview)
            self._text_previews[key] = preview
        self._editor_layout.addWidget(card)

        self._add_section(ui_text('support_preserved_title'))
        card = self._make_card()
        card.layout().addWidget(self._explanation(ui_text('support_preserved_hint')))
        grid = self._card_grid(card)
        self._active_grid_columns = 3
        keys = ('tier_or_category', 'enabled_flag', 'raw_80', 'raw_84', 'raw_88')
        for index, key in enumerate(keys):
            self._add_uint_field(grid, index // 3, index % 3, key, entry,
                                 self._label_for_key(key), self._hint_for_key(key))
        self._editor_layout.addWidget(card)
        self._editor_layout.addStretch()
        self._loading_detail = False
        self._reflow_fields()
        self._refresh_research()
        self._refresh_text_previews()
        self._refresh_argument_hints()

    def _explanation(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        return label

    def _refresh_text_previews(self):
        entry = self._entries[self._current_idx]
        for key, label in self._text_previews.items():
            values = self._messages(entry.get(key, ''))
            label.setText(values[0] if values else ui_text('support_text_missing'))
        self._fit_timer.start(0)

    def _label_for_key(self, key: str) -> str:
        return ui_text(f"ui_supportitemparam_{key}")

    def _hint_for_key(self, key: str) -> str:
        if key == 'tier_or_category':
            return ui_text('ui_supportitemparam_tier_hint')
        specific = ui_text(f"ui_supportitemparam_{key}_hint")
        return specific if specific != f"ui_supportitemparam_{key}_hint" else ui_text("ui_supportitemparam_raw_hint")

    def _add_section(self, title: str):
        self._pending_section_title = title

    def _make_card(self) -> QFrame:
        section_title = getattr(self, "_pending_section_title", None)
        self._pending_section_title = None
        card, grid = make_editor_grid_card(self._editor_widget, title=section_title, icon_name='fa6s.sliders')
        self._prep_card(card)
        card._editor_grid = grid
        return card

    def _card_grid(self, card: QFrame) -> QGridLayout:
        return card._editor_grid

    def _field_shell(self, label: str, hint: str = "") -> tuple[QWidget, QVBoxLayout]:
        frame, layout, _label, _hint = make_editor_field_shell(label, hint)
        frame.installEventFilter(self)
        for widget in (_label, _hint):
            if widget is not None:
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        return frame, layout

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and isinstance(watched, QComboBox) and not watched.hasFocus():
            event.ignore()
            return True
        if (event.type() == QEvent.Type.Resize and hasattr(self, '_editor_scroll')
                and watched is self._editor_scroll.viewport() and self._current_idx is not None):
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)
        if event.type() == QEvent.Type.Resize and isinstance(watched, QWidget):
            if isinstance(watched, QLabel) and watched.property('supportFullText') is not None:
                watched.setText(watched.fontMetrics().elidedText(
                    watched.property('supportFullText'), Qt.TextElideMode.ElideRight, watched.width()))
            layout = watched.layout()
            if layout:
                width = max(1, watched.contentsRect().width())
                for i in range(layout.count()):
                    label = layout.itemAt(i).widget()
                    if isinstance(label, QLabel) and label.wordWrap():
                        height = max(0, label.heightForWidth(width))
                        if label.minimumHeight() != height:
                            label.setMinimumHeight(height)
                            self._fit_timer.start(0)
        return super().eventFilter(watched, event)

    def _place_field(self, grid, frame, span=1):
        if grid not in self._grids:
            self._grids[grid] = (self._active_grid_columns, [])
        self._grids[grid][1].append((frame, span))
        # Lay out immediately so Qt can compute the card's initial size.
        self._reflow_grid(grid)

    def _reflow_grid(self, grid):
        maximum, fields = self._grids[grid]
        columns = self._grid_columns(maximum)
        while grid.count():
            grid.takeAt(0)
        for column in range(maximum):
            grid.setColumnStretch(column, int(column < columns))
        row = col = 0
        for frame, requested in fields:
            span = min(columns, requested)
            if col + span > columns:
                row, col = row + 1, 0
            grid.addWidget(frame, row, col, 1, span)
            col += span
            if col == columns:
                row, col = row + 1, 0

    def _reflow_fields(self):
        for grid in self._grids:
            self._reflow_grid(grid)
        self._last_columns = self._grid_columns(3)
        self._last_compact = self._is_compact_editor()
        self._fit_timer.start(0)

    def _fit_card_heights(self):
        from core.ui.editor_widgets import fit_scroll_page
        fit_scroll_page(self._editor_scroll)

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_editor_scroll"):
            return False
        return self._editor_scroll.viewport().width() < 780

    def _grid_columns(self, max_columns: int) -> int:
        width = self._editor_scroll.viewport().width()
        if width < 780:
            return 1
        if width < 960:
            return min(2, max_columns)
        return max_columns

    def _prep_card(self, card: QFrame):
        configure_card(card, vertical_policy=QSizePolicy.Policy.Minimum)
        return card

    def _prep_field_widget(self, frame: QWidget, editor: QWidget):
        configure_field(frame, editor, vertical_policy=QSizePolicy.Policy.Minimum)
        if frame.layout().count() > 2:
            editor.setToolTip(frame.layout().itemAt(1).widget().text())

    def _add_text_field(self, grid, row, col, key, entry, label, hint="", big=False):
        self._add_text_value_field(grid, row, col, key, label, str(entry.get(key, "")), hint, big=big)

    def _add_text_value_field(self, grid, row, col, key, label, value, hint="", colspan=1, hex_mode=False, big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._hex_validator if hex_mode else self._ascii_validator)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(value))
        edit.setCursorPosition(0)
        edit.textChanged.connect(lambda _text, k=key: self._on_text_changed(k))
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame, colspan)
        self._fields[key] = edit

    def _add_uint_field(self, grid, row, col, key, entry, label, hint="", big=False):
        self._add_uint_value_field(grid, row, col, key, label, int(entry.get(key, 0)), hint, big=big)

    def _add_uint_value_field(self, grid, row, col, key, label, value, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._uint_validator)
        edit.setMaxLength(10)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(str(int(value)))
        edit.setProperty('supportField', key)
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(self._on_number_finished)
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame)
        self._fields[key] = edit

    def _add_combo_field(self, grid, row, col, key, entry, options, label, hint="", big=False, colspan=1):
        frame, layout = self._field_shell(label, hint)
        combo = QComboBox()
        configure_input(combo, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=False)
        combo.installEventFilter(self)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.setMinimumContentsLength(1)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        current = int(entry.get(key, 0))
        values = [value for value, _text in options]
        if current not in values:
            options = list(options) + [(current, ui_text("ui_supportitemparam_custom_option", value=current))]
        for value, text in options:
            combo.addItem(text, value)
        selected = combo.findData(current)
        combo.setCurrentIndex(max(0, selected))
        combo.currentIndexChanged.connect(lambda _idx, k=key: self._on_combo_changed(k))
        layout.addWidget(combo)
        self._prep_field_widget(frame, combo)
        self._place_field(grid, frame, colspan)
        self._fields[key] = combo

    def _add_float_field(self, grid, row, col, key, entry, label, hint="", big=False):
        frame, layout = self._field_shell(label, hint)
        edit = QLineEdit()
        edit.setValidator(self._float_validator)
        configure_input(edit, height=Size.LARGE_CONTROL if big else Size.CONTROL, monospace=True)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.setText(f"{float(entry.get(key, 0.0)):.9g}")
        edit.setProperty('supportField', key)
        edit.setCursorPosition(0)
        edit.textChanged.connect(self._on_numeric_text_changed)
        edit.editingFinished.connect(self._on_number_finished)
        layout.addWidget(edit)
        self._prep_field_widget(frame, edit)
        self._place_field(grid, frame)
        self._fields[key] = edit

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx is not None and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx is None or self._loading_detail:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact and self._last_columns == self._grid_columns(3):
            self._fit_timer.start(0)
            return
        self._apply_current_entry(show_errors=False)
        self._reflow_fields()

    def _on_text_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        if key in ("notes_hex", "pre_text_blob_hex"):
            self._mark_dirty()
            self._set_valid(self._fields[key], self._read_hex(key, 'ui_supportitemparam_invalid_blob_hex') is not None)
            return
        self._entries[self._current_idx][key] = self._fields[key].text()
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)
        self._refresh_research()
        self._refresh_text_previews()

    def _on_numeric_text_changed(self):
        if not self._loading_detail:
            self._mark_dirty()
            widget = self.sender()
            for key, field in self._fields.items():
                if field is widget:
                    value = self._read_float(key) if key in _FLOAT_KEYS else self._read_uint(key)
                    self._set_valid(field, value is not None)
                    break
            self._refresh_argument_hints()

    def _on_combo_changed(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        widget = self._fields.get(key)
        if not isinstance(widget, QComboBox):
            return
        self._entries[self._current_idx][key] = int(widget.currentData())
        self._mark_dirty()
        self._refresh_entry_button(self._current_idx)
        if key in ('effect_type', 'effect_2_type'):
            self._refresh_effect_captions()
            self._refresh_argument_hints()
        self._refresh_research()

    def _refresh_research(self):
        if self._current_idx is None or not getattr(self, '_research_card', None):
            return
        entry = self._entries[self._current_idx]
        text = '\n'.join(row_description(entry).splitlines()[1:])
        if packet_gate(entry):
            text = ui_text('support_ready') + ('\n' + text if text else '')
        diagnostic = identity_diagnostics(entry, self._entries)
        if diagnostic:
            text = diagnostic + '\n\n' + text
        self._research_card.research_label.setText(text)
        self._summary_title.setText(self._item_name(entry))
        self._summary_subtitle.setText(self._entry_subtitle(entry))
        self._fit_timer.start(0)

    def _refresh_argument_hints(self):
        if self._current_idx is None or not hasattr(self, '_text_previews'):
            return
        from core.parameter_research import set_field_hint
        entry = self._entries[self._current_idx]
        for second in (False, True):
            opcode = entry.get('effect_2_type' if second else 'effect_type', 0)
            prefix = 'effect_2_value_' if second else 'effect_value_'
            for index in range(1, 6):
                key = prefix + str(index)
                if key not in self._fields:
                    continue
                value = self._read_float(key)
                hint = support_value_hint(opcode, index)
                if value is not None:
                    if (opcode == 15 and index == 1) or (opcode == 17 and index == 2):
                        hint = ui_text('support_value_seconds', value=f'{value / 30:.6g}')
                    elif opcode in (19, 20) and index == 1:
                        hint = ui_text('support_value_percent', value=f'{value * 100:.6g}')
                    elif (opcode in (13, 14, 25) and index == 1) or (opcode == 35 and index in (1, 2)):
                        hint = ui_text('support_value_multiplier', value=f'{value:.6g}')
                set_field_hint(self._fields, key, hint)
        self._fit_timer.start(0)

    def _refresh_effect_captions(self):
        from core.parameter_research import set_field_caption, set_field_hint, support_value_label, support_value_hint
        entry = self._entries[self._current_idx]
        for prefix, opcode_key in (('effect_value_', 'effect_type'), ('effect_2_value_', 'effect_2_type')):
            for i in range(1, 6):
                set_field_caption(self._fields, prefix + str(i), support_value_label(entry.get(opcode_key, 0), i))
                set_field_hint(self._fields, prefix + str(i), support_value_hint(entry.get(opcode_key, 0), i))

    def _on_uint_finished(self, key: str):
        if self._loading_detail:
            return
        value = self._read_uint(key)
        if value is None:
            return
        if key == "version":
            if self._result is not None:
                self._result["version"] = value
            return
        if self._current_idx is not None:
            self._entries[self._current_idx][key] = value
            self._refresh_entry_button(self._current_idx)
            if key == 'effect_2_type':
                self._refresh_effect_captions()
            self._refresh_research()

    def _on_number_finished(self):
        widget = self.sender()
        key = widget.property('supportField') if widget is not None else None
        if key in _FLOAT_KEYS:
            self._on_float_finished(key)
        elif key in _UINT_KEYS:
            self._on_uint_finished(key)

    def _on_float_finished(self, key: str):
        if self._loading_detail or self._current_idx is None:
            return
        value = self._read_float(key)
        if value is not None:
            self._entries[self._current_idx][key] = value

    def _set_valid(self, widget, valid):
        if widget.property('supportInvalid') == (not valid):
            return
        widget.setProperty('supportInvalid', not valid)
        widget.setStyleSheet(ss_input_validation(not valid))

    def _read_ascii(self, key: str, show_errors: bool = False) -> str | None:
        widget = self._fields.get(key)
        if widget is None:
            return ""
        text = widget.text()
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            if show_errors:
                self._set_valid(widget, False)
                widget.setFocus()
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_supportitemparam_ascii_only", field=self._label_for_key(key)))
            return None
        return text

    def _read_uint(self, key: str, show_errors: bool = False) -> int | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        if isinstance(widget, QComboBox):
            return int(widget.currentData())
        text = widget.text().strip()
        try:
            value = int(text)
        except ValueError:
            value = _UINT32_MAX + 1
        if value < 0 or value > _UINT32_MAX:
            if show_errors:
                self._set_valid(widget, False)
                widget.setFocus()
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_supportitemparam_invalid_integer", value=text, min=0, max=_UINT32_MAX))
            return None
        return value

    def _read_float(self, key: str, show_errors: bool = False) -> float | None:
        widget = self._fields.get(key)
        if widget is None:
            return None
        text = widget.text().strip()
        try:
            value = float(text)
            value = struct.unpack('<f', struct.pack('<f', value))[0]
        except (ValueError, OverflowError):
            value = math.inf
        if not math.isfinite(value) or value < _FLOAT_MIN or value > _FLOAT_MAX:
            if show_errors:
                self._set_valid(widget, False)
                widget.setFocus()
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_supportitemparam_invalid_float", value=text))
            return None
        return value

    def _notes_hex(self) -> str:
        if not self._result:
            return ""
        return " ".join(f"{byte:02X}" for byte in bytes(self._result.get("notes", b"")))

    def _blob_hex(self, entry: dict) -> str:
        return " ".join(f"{byte:02X}" for byte in bytes(entry.get("pre_text_blob", b"")))

    def _read_hex(self, key: str, error_key: str, show_errors: bool = False) -> bytes | None:
        widget = self._fields.get(key)
        if widget is None:
            return b""
        text = widget.text().strip().replace(" ", "")
        if not text:
            return b""
        try:
            return bytes.fromhex(text)
        except ValueError:
            if show_errors:
                self._set_valid(widget, False)
                widget.setFocus()
                QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text(error_key))
            return None

    def _apply_current_entry(self, show_errors: bool = False) -> bool:
        if self._result is not None and "version" in self._fields:
            version = self._read_uint("version", show_errors=show_errors)
            if version is None:
                return False
            self._result["version"] = version
        if self._result is not None and "notes_hex" in self._fields:
            notes = self._read_hex("notes_hex", "ui_supportitemparam_invalid_hex", show_errors=show_errors)
            if notes is None:
                return False
            self._result["notes"] = notes

        if self._current_idx is None:
            return True
        entry = copy.deepcopy(self._entries[self._current_idx])
        for key in _TEXT_KEYS:
            value = self._read_ascii(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        for key in _UINT_KEYS:
            if key not in self._fields:
                continue
            value = self._read_uint(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        for key in _FLOAT_KEYS:
            if key not in self._fields:
                continue
            value = self._read_float(key, show_errors=show_errors)
            if value is None:
                return False
            entry[key] = value
        if "pre_text_blob_hex" in self._fields:
            blob = self._read_hex("pre_text_blob_hex", "ui_supportitemparam_invalid_blob_hex", show_errors=show_errors)
            if blob is None:
                return False
            entry["pre_text_blob"] = blob
        self._entries[self._current_idx].update(entry)
        self._refresh_entry_button(self._current_idx)
        return True

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            if self._filepath:
                set_file_label(self._file_label, self._filepath, dirty=True)
        self._update_actions()

    def _do_add(self):
        if self._raw_data is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        entry = self._new_identity(make_default_entry())
        if entry is None:
            return
        self._entries.append(entry)
        self._current_idx = None
        self._mark_dirty()
        self._search._design_filter_reset.clear()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)

    def _do_dup(self):
        if self._raw_data is None or self._current_idx is None:
            return
        if not self._apply_current_entry(show_errors=True):
            return
        entry = self._new_identity(make_default_entry(self._entries[self._current_idx]))
        if entry is None:
            return
        self._entries.insert(self._current_idx + 1, entry)
        new_idx = self._current_idx + 1
        self._current_idx = None
        self._mark_dirty()
        self._search._design_filter_reset.clear()
        self._populate_list()
        self._select_entry(new_idx)

    def _new_identity(self, entry):
        used = {int(row.get('support_id', 0)) for row in self._entries}
        available = next((sid for sid in range(256) if sid not in used
                          and menu_class(sid) == 2 and sid != 23), None)
        if available is None:
            QMessageBox.warning(self, ui_text('dlg_title_warning'), ui_text('support_no_free_identity'))
            return None
        slots = {int(row.get('display_order', 0)) for row in self._entries}
        entry['support_id'] = available
        entry['display_order'] = next(slot for slot in range(len(slots) + 1) if slot not in slots)
        return entry

    def _do_del(self):
        if self._raw_data is None or self._current_idx is None:
            return
        entry = self._entries[self._current_idx]
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("msg_confirm_delete_item", name=self._entry_title(self._current_idx, entry)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        old_idx = self._current_idx
        self._entries.pop(old_idx)
        self._current_idx = None
        self._mark_dirty()
        self._populate_list()
        if self._entries:
            self._select_entry(min(old_idx, len(self._entries) - 1))
        else:
            self._show_placeholder(ui_text("ui_supportitemparam_no_entries"))
            self._update_actions()
