import copy
import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    ss_bg_dark,
    ss_bg_panel,
    ss_accent_label,
    ss_btn,
    ss_dim_label,
    ss_entry_card,
    ss_field_label,
    ss_file_label,
    ss_file_label_loaded,
    ss_input,
    ss_placeholder,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_section_label,
    ss_sep,
    ss_search,
    ss_sidebar_btn,
    ss_sidebar_frame,
    ss_main_label,
    ss_transparent,
)
from core.editor_file_state import set_file_label
from parsers.sndcmnparam_parser import parse_sndcmnparam_xfbin, save_sndcmnparam_xfbin
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _fmt_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    return str(int(value)) if value == int(value) else f"{value:.4f}"


class SndCmnParamEditor(QWidget):
    _load_done = pyqtSignal(str, object, object)
    _load_error = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda key, **kw: key.format(**kw) if kw else key)

        self._filepath = None
        self._raw = None
        self._sections = []
        self._dirty = False
        self._category_buttons = []
        self._entry_cards = []
        self._fields = {}
        self._current_section_idx = None
        self._current_entry_idx = None

        self._load_done.connect(self._on_load_done)
        self._load_error.connect(self._on_load_error)

        self._build_ui()

    def _tr(self, key, fallback=None, **kwargs):
        text = self.t(key, **kwargs) if kwargs else self.t(key)
        return fallback if fallback is not None and text == key else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        self._open_btn = QPushButton(self._tr("btn_open_file", ui_text("btn_open_file")))
        self._open_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(self._open_btn)

        self._save_btn = QPushButton(self._tr("btn_save_file", ui_text("btn_save_file")))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_lbl = QLabel(self._tr("no_file_loaded", ui_text("ui_btladjprm_no_file_loaded")))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_lbl)
        top_layout.addStretch()
        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)

        main = QWidget()
        main.setStyleSheet(ss_bg_dark())
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(ss_sidebar_frame())
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(8, 8, 8, 4)
        list_layout.setSpacing(4)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self._tr("search_placeholder", ui_text("search_placeholder")))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(self._filter_cards)
        list_layout.addWidget(self._search_entry)

        actions_frame = QWidget()
        actions_frame.setStyleSheet(ss_transparent())
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_btn = QPushButton(self._tr("btn_new", ui_text("btn_new")))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self._tr("btn_duplicate", ui_text("btn_duplicate")))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self._tr("btn_delete", ui_text("btn_delete")))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_entry)
        actions_layout.addWidget(self._del_btn, 1)
        list_layout.addWidget(actions_frame)

        self._category_scroll = QScrollArea()
        self._category_scroll.setWidgetResizable(True)
        self._category_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._category_scroll.setStyleSheet(ss_scrollarea_transparent())

        self._category_widget = QWidget()
        self._category_widget.setStyleSheet(ss_transparent())
        self._category_layout = QVBoxLayout(self._category_widget)
        self._category_layout.setContentsMargins(0, 0, 0, 0)
        self._category_layout.setSpacing(1)
        self._category_layout.addStretch()
        self._category_scroll.setWidget(self._category_widget)
        list_layout.addWidget(self._category_scroll)

        main_layout.addWidget(list_frame)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())

        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)
        self._show_placeholder(ui_text("ui_sndcmnparam_open_a_sndcmnparam_xfbin_file_to_begin_editing"))

        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_sndcmnparam_open_sndcmnparam_xfbin"),
            game_files_dialog_dir(target_patterns=("sndcmnparam.xfbin", "sndcmnparam.bin.xfbin")),
            "Sound CMN Param files (sndcmnparam.xfbin *.xfbin);;All files (*.*)",
        )
        if not path:
            return
        create_backup_on_open(path)
        self._filepath = path
        self._file_lbl.setText(self._tr("loading", ui_text("loading")))
        self._file_lbl.setStyleSheet(ss_file_label())
        self._save_btn.setEnabled(False)
        self._set_action_state(False)
        self._clear_categories()
        self._show_placeholder(self._tr("loading", ui_text("loading")))

        def worker():
            try:
                raw, sections = parse_sndcmnparam_xfbin(path)
                self._load_done.emit(path, raw, sections)
            except Exception as exc:
                import traceback
                self._load_error.emit(f"{exc}\n{traceback.format_exc()}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_done(self, path, raw, sections):
        self._filepath = path
        self._raw = raw
        self._sections = sections
        self._dirty = False
        self._current_section_idx = 0 if sections else None
        self._current_entry_idx = 0 if sections and sections[0]["entries"] else None

        set_file_label(self._file_lbl, path)
        self._save_btn.setEnabled(True)
        self._populate_categories()
        self._select_category(self._current_section_idx)

    def _on_load_error(self, msg):
        self._raw = None
        self._sections = []
        self._current_section_idx = None
        self._current_entry_idx = None
        self._file_lbl.setText(self._tr("no_file_loaded", ui_text("ui_btladjprm_no_file_loaded")))
        self._file_lbl.setStyleSheet(ss_file_label())
        self._save_btn.setEnabled(False)
        self._set_action_state(False)
        self._clear_categories()
        self._show_placeholder(ui_text("ui_sndcmnparam_open_a_sndcmnparam_xfbin_file_to_begin_editing"))
        QMessageBox.critical(
            self,
            self._tr("dlg_title_error", ui_text("dlg_title_error")),
            self._tr("msg_load_error", ui_text("msg_load_error"), error=msg),
        )

    def _save_file(self):
        if not self._filepath or self._raw is None:
            return
        self._sync_visible_fields()
        try:
            save_sndcmnparam_xfbin(self._filepath, self._raw, self._sections)
            self._dirty = False
            set_file_label(self._file_lbl, self._filepath)
            self._raw, self._sections = parse_sndcmnparam_xfbin(self._filepath)
            self._populate_categories()
            self._select_category(self._current_section_idx)
            QMessageBox.information(
                self,
                self._tr("dlg_title_success", ui_text("dlg_title_success")),
                self._tr(
                    "msg_save_success",
                    ui_text("msg_save_success"),
                    path=os.path.basename(self._filepath),
                ),
            )
        except Exception as exc:
            import traceback
            QMessageBox.critical(
                self,
                self._tr("dlg_title_error", ui_text("dlg_title_error")),
                self._tr("msg_save_error", ui_text("msg_save_error"), error=f"{exc}\n{traceback.format_exc()}"),
            )

    def _clear_categories(self):
        _clear_layout(self._category_layout)
        self._category_layout.addStretch()
        self._category_buttons = []

    def _populate_categories(self):
        self._clear_categories()
        for idx, section in enumerate(self._sections):
            btn = self._make_category_button(idx, section)
            self._category_layout.insertWidget(self._category_layout.count() - 1, btn)
            self._category_buttons.append((btn, idx))
        self._refresh_category_styles()

    def _make_category_button(self, idx, section):
        btn = QPushButton()
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_section_idx))

        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(10, 3, 10, 3)
        btn_layout.setSpacing(0)

        name_lbl = QLabel(section["name"])
        name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(name_lbl)

        type_lbl = QLabel(self._section_type_label(section))
        type_lbl.setFont(QFont("Consolas", 11))
        type_lbl.setStyleSheet(ss_dim_label())
        type_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn_layout.addWidget(type_lbl)

        btn.clicked.connect(lambda checked=False, i=idx: self._select_category(i))
        return btn

    def _section_type_label(self, section):
        labels = {
            "sndcmnparam": ui_text("ui_sndcmnparam_audio_ids"),
            "pldata": ui_text("ui_sndcmnparam_character_sound"),
            "cridata": ui_text("ui_sndcmnparam_cri_libraries"),
        }
        return labels.get(section.get("type"), section.get("type", ""))

    def _select_category(self, idx):
        if idx is None or idx < 0 or idx >= len(self._sections):
            self._current_section_idx = None
            self._current_entry_idx = None
            self._show_placeholder(ui_text("ui_sndcmnparam_open_a_sndcmnparam_xfbin_file_to_begin_editing"))
            self._set_action_state(False)
            return
        self._sync_visible_fields()
        self._current_section_idx = idx
        section = self._sections[idx]
        if self._current_entry_idx is None or self._current_entry_idx >= len(section["entries"]):
            self._current_entry_idx = 0 if section["entries"] else None
        self._refresh_category_styles()
        self._build_entry_cards()
        self._update_action_state()

    def _refresh_category_styles(self):
        for btn, idx in self._category_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=idx == self._current_section_idx))

    def _show_placeholder(self, text):
        _clear_layout(self._editor_layout)
        self._fields = {}
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet(ss_placeholder())
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(lbl)
        self._editor_layout.addStretch()

    def _build_entry_cards(self):
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._entry_cards = []
        section = self._current_section()
        if not section:
            self._show_placeholder(ui_text("ui_sndcmnparam_open_a_sndcmnparam_xfbin_file_to_begin_editing"))
            return

        title = QLabel(section["name"])
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setStyleSheet(ss_accent_label())
        title.setContentsMargins(16, 12, 0, 4)
        self._editor_layout.addWidget(title)

        shown = 0
        query = self._search_entry.text().lower().strip()
        for idx, entry in enumerate(section["entries"]):
            if query and not self._matches_entry(section, entry, idx, query):
                continue
            card = self._make_entry_card(section, entry, idx)
            self._editor_layout.addWidget(card)
            self._entry_cards.append((card, idx))
            shown += 1

        if shown == 0:
            hint = QLabel(self._tr("no_matches", ui_text("ui_sndcmnparam_no_matches")))
            hint.setFont(QFont("Segoe UI", 16))
            hint.setStyleSheet(ss_placeholder())
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._editor_layout.addStretch()
            self._editor_layout.addWidget(hint)

        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet(ss_transparent())
        self._editor_layout.addWidget(spacer)
        self._editor_layout.addStretch()
        self._refresh_entry_card_styles()

    def _make_entry_card(self, section, entry, idx):
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(ss_entry_card(selected=idx == self._current_entry_idx))
        card.mousePressEvent = lambda event, i=idx: self._select_entry(i)

        layout = QGridLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(8)

        title = QLabel(self._entry_title(section, entry, idx))
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet(ss_section_label())
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title, 0, 0, 1, 3)

        subtitle = QLabel(self._entry_subtitle(section, entry))
        subtitle.setFont(QFont("Consolas", 11))
        subtitle.setStyleSheet(ss_dim_label())
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(subtitle, 0, 3)

        fields = self._fields_for_type(section["type"])
        for pos, field in enumerate(fields):
            key, label, kind = field
            row = 1 + pos // 3
            col = pos % 3
            colspan = 4 if len(fields) == 1 else 1
            self._add_field(layout, row, col, section, entry, idx, key, label, kind, colspan)
            layout.setColumnStretch(col, 1)

        return card

    def _fields_for_type(self, section_type):
        if section_type == "sndcmnparam":
            return [("audio_id", ui_text("ui_sndcmnparam_audio_id"), "str")]
        if section_type == "pldata":
            return [
                ("char_id", ui_text("ui_assist_char_id"), "str"),
                ("pl", ui_text("ui_sndcmnparam_se_file_pl"), "str"),
                ("null1", ui_text("ui_sndcmnparam_unused_null1"), "str"),
                ("spl", ui_text("ui_sndcmnparam_special_spl"), "str"),
                ("spl_interaction", ui_text("ui_sndcmnparam_spl_interact"), "str"),
                ("ev", ui_text("ui_sndcmnparam_event_ev"), "str"),
                ("stand_index", ui_text("ui_sndcmnparam_stand_idx"), "float"),
                ("unk2", ui_text("ui_customizedefaultparam_unk2"), "float"),
                ("unk3", ui_text("ui_sndcmnparam_unk3"), "float"),
                ("entity", ui_text("ui_sndcmnparam_entity"), "float"),
                ("char_index", ui_text("ui_sndcmnparam_char_idx"), "float"),
            ]
        return [
            ("float0", ui_text("ui_sndcmnparam_float_0"), "float"),
            ("float1", ui_text("ui_sndcmnparam_float_1"), "float"),
            ("float2", ui_text("ui_sndcmnparam_float_2"), "float"),
            ("float3", ui_text("ui_sndcmnparam_float_3"), "float"),
            ("str0", ui_text("ui_sndcmnparam_acf_archive"), "str"),
            ("str1", ui_text("ui_sndcmnparam_string_1"), "str"),
            ("str2", ui_text("ui_sndcmnparam_acb_sound"), "str"),
            ("str3", ui_text("ui_sndcmnparam_string_3"), "str"),
            ("str4", ui_text("ui_sndcmnparam_awb_stream"), "str"),
            ("flag", ui_text("ui_sndcmnparam_flag_u16"), "int"),
        ]

    def _add_field(self, layout, row, col, section, entry, idx, key, label, kind, colspan=1):
        frame = QWidget()
        frame.setStyleSheet(ss_transparent())
        field_layout = QVBoxLayout(frame)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(ss_field_label())
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        field_layout.addWidget(lbl)

        edit = QLineEdit()
        edit.setFixedHeight(30)
        edit.setFont(QFont("Consolas", 13))
        edit.setStyleSheet(ss_input())
        if kind == "str":
            edit.setMaxLength(32)
            edit.setText(str(entry.get(key, "")))
        elif kind == "int":
            edit.setText(str(entry.get(key, 0)))
        else:
            edit.setText(_fmt_float(entry.get(key, 0.0)))
        edit.textChanged.connect(lambda text, e=entry, k=key, t=kind, w=edit, i=idx: self._on_field_changed(e, k, t, w, i))
        edit.editingFinished.connect(lambda e=entry, k=key, t=kind, w=edit: self._coerce_field(e, k, t, w))
        field_layout.addWidget(edit)

        self._fields[(id(section), idx, key)] = (edit, entry, key, kind)
        layout.addWidget(frame, row, col, 1, colspan)

    def _on_field_changed(self, entry, key, kind, widget, idx):
        self._current_entry_idx = idx
        self._refresh_entry_card_styles()
        if kind == "str":
            entry[key] = widget.text()
            self._refresh_entry_titles(idx)
        else:
            try:
                entry[key] = int(widget.text(), 0) & 0xFFFF if kind == "int" else float(widget.text())
            except ValueError:
                return
        self._mark_dirty()

    def _coerce_field(self, entry, key, kind, widget):
        if kind == "str":
            entry[key] = widget.text()
            return
        try:
            if kind == "int":
                entry[key] = int(widget.text(), 0) & 0xFFFF
                widget.setText(str(entry[key]))
            else:
                entry[key] = float(widget.text())
                widget.setText(_fmt_float(entry[key]))
        except ValueError:
            widget.setText(str(entry.get(key, 0)) if kind == "int" else _fmt_float(entry.get(key, 0.0)))

    def _filter_cards(self):
        self._sync_visible_fields()
        self._build_entry_cards()
        self._update_action_state()

    def _matches_entry(self, section, entry, idx, query):
        values = [self._entry_title(section, entry, idx), self._entry_subtitle(section, entry)]
        values.extend(str(entry.get(key, "")) for key, _, _ in self._fields_for_type(section["type"]))
        return query in " ".join(values).lower()

    def _select_entry(self, idx):
        self._current_entry_idx = idx
        self._refresh_entry_card_styles()
        self._update_action_state()

    def _refresh_entry_card_styles(self):
        for card, idx in self._entry_cards:
            card.setStyleSheet(ss_entry_card(selected=idx == self._current_entry_idx))

    def _refresh_entry_titles(self, idx):
        for card, card_idx in self._entry_cards:
            if card_idx != idx:
                continue
            labels = card.findChildren(QLabel)
            section = self._current_section()
            if section and len(labels) >= 2 and idx < len(section["entries"]):
                entry = section["entries"][idx]
                labels[0].setText(self._entry_title(section, entry, idx))
                labels[1].setText(self._entry_subtitle(section, entry))
            break

    def _entry_title(self, section, entry, idx):
        if section["type"] == "sndcmnparam":
            return str(entry.get("audio_id", "")).strip() or f"Entry {idx:04d}"
        if section["type"] == "pldata":
            return str(entry.get("char_id", "")).strip() or f"Entry {idx:04d}"
        return str(entry.get("str2", "")).strip() or f"Entry {idx:04d}"

    def _entry_subtitle(self, section, entry):
        if section["type"] == "sndcmnparam":
            return ui_text("ui_sndcmnparam_audio_id")
        if section["type"] == "pldata":
            parts = [entry.get("pl", ""), entry.get("spl", ""), entry.get("ev", "")]
            return " / ".join(part for part in parts if str(part).strip()) or ui_text("ui_sndcmnparam_character_sound")
        parts = [entry.get("str0", ""), entry.get("str4", "")]
        return " / ".join(part for part in parts if str(part).strip()) or ui_text("ui_sndcmnparam_cri_libraries")

    def _current_section(self):
        if self._current_section_idx is None:
            return None
        if self._current_section_idx < 0 or self._current_section_idx >= len(self._sections):
            return None
        return self._sections[self._current_section_idx]

    def _sync_visible_fields(self):
        for widget, entry, key, kind in list(self._fields.values()):
            self._coerce_field(entry, key, kind, widget)

    def _mark_dirty(self):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=True)

    def _set_action_state(self, enabled):
        self._add_btn.setEnabled(enabled)
        self._dup_btn.setEnabled(False)
        self._del_btn.setEnabled(False)

    def _update_action_state(self):
        loaded = self._raw is not None and self._current_section() is not None
        selected = loaded and self._current_entry_idx is not None
        self._add_btn.setEnabled(loaded)
        self._dup_btn.setEnabled(selected)
        self._del_btn.setEnabled(selected)

    def _make_default_entry(self, section_type):
        if section_type == "sndcmnparam":
            return {"idx": 0, "audio_id": ui_text("ui_sndcmnparam_s_new_sound")}
        if section_type == "pldata":
            return {
                "idx": 0,
                "char_id": "0new01",
                "pl": "pl_new",
                "null1": "",
                "spl": "NULL",
                "spl_interaction": "NULL",
                "ev": "NULL",
                "stand_index": 0.0,
                "unk2": 0.0,
                "unk3": 0.0,
                "entity": 0.0,
                "char_index": 0.0,
            }
        return {
            "idx": 0,
            "float0": 0.0,
            "float1": 0.0,
            "float2": 0.0,
            "float3": 0.0,
            "str0": ui_text("ui_sndcmnparam_asb_acf"),
            "str1": "",
            "str2": "NULL",
            "str3": "",
            "str4": "NULL",
            "flag": 0xFFFF,
        }

    def _add_entry(self):
        section = self._current_section()
        if not section:
            return
        self._sync_visible_fields()
        entry = self._make_default_entry(section["type"])
        section["entries"].append(entry)
        self._renumber(section)
        self._current_entry_idx = len(section["entries"]) - 1
        self._search_entry.clear()
        self._build_entry_cards()
        self._mark_dirty()
        self._update_action_state()

    def _duplicate_entry(self):
        section = self._current_section()
        if not section or self._current_entry_idx is None:
            return
        if self._current_entry_idx < 0 or self._current_entry_idx >= len(section["entries"]):
            return
        self._sync_visible_fields()
        entry = copy.deepcopy(section["entries"][self._current_entry_idx])
        self._apply_copy_suffix(section, entry)
        section["entries"].append(entry)
        self._renumber(section)
        self._current_entry_idx = len(section["entries"]) - 1
        self._search_entry.clear()
        self._build_entry_cards()
        self._mark_dirty()
        self._update_action_state()

    def _delete_entry(self):
        section = self._current_section()
        if not section or self._current_entry_idx is None:
            return
        if self._current_entry_idx < 0 or self._current_entry_idx >= len(section["entries"]):
            return
        name = self._entry_title(section, section["entries"][self._current_entry_idx], self._current_entry_idx)
        result = QMessageBox.question(
            self,
            self._tr("dlg_title_confirm_delete", ui_text("dlg_title_confirm_delete")),
            self._tr("msg_confirm_delete_item", ui_text("msg_confirm_delete_item"), name=name),
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._sync_visible_fields()
        del section["entries"][self._current_entry_idx]
        self._renumber(section)
        if section["entries"]:
            self._current_entry_idx = min(self._current_entry_idx, len(section["entries"]) - 1)
        else:
            self._current_entry_idx = None
        self._build_entry_cards()
        self._mark_dirty()
        self._update_action_state()

    def _apply_copy_suffix(self, section, entry):
        suffix = self._tr("msg_copy_suffix", ui_text("msg_copy_suffix"))
        if section["type"] == "sndcmnparam":
            key = "audio_id"
        elif section["type"] == "pldata":
            key = "char_id"
        else:
            key = "str2"
        entry[key] = f"{entry.get(key, '')}{suffix}"[:32]

    def _renumber(self, section):
        for idx, entry in enumerate(section["entries"]):
            entry["idx"] = idx
