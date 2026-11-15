"""Editor for damageeff.bin.xfbin, with an automatically resolved effect catalog.

Each entry maps a damage-effect slot index to five effectprm slot IDs.
Load effectprm.bin.xfbin to resolve slot IDs to human-readable effect names.
"""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_accent_label,
    ss_bg_dark,
    ss_dim_label,
    ss_error_label,
    ss_main_label,
    ss_sidebar_btn,
    ss_transparent,
)
from core.ui.editor_widgets import (
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
from core.ui.editor_actions import install_file_actions
import os

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog, QMessageBox, QLineEdit, QSizePolicy, QComboBox, QCompleter,
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QFont

from core.editor_file_state import set_file_label
from core.damage_effects import EFFECT_KEYS, effectprm_candidates, effect_caption
from parsers.damageeff_parser import parse_damageeff_xfbin, save_damageeff_xfbin, _NONE_VAL
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir, load_settings

# Field definitions

_FIELDS = [(key, 'dme_field_' + key, key in ('eff_a', 'eff_c', 'eff_e'),
            'dme_hint_' + key) for key in EFFECT_KEYS]

_NONE_STR = "NONE"


# Value helpers

def _parse(text, nullable):
    t = text.strip()
    if nullable and t.upper() in (_NONE_STR, "-1", ""):
        return _NONE_VAL
    v = int(t, 16) if t.lower().startswith('0x') else int(t, 10)
    if v < 0 or v > 0xFFFFFFFF:
        raise ValueError(f"Value {v} out of range 0–4294967295")
    return v


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 1)] + "..."


# Main editor widget

class DamageEffEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t           = t or (lambda k, **kw: k)
        self._embedded    = embedded
        self._filepath    = None
        self._raw         = None
        self._result      = None
        self._dirty       = False
        self._effprm_map  = {}
        self._effprm_entries = {}
        self._effprm_path = None
        self._choice_cache = None
        self._current_idx = -1
        self._entry_buttons = []
        self._last_compact: bool | None = None
        self._field_widgets = {}  # key → (QComboBox, details label)

        self._build_ui()
        install_file_actions(self, self._btn_save, existing_button=self._btn_save_as)
        install_editor_chrome(self)

    def _tr(self, key, **kw):
        text = self._t(key, **kw)
        return ui_text(key, **kw) if text == key else text

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        top = EditorToolbar()
        self._build_toolbar_content(top)
        root.addWidget(top)

        sep = EditorSeparator(accent=True)


        root.addWidget(sep)

        body_w = QWidget()
        body = QHBoxLayout(body_w)
        configure_layout(body, LayoutRole.ROOT)

        sidebar = EditorSidebar()
        self._build_sidebar(sidebar)
        body.addWidget(sidebar)

        div1 = EditorSeparator(orientation=Qt.Orientation.Vertical)


        body.addWidget(div1)

        self._main_scroll = QScrollArea()


        self._main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        configure_scrollarea(self._main_scroll)
        self._main_inner = QWidget()
        self._main_inner.setStyleSheet(ss_bg_dark())
        self._main_layout = QVBoxLayout(self._main_inner)
        configure_layout(self._main_layout, LayoutRole.PAGE)
        self._main_scroll.setWidget(self._main_inner)
        body.addWidget(self._main_scroll, 1)

        root.addWidget(body_w, 1)

        self._show_placeholder()

    def _build_toolbar_content(self, bar):
        lo = bar.content_layout

        self._btn_open = QPushButton(self._tr("btn_open_file"))
        configure_button(self._btn_open, accent=True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_open.setProperty("designAction", 'open')
        lo.addWidget(self._btn_open)

        self._btn_save = QPushButton(self._tr("btn_save_file"))
        configure_button(self._btn_save, accent=True)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        lo.addWidget(self._btn_save)

        self._btn_save_as = QPushButton(self._tr('dme_save_as'))
        configure_button(self._btn_save_as)
        self._btn_save_as.setEnabled(False)
        self._btn_save_as.clicked.connect(self._on_save_as)
        lo.addWidget(self._btn_save_as)

        lo.addSpacing(8)

        self._btn_effprm = QPushButton(self._tr("ui_damageeff_load_effectprm"))
        configure_button(self._btn_effprm)
        self._btn_effprm.setToolTip(self._tr("ui_damageeff_load_effectprm_bin_xfbin_to_resolve_slot_ids_to_"))
        self._btn_effprm.clicked.connect(self._on_load_effectprm)
        lo.addWidget(self._btn_effprm)

        self._effprm_lbl = QLabel(self._tr("ui_damageeff_not_loaded"))

        configure_file_label(self._effprm_lbl)
        self._effprm_lbl.setMinimumWidth(0)
        self._effprm_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lo.addWidget(self._effprm_lbl, 1)

        self._file_lbl = QLabel(self._tr("xfa_no_file"))

        configure_file_label(self._file_lbl)
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lo.addWidget(self._file_lbl, 1)

    def _build_sidebar(self, frame):
        lo = frame.content_layout

        self._search = QLineEdit()
        configure_search(self._search)
        self._search.setClearButtonEnabled(True)
        self._search.installEventFilter(self)
        configure_search(self._search)
        self._search.textChanged.connect(self._on_search)
        lo.addWidget(self._search)


        btn_row = QHBoxLayout()
        configure_layout(btn_row, LayoutRole.ACTIONS)

        self._btn_new = QPushButton(self._tr("btn_new"))
        configure_button(self._btn_new, height=Size.COMPACT_CONTROL)
        self._btn_new.setEnabled(False)
        self._btn_new.clicked.connect(self._on_add_entry)
        self._btn_new.setProperty("designAction", 'new')
        btn_row.addWidget(self._btn_new)

        self._btn_dup = QPushButton(self._tr("btn_dup_short"))
        configure_button(self._btn_dup, height=Size.COMPACT_CONTROL)
        self._btn_dup.setEnabled(False)
        self._btn_dup.clicked.connect(self._on_dup_entry)
        self._btn_dup.setProperty("designAction", 'duplicate')
        btn_row.addWidget(self._btn_dup)

        self._btn_del = QPushButton(self._tr("btn_delete"))
        configure_button(self._btn_del, danger=True, height=Size.COMPACT_CONTROL)
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._on_delete_entry)
        self._btn_del.setProperty("designAction", 'delete')
        btn_row.addWidget(self._btn_del)

        lo.addLayout(btn_row)

        self._sidebar_scroll = QScrollArea()

        configure_scrollarea(self._sidebar_scroll, transparent=True)
        self._sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._sidebar_inner = QWidget()
        self._sidebar_inner.setMinimumWidth(0)
        self._sidebar_inner.setStyleSheet(ss_transparent())
        self._sidebar_list = QVBoxLayout(self._sidebar_inner)
        configure_layout(self._sidebar_list, LayoutRole.TITLE_TEXT)
        self._sidebar_list.addStretch()

        self._sidebar_scroll.setWidget(self._sidebar_inner)
        lo.addWidget(self._sidebar_scroll, 1)

    # Sidebar

    def _make_entry_button(self, entry, idx):
        btn = QPushButton()
        btn.setFixedHeight(58)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.setStyleSheet(ss_transparent())
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(10, 4, 10, 4)
        vl.setSpacing(1)

        name_text = self._entry_caption(entry)
        name_lbl = QLabel(name_text)
        name_lbl.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        name_lbl.setToolTip(name_text)
        vl.addWidget(name_lbl)

        id_text = self._tr('dme_entry_ids', row=idx, id=entry['entry_id'])
        id_lbl = QLabel(_truncate(id_text, 28))
        id_lbl.setFont(mono_font(TypeSize.CODE))
        id_lbl.setStyleSheet(ss_dim_label())
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        id_lbl.setToolTip(id_text)
        vl.addWidget(id_lbl)

        ol = QHBoxLayout(btn)
        ol.setContentsMargins(*Insets.NONE)
        ol.addWidget(inner)

        btn.clicked.connect(lambda checked, i=idx: self._select_entry(i))
        btn.setToolTip(name_text + '\n' + id_text + '\n' + '\n'.join(
            f'{self._tr(title)}: {self._effect_text(entry[key], nullable)}'
            for key, title, nullable, _ in _FIELDS))
        btn.setAccessibleName(name_text + ', ' + id_text)
        return btn

    def _entry_caption(self, entry):
        name = self._effprm_map.get(entry['eff_b'])
        return effect_caption(name, self._tr) if name else self._tr(
            'ui_damageeff_entry_value', p0=entry['entry_id'])

    def _populate_sidebar(self, filter_text=""):
        ft = filter_text.strip().lower()
        while self._sidebar_list.count() > 1:
            item = self._sidebar_list.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        self._entry_buttons = []
        if self._result is None:
            return

        for idx, entry in enumerate(self._result['entries']):
            search = ' '.join([str(idx), str(entry['entry_id']), self._entry_caption(entry)] + [
                self._effect_text(entry[k], n) + ' ' + self._effect_details(entry[k], n)
                for k, _, n, _ in _FIELDS]).casefold()
            if ft and not all(word in search for word in ft.split()):
                continue
            btn = self._make_entry_button(entry, idx)
            self._sidebar_list.insertWidget(self._sidebar_list.count() - 1, btn)
            self._entry_buttons.append((idx, btn))
        if not self._entry_buttons:
            empty = QLabel(self._tr('dme_no_results'))
            empty.setStyleSheet(ss_dim_label())
            empty.setWordWrap(True)
            self._sidebar_list.insertWidget(0, empty)

    def _refresh_sidebar_styles(self):
        for idx, btn in self._entry_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

    # Right panel

    def _show_placeholder(self):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        card = make_empty_state(
            self._main_inner,
            title=self._tr("no_file_loaded"),
            text=self._tr("ui_damageeff_open_a_damageeff_bin_xfbin_file_to_begin_editing"),
            icon_name="fa6s.wand-magic-sparkles",
        )
        self._main_layout.addStretch(1)
        self._main_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)

    def _show_empty_selection(self):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        card = make_empty_state(
            self._main_inner,
            title=self._tr("ui_model_viewer_select_item"),
            text=self._tr("ui_damageeff_select_an_entry_from_the_sidebar"),
            icon_name="fa6s.list",
        )
        self._main_layout.addStretch(1)
        self._main_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addStretch(1)

    def _is_compact_editor(self) -> bool:
        if not hasattr(self, "_main_scroll"):
            return False
        return self._main_scroll.viewport().width() < 780

    def _grid_columns(self, max_columns: int) -> int:
        width = self._main_scroll.viewport().width()
        if width < 780:
            return 1
        if width < 1080:
            return min(2, max_columns)
        return max_columns

    def _prep_card(self, card: QFrame):
        configure_card(card)
        return card

    def _prep_field_widget(self, widget: QWidget):
        configure_field(widget)
        return widget

    def _add_editor_card(self, card: QFrame):
        self._main_layout.addWidget(card)

    def _build_editor(self, entry):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        self._last_compact = self._is_compact_editor()
        columns = self._grid_columns(2)

        card, grid = make_editor_grid_card(self._main_inner, title=self._tr('ui_damageeff_damage_effect_slot_value', p0=entry['entry_id']), icon_name='fa6s.wand-magic-sparkles', subtitle=self._tr('dme_intro'))
        self._prep_card(card)

        for i, (fkey, fname, nullable, tip) in enumerate(_FIELDS):
            lbl_text = self._tr(fname)
            tip = self._tr(tip)
            val = entry[fkey]
            field, field_layout, label, _ = make_editor_field_shell(lbl_text)
            self._prep_field_widget(field)
            label.setToolTip(tip)
            inp = self._effect_choice(val, nullable)
            configure_input(inp, height=Size.CONTROL, monospace=False)
            inp.setToolTip(tip)
            inp.setMinimumWidth(0)
            inp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            field_layout.addWidget(inp)

            name_lbl = QLabel(self._effect_details(val, nullable))
            name_lbl.setTextFormat(Qt.TextFormat.PlainText)
            name_lbl.setWordWrap(True)
            name_lbl.setMinimumWidth(0)
            name_lbl.setStyleSheet(ss_dim_label())
            name_lbl.setFont(mono_font(TypeSize.HINT))
            name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            field_layout.addWidget(name_lbl)
            hint = QLabel(tip)
            hint.setWordWrap(True)
            hint.setStyleSheet(ss_dim_label())
            hint.setFont(ui_font(TypeSize.BODY))
            field_layout.addWidget(hint)
            inp.currentIndexChanged.connect(lambda _, fk=fkey: self._field_changed(fk))
            inp.lineEdit().textEdited.connect(lambda _, fk=fkey: self._field_changed(fk))

            row, col = divmod(i, columns)
            grid.addWidget(field, row, col, alignment=Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(col, 1)
            self._field_widgets[fkey] = (inp, name_lbl)

        self._add_editor_card(card)
        self._main_layout.addStretch(1)
        QTimer.singleShot(0, self._fit_card_heights)

    def _effect_text(self, value, nullable):
        if nullable and value == _NONE_VAL:
            return 'NONE · ' + self._tr('dme_none')
        record = self._effprm_entries.get(value)
        caption = (effect_caption(record['effect_name'], self._tr) if record is not None
                   else self._tr('dme_custom_effect'))
        return f'{value} · {caption}'

    def _effect_details(self, value, nullable):
        if nullable and value == _NONE_VAL:
            return self._tr('dme_none')
        record = self._effprm_entries.get(value)
        if record is None:
            return self._tr('dme_unresolved', id=value)
        return (record['effect_name'] or self._tr('dme_empty_effect')) + (
            '\n' + record['xfbin_path'] if record['xfbin_path'] else '')

    def _effect_choice(self, value, nullable):
        inp = QComboBox()
        inp.setEditable(True)
        inp.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        inp.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        inp.setMaxVisibleItems(12)
        if nullable:
            inp.addItem(self._effect_text(_NONE_VAL, True), _NONE_VAL)
        language_key = self._tr('dme_none')
        if self._choice_cache is None or self._choice_cache[0] != language_key:
            rows = [(n, self._effect_text(n, False), self._effect_details(n, False))
                    for n in sorted(self._effprm_entries)]
            names = [r['effect_name'] for r in self._effprm_entries.values() if r['effect_name']]
            unique_names = sorted(name for name in set(names) if names.count(name) == 1)
            self._choice_cache = (language_key, rows, unique_names)
        _, rows, unique_names = self._choice_cache
        for number, caption, details in rows:
            if nullable and number == _NONE_VAL:
                continue
            inp.addItem(caption, number)
            inp.setItemData(inp.count() - 1, details, Qt.ItemDataRole.ToolTipRole)
        index = inp.findData(value)
        if index < 0:
            inp.addItem(self._effect_text(value, nullable), value)
            index = inp.count() - 1
        inp.setCurrentIndex(index)
        # Include authored names in completion, while keeping readable captions
        # in the normal dropdown. Ambiguous authored names still require an ID.
        inp.setCompleter(QCompleter([inp.itemText(i) for i in range(inp.count())] + unique_names, inp))
        inp.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        inp.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        inp.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        inp.lineEdit().setPlaceholderText(self._tr('dme_choice_hint'))
        inp.lineEdit().setCursorPosition(0)
        inp.installEventFilter(self)
        return inp

    def _choice_value(self, inp, nullable):
        text = inp.currentText().strip()
        index = inp.findText(text, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            return inp.itemData(index)
        # Exact asset names are accepted too; duplicate names require an ID.
        matches = [number for number, record in self._effprm_entries.items()
                   if record['effect_name'] and record['effect_name'].casefold() == text.casefold()]
        if len(matches) == 1:
            return matches[0]
        return _parse(text, nullable)

    def _field_changed(self, key):
        self._mark_dirty()
        inp, label = self._field_widgets[key]
        nullable = next(n for k, _, n, _ in _FIELDS if k == key)
        try:
            value = self._choice_value(inp, nullable)
        except (ValueError, TypeError):
            label.setText(self._tr('dme_invalid'))
            label.setStyleSheet(ss_error_label())
        else:
            label.setText(self._effect_details(value, nullable))
            label.setStyleSheet(ss_dim_label())
        QTimer.singleShot(0, self._fit_card_heights)

    def _fit_card_heights(self):
        width = max(100, self._main_scroll.viewport().width() - 24)
        for i in range(self._main_layout.count()):
            card = self._main_layout.itemAt(i).widget()
            if isinstance(card, QFrame) and card.layout() is not None:
                card.layout().invalidate()
                height = card.layout().totalHeightForWidth(min(width, card.maximumWidth()))
                if height > 0:
                    card.setFixedHeight(height)
        self._main_layout.invalidate()

    def eventFilter(self, obj, event):
        if isinstance(obj, QComboBox) and event.type() == QEvent.Type.Wheel and not obj.view().isVisible():
            event.ignore()
            return True
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Return):
                indices = [idx for idx, _ in self._entry_buttons]
                if indices:
                    position = indices.index(self._current_idx) if self._current_idx in indices else -1
                    if event.key() == Qt.Key.Key_Return:
                        position = max(0, position)
                    else:
                        position = max(0, min(len(indices) - 1, position + (1 if event.key() == Qt.Key.Key_Down else -1)))
                    if self._select_entry(indices[position]):
                        self._sidebar_scroll.ensureWidgetVisible(self._entry_buttons[position][1])
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx >= 0 and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx < 0 or self._result is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact:
            self._fit_card_heights()
            return
        if not self._apply_fields():
            return
        entries = self._result.get('entries') or []
        if 0 <= self._current_idx < len(entries):
            self._build_editor(entries[self._current_idx])

    def _mark_dirty(self, *_):
        self._dirty = True
        self._btn_save.setEnabled(True)
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _apply_fields(self):
        if self._current_idx < 0 or self._result is None:
            return True
        entries = self._result['entries']
        if not (0 <= self._current_idx < len(entries)):
            return True
        entry = entries[self._current_idx]
        candidate = {}
        for fkey, fname, nullable, _ in _FIELDS:
            if fkey not in self._field_widgets:
                continue
            inp, name_lbl = self._field_widgets[fkey]
            try:
                value = self._choice_value(inp, nullable)
            except (ValueError, TypeError):
                name_lbl.setText(self._tr('dme_invalid'))
                name_lbl.setStyleSheet(ss_error_label())
                inp.setFocus()
                inp.lineEdit().selectAll()
                self._main_scroll.ensureWidgetVisible(inp)
                self._fit_card_heights()
                return False
            candidate[fkey] = value
        changed = any(entry[k] != value for k, value in candidate.items())
        entry.update(candidate)
        for key, _, nullable, _ in _FIELDS:
            if key in self._field_widgets:
                _, label = self._field_widgets[key]
                label.setText(self._effect_details(candidate[key], nullable))
                label.setStyleSheet(ss_dim_label())
        if changed:
            self._mark_dirty()
            self._populate_sidebar(self._search.text())
        return True

    def _select_entry(self, idx):
        if not self._apply_fields():
            return False
        self._current_idx = idx
        self._refresh_sidebar_styles()

        if self._result is None or not (0 <= idx < len(self._result['entries'])):
            self._show_empty_selection()
            return False

        entry = self._result['entries'][idx]
        self._build_editor(entry)
        self._btn_del.setEnabled(True)
        self._btn_dup.setEnabled(True)
        self._main_scroll.verticalScrollBar().setValue(0)
        return True

    # effectprm

    def _on_load_effectprm(self):
        if not self._apply_fields():
            return False
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("ui_damageeff_load_effectprm_bin_xfbin"), game_files_dialog_dir(target_patterns="effectprm.bin.xfbin"),
            "XFBIN Files (effectprm.bin.xfbin);;All Files (*.*)"
        )
        if not path:
            return False
        return self._load_effectprm(path, report_error=True)

    def _load_effectprm(self, path, report_error=False):
        if not self._apply_fields():
            return False
        try:
            from parsers.effectprm_parser import parse_effectprm_xfbin
            _, eff = parse_effectprm_xfbin(path)
            records = {e['slot_id']: e for e in eff['entries']}
        except Exception as e:
            if report_error:
                QMessageBox.critical(self, self._tr("dlg_title_error"), self._tr("ui_damageeff_failed_to_load_effectprm_value", p0=e))
            return False

        self._effprm_entries = records
        self._choice_cache = None
        self._effprm_map = {number: record['effect_name'] for number, record in records.items()}
        self._effprm_path = str(path)

        self._effprm_lbl.setText(self._tr("ui_damageeff_value_effects_loaded"))
        self._effprm_lbl.setStyleSheet(ss_accent_label())
        self._effprm_lbl.setToolTip(str(path))
        self._btn_effprm.setText(self._tr("ui_damageeff_reload_effectprm"))

        if self._result and 0 <= self._current_idx < len(self._result['entries']):
            self._build_editor(self._result['entries'][self._current_idx])
        self._populate_sidebar(self._search.text())
        return True

    def _auto_load_effectprm(self):
        # Reset on every damage file, even after a failed lookup: another mod's
        # catalog must never silently label this file's slot IDs.
        self._effprm_entries = {}
        self._effprm_map = {}
        self._effprm_path = None
        self._choice_cache = None
        errors = []
        try:
            candidates = effectprm_candidates(self._filepath, load_settings().get('game_files_dir', ''))
            for path in candidates:
                if self._load_effectprm(path):
                    return True
                errors.append(str(path))
        except OSError as error:
            errors.append(str(error))
        self._effprm_lbl.setText(self._tr('dme_catalog_missing'))
        self._effprm_lbl.setStyleSheet(ss_dim_label())
        self._effprm_lbl.setToolTip(self._tr('dme_catalog_missing_hint') + (
            '\n' + '\n'.join(errors) if errors else ''))
        self._btn_effprm.setText(self._tr('ui_damageeff_load_effectprm'))
        return False

    # Data loading

    def _load_file(self, filepath):
        filepath = os.fspath(filepath)
        if not self._confirm_discard():
            return False
        try:
            raw, result = parse_damageeff_xfbin(filepath)
        except Exception as e:
            QMessageBox.critical(self, self._tr("dlg_title_error"), self._tr("ui_assist_failed_to_open_file_value", p0=e))
            return False

        create_backup_on_open(filepath)
        self._filepath    = filepath
        self._raw         = raw
        self._result      = result
        self._dirty       = False
        self._current_idx = -1
        self._field_widgets = {}
        self._btn_del.setEnabled(False)
        self._btn_dup.setEnabled(False)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._auto_load_effectprm()

        self._populate_sidebar()
        if self._result.get('entries'):
            self._select_entry(0)
        else:
            self._show_empty_selection()

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_new.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        return True

    # Search

    def _on_search(self, text):
        self._populate_sidebar(filter_text=text)

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("ui_damageeff_open_damageeff_bin_xfbin"), game_files_dialog_dir(target_patterns="damageeff.bin.xfbin"),
            "XFBIN Files (damageeff.bin.xfbin);;All Files (*.*)"
        )
        if path:
            self._load_file(path)

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return False
        return self._save_to(self._filepath)

    def _on_save_as(self):
        if self._raw is None or not self._apply_fields():
            return False
        path, _ = QFileDialog.getSaveFileName(self, self._tr('dme_save_as'), self._filepath,
                                             'XFBIN Files (*.xfbin);;All Files (*.*)')
        return self._save_to(path) if path else False

    def _confirm_discard(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, self._tr('hit_unsaved_title'), self._tr('hit_unsaved'),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if not self._embedded and not self._confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)

    def _save_to(self, filepath):
        filepath = os.fspath(filepath)
        if not self._apply_fields():
            return False
        try:
            save_damageeff_xfbin(filepath, self._raw, self._result)
            self._filepath = str(filepath)
            self._dirty = False
            set_file_label(self._file_lbl, filepath)
            QMessageBox.information(self, self._tr("ui_assist_saved"), self._tr("ui_assist_file_saved_value", p0=os.path.basename(filepath)))
            return True
        except Exception as e:
            QMessageBox.critical(self, self._tr("ui_assist_save_error"), self._tr("ui_assist_failed_to_save_value", p0=e))
            return False

    # Add / Dup / Delete

    def _new_entry_id(self):
        used = {e['entry_id'] for e in self._result['entries']}
        value = (max(used, default=-1) + 1) & 0xFFFFFFFF
        while value in used:
            value = (value + 1) & 0xFFFFFFFF
        return value

    def _on_add_entry(self):
        if self._result is None:
            return
        if not self._apply_fields():
            return False
        entries = self._result['entries']
        new_idx = len(entries)
        entries.append({
            'idx':      new_idx,
            'entry_id': self._new_entry_id(),
            'eff_a':    _NONE_VAL,
            'eff_b':    0,
            'eff_c':    _NONE_VAL,
            'eff_d':    0,
            'eff_e':    _NONE_VAL,
        })
        self._result['entry_count'] = len(entries)
        self._mark_dirty()
        self._search.clear()
        self._populate_sidebar(self._search.text())
        self._select_entry(new_idx)
        self._sidebar_scroll.verticalScrollBar().setValue(
            self._sidebar_scroll.verticalScrollBar().maximum()
        )

    def _on_dup_entry(self):
        if self._result is None or self._current_idx < 0:
            return
        if not self._apply_fields():
            return False
        entries = self._result['entries']
        src     = entries[self._current_idx]
        new_idx = len(entries)
        entries.append({
            'idx':      new_idx,
            'entry_id': self._new_entry_id(),
            'eff_a':    src['eff_a'],
            'eff_b':    src['eff_b'],
            'eff_c':    src['eff_c'],
            'eff_d':    src['eff_d'],
            'eff_e':    src['eff_e'],
        })
        self._result['entry_count'] = len(entries)
        self._mark_dirty()
        self._search.clear()
        self._populate_sidebar(self._search.text())
        self._select_entry(new_idx)
        self._sidebar_scroll.verticalScrollBar().setValue(
            self._sidebar_scroll.verticalScrollBar().maximum()
        )

    def _on_delete_entry(self):
        if self._result is None or self._current_idx < 0:
            return
        if not self._apply_fields():
            return False
        entries = self._result['entries']
        idx = self._current_idx
        if not (0 <= idx < len(entries)):
            return

        reply = QMessageBox.question(
            self, self._tr("ui_damageeff_delete_entry"),
            self._tr('dme_delete_warning', id=entries[idx]['entry_id']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del entries[idx]
        for i, e in enumerate(entries):
            e['idx']      = i
        self._result['entry_count'] = len(entries)
        self._mark_dirty()

        self._current_idx = -1
        self._populate_sidebar(self._search.text())

        new_idx = min(idx, len(entries) - 1)
        if new_idx >= 0:
            self._select_entry(new_idx)
        else:
            self._show_empty_selection()
            self._btn_del.setEnabled(False)
            self._btn_dup.setEnabled(False)
