"""editors/damageprm_editor.py  –  Editor for damageprm.bin.xfbin (Hit Reactions)."""

from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_editor_grid_card,
    make_empty_state,
    ss_bg_dark,
    ss_dim_label,
    ss_error_label,
    ss_main_label,
    ss_sidebar_btn,
    ss_transparent,
)
from core.ui.editor_widgets import (
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
from core.ui.editor_actions import install_file_actions
import os
import math
import struct

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog, QMessageBox, QLineEdit, QSizePolicy, QComboBox, QCompleter,
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QFont

from core.editor_file_state import set_file_label
from parsers.damageprm_parser import parse_damageprm_xfbin, save_damageprm_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.hit_reactions import reaction_name, entry_name
from parsers.damageprm_parser import FIELD_LAYOUT

# Keep storage keys for compatibility; captions describe native uses, not guesses.
_FIELD_GROUPS = (
    ('reaction', ('reaction',)),
    ('parameters', ('launch_x', 'launch_y', 'hitstun', 'recovery')),
    ('technical', ('flag', 'sub_react')),
)


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


class DamagePrmEditor(QWidget):
    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t           = t or (lambda k, **kw: k)
        self._embedded    = embedded
        self._filepath    = None
        self._raw         = None
        self._result      = None
        self._dirty       = False
        self._current_idx = -1
        self._entry_buttons = []
        self._last_compact: bool | None = None
        self._field_widgets = {}  # key -> (input widget, optional hint)

        self._last_columns = None
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

        div = EditorSeparator(orientation=Qt.Orientation.Vertical)


        body.addWidget(div)

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

        self._btn_save_as = QPushButton(self._tr('hit_save_as'))
        configure_button(self._btn_save_as)
        self._btn_save_as.setEnabled(False)
        self._btn_save_as.clicked.connect(self._on_save_as)
        lo.addWidget(self._btn_save_as)
        lo.addStretch(1)

        self._file_lbl = QLabel(self._tr("xfa_no_file"))

        configure_file_label(self._file_lbl)
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lo.addWidget(self._file_lbl)

    def _build_sidebar(self, frame):
        lo = frame.content_layout

        self._search = QLineEdit()
        configure_search(self._search)
        self._search.setClearButtonEnabled(True)
        configure_search(self._search)
        self._search.textChanged.connect(self._on_search)
        lo.addWidget(self._search)
        self._reaction_filter = EditorFilterCombo()
        configure_input(self._reaction_filter)
        self._reaction_filter.setMinimumWidth(0)
        self._reaction_filter.addItem(self._tr('hit_all_reactions'), None)
        self._reaction_filter.currentIndexChanged.connect(lambda: self._on_search(self._search.text()))
        lo.addWidget(self._reaction_filter)

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
        btn.setFixedHeight(Size.LIST_ROW)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._current_idx)))

        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.setStyleSheet(ss_transparent())
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(10, 4, 10, 4)
        vl.setSpacing(1)

        name_text = entry_name(entry, self._tr)
        name_lbl = QLabel(_truncate(name_text, 24))
        name_lbl.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        name_lbl.setToolTip(name_text + '\n' + entry['name'])
        vl.addWidget(name_lbl)

        id_text = f"{entry['idx']:02d} · {entry['name'].removeprefix('DAMAGE_ID_')}"
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

        btn.setProperty('entry_index', idx)
        btn.installEventFilter(self)
        btn.setToolTip(entry['name'] + '\n' + reaction_name(entry['reaction'], self._tr))
        btn.clicked.connect(lambda checked, i=idx: self._select_entry(i))
        return btn

    def _populate_sidebar(self, filter_text=""):
        ft = filter_text.strip().casefold()
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

        reaction = self._reaction_filter.currentData()
        for idx, entry in enumerate(self._result['entries']):
            text = ' '.join((entry['name'], entry_name(entry, self._tr), str(idx),
                             str(entry['reaction']), reaction_name(entry['reaction'], self._tr))).casefold()
            if (ft and ft not in text) or (reaction is not None and entry['reaction'] != reaction):
                continue
            btn = self._make_entry_button(entry, idx)
            self._sidebar_list.insertWidget(self._sidebar_list.count() - 1, btn)
            self._entry_buttons.append((idx, btn))

    def eventFilter(self, watched, event):
        if isinstance(watched, QComboBox) and event.type() == QEvent.Type.Wheel and not watched.hasFocus():
            event.ignore()
            return True
        if event.type() == QEvent.Type.KeyPress and watched.property('entry_index') is not None:
            rows = [i for i, _ in self._entry_buttons]
            index = watched.property('entry_index')
            if index in rows and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
                pos = rows.index(index)
                if event.key() == Qt.Key.Key_Home:
                    pos = 0
                elif event.key() == Qt.Key.Key_End:
                    pos = len(rows) - 1
                else:
                    pos = max(0, min(len(rows) - 1, pos + (1 if event.key() == Qt.Key.Key_Down else -1)))
                if self._select_entry(rows[pos]):
                    self._entry_buttons[pos][1].setFocus()
                    self._sidebar_scroll.ensureWidgetVisible(self._entry_buttons[pos][1])
                return True
        return super().eventFilter(watched, event)

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
            text=self._tr("ui_damageprm_open_a_damageprm_bin_xfbin_file_to_begin_editing"),
            icon_name="fa6s.burst",
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

    def _choice(self, value, options):
        inp = QComboBox()
        inp.setEditable(True)
        inp.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        inp.setMaxVisibleItems(14)
        for number, caption in options:
            inp.addItem(f"{number} · {caption}", number)
        index = inp.findData(value)
        if index < 0:
            inp.addItem(f"{value} · {self._tr('hit_custom')}", value)
            index = inp.count() - 1
        inp.setCurrentIndex(index)
        inp.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        inp.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        inp.installEventFilter(self)
        inp.lineEdit().setPlaceholderText(self._tr('hit_custom_hint'))
        inp.currentIndexChanged.connect(self._mark_dirty)
        inp.lineEdit().textEdited.connect(self._mark_dirty)
        return inp

    def _build_editor(self, entry):
        _clear_layout(self._main_layout)
        self._field_widgets = {}
        self._last_compact = self._is_compact_editor()
        self._last_columns = self._grid_columns(2)
        card, lo = make_editor_card(self._main_inner)
        self._prep_card(card)
        add_editor_card_title(lo, entry_name(entry, self._tr), 'fa6s.burst', entry['name'])
        note = QLabel(self._tr('hit_intro'))
        note.setStyleSheet(ss_dim_label())
        note.setWordWrap(True)
        lo.addWidget(note)
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(ss_error_label())
        self._error_label.hide()
        lo.addWidget(self._error_label)
        self._add_editor_card(card)
        for group, keys in _FIELD_GROUPS:
            card, grid = make_editor_grid_card(self._main_inner, title=self._tr('hit_group_' + group), icon_name='fa6s.sliders' if group != 'reaction' else 'fa6s.burst')
            self._prep_card(card)
            for i, key in enumerate(keys):
                value = entry[key]
                hint = self._tr('hit_hint_' + key)
                field, layout, label, _ = make_editor_field_shell(self._tr('hit_field_' + key))
                self._prep_field_widget(field)
                label.setToolTip(hint)
                if key == 'reaction':
                    inp = self._choice(value, [(i, reaction_name(i, self._tr)) for i in range(28)])
                else:
                    inp = QLineEdit(format(value, '.9g') if FIELD_LAYOUT[key][1] == 'f' else str(value))
                    inp.textEdited.connect(self._mark_dirty)
                configure_input(inp, monospace=False)
                inp.setToolTip(hint + ('\n' + self._tr('hit_custom_hint') if isinstance(inp, QComboBox) else ''))
                inp.setMinimumWidth(0)
                inp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                if isinstance(inp, QLineEdit):
                    inp.setCursorPosition(0)
                layout.addWidget(inp)
                help_label = QLabel(hint)
                help_label.setWordWrap(True)
                help_label.setStyleSheet(ss_dim_label())
                help_label.setFont(ui_font(TypeSize.BODY))
                help_label.setMinimumWidth(0)
                layout.addWidget(help_label)
                row, col = divmod(i, self._last_columns)
                grid.addWidget(field, row, col, alignment=Qt.AlignmentFlag.AlignTop)
                grid.setColumnStretch(col, 1)
                self._field_widgets[key] = (inp, help_label)
            self._add_editor_card(card)
        self._main_layout.addStretch(1)
        QTimer.singleShot(0, self._fit_card_heights)

    def _fit_card_heights(self, settled=False):
        # QScrollArea otherwise uses the unwrapped minimum hints, leaving large
        # empty scroll tails after the labels have wrapped to their actual width.
        width = max(100, self._main_scroll.viewport().width() - 24)
        for index in range(self._main_layout.count()):
            card = self._main_layout.itemAt(index).widget()
            if not isinstance(card, QFrame) or card.layout() is None:
                continue
            for child in card.findChildren(QWidget):
                if child.layout() is not None:
                    child.layout().invalidate()
            card.layout().invalidate()
            height = card.layout().totalHeightForWidth(min(width, card.maximumWidth()))
            if height > 0:
                card.setFixedHeight(height)
        self._main_layout.invalidate()
        if not settled:
            QTimer.singleShot(0, lambda: self._fit_card_heights(True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_idx >= 0 and self._last_compact is not None:
            QTimer.singleShot(0, self._maybe_rebuild_for_compact)

    def _maybe_rebuild_for_compact(self):
        if self._current_idx < 0 or self._result is None:
            return
        compact = self._is_compact_editor()
        if compact == self._last_compact and self._grid_columns(2) == self._last_columns:
            self._fit_card_heights()
            return
        if not self._apply_fields():
            self._fit_card_heights()
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
        entry = self._result['entries'][self._current_idx]
        candidate = {}
        for key, (_, help_label) in self._field_widgets.items():
            help_label.setText(self._tr('hit_hint_' + key))
            help_label.setStyleSheet(ss_dim_label())
        for key, (inp, help_label) in self._field_widgets.items():
            try:
                if isinstance(inp, QComboBox):
                    index = inp.currentIndex()
                    value = (inp.itemData(index) if index >= 0 and inp.currentText() == inp.itemText(index)
                             else self._parse_int(inp.currentText()))
                elif FIELD_LAYOUT[key][1] == 'f':
                    value = float(inp.text().strip().replace(',', '.'))
                    if not math.isfinite(value):
                        if inp.text() == format(entry[key], '.9g'):
                            value = entry[key]
                        else:
                            raise ValueError()
                    else:
                        value = struct.unpack('<f', struct.pack('<f', value))[0]
                        if not math.isfinite(value):
                            raise ValueError()
                else:
                    value = self._parse_int(inp.text())
                if FIELD_LAYOUT[key][1] == 'I' and not 0 <= value <= 0xFFFFFFFF:
                    raise ValueError()
                if FIELD_LAYOUT[key][1] == 'i' and not -0x80000000 <= value <= 0x7FFFFFFF:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError, struct.error):
                error = self._tr('hit_invalid', field=self._tr('hit_field_' + key))
                self._error_label.setText(error)
                self._error_label.show()
                help_label.setText(error)
                help_label.setStyleSheet(ss_error_label())
                self._fit_card_heights()
                inp.setFocus()
                if isinstance(inp, QLineEdit):
                    inp.selectAll()
                else:
                    inp.lineEdit().selectAll()
                self._main_scroll.ensureWidgetVisible(inp)
                return False
            candidate[key] = value
        changed = any(not (candidate[k] == entry[k] or
                      isinstance(candidate[k], float) and math.isnan(candidate[k]) and math.isnan(entry[k]))
                      or (candidate[k] == 0 and isinstance(candidate[k], float) and
                          math.copysign(1, candidate[k]) != math.copysign(1, entry[k])) for k in candidate)
        entry.update(candidate)
        self._error_label.hide()
        self._fit_card_heights()
        if changed:
            self._mark_dirty()
            self._populate_sidebar(self._search.text())
        return True

    @staticmethod
    def _parse_int(text):
        text = text.strip()
        return int(text, 16) if text.lower().startswith('0x') else int(text, 10)

    def _select_entry(self, idx):
        if not self._apply_fields():
            return False
        if self._result is None or not 0 <= idx < len(self._result['entries']):
            return False
        self._current_idx = idx
        self._refresh_sidebar_styles()
        self._build_editor(self._result['entries'][idx])
        self._main_scroll.verticalScrollBar().setValue(0)
        return True

    # Search

    def _on_search(self, text):
        self._populate_sidebar(filter_text=text)

    # Data loading

    def _load_file(self, filepath):
        if not self._confirm_discard():
            return False
        try:
            raw, result = parse_damageprm_xfbin(filepath)
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

        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._reaction_filter.blockSignals(True)
        self._reaction_filter.clear()
        self._reaction_filter.addItem(self._tr('hit_all_reactions'), None)
        for value in sorted(set(range(28)) | {e['reaction'] for e in result['entries']}):
            self._reaction_filter.addItem(f'{value} · {reaction_name(value, self._tr)}', value)
        self._reaction_filter.blockSignals(False)
        self._populate_sidebar()
        if self._result.get('entries'):
            self._select_entry(0)
        else:
            self._show_empty_selection()

        set_file_label(self._file_lbl, filepath)
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        return True

    # File I/O

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("ui_damageprm_open_damageprm_bin_xfbin"), game_files_dialog_dir(target_patterns="damageprm.bin.xfbin"),
            "XFBIN Files (damageprm.bin.xfbin);;All Files (*.*)"
        )
        if path:
            self._load_file(path)

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

    def _on_save(self):
        if not self._filepath or self._raw is None:
            return False
        return self._save_to(self._filepath)

    def _on_save_as(self):
        if self._raw is None or not self._apply_fields():
            return False
        path, _ = QFileDialog.getSaveFileName(self, self._tr('hit_save_as'), self._filepath,
                                             'XFBIN Files (*.xfbin);;All Files (*)')
        return self._save_to(path) if path else False

    def _save_to(self, filepath):
        if not self._apply_fields():
            return False
        try:
            save_damageprm_xfbin(filepath, self._raw, self._result)
            raw, result = parse_damageprm_xfbin(filepath)
            self._raw, self._result = raw, result
            self._filepath = str(filepath)
            self._dirty = False
            set_file_label(self._file_lbl, str(filepath))
            QMessageBox.information(self, self._tr('ui_assist_saved'),
                                    self._tr('ui_assist_file_saved_value', p0=os.path.basename(filepath)))
            return True
        except Exception as exc:
            QMessageBox.critical(self, self._tr('ui_assist_save_error'), self._tr('ui_assist_failed_to_save_value', p0=exc))
            return False
