from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QKeySequenceEdit,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)


@dataclass(frozen=True)
class ShortcutAction:
    action_id: str
    label_key: str
    group_key: str
    context: str
    defaults: tuple[str, ...]


SHORTCUT_ACTIONS: tuple[ShortcutAction, ...] = (
    ShortcutAction("app.back", "shortcut_action_app_back", "shortcuts_group_application", "app", ("Alt+Left", "Esc")),
    ShortcutAction("app.command_palette", "shortcut_action_app_command_palette", "shortcuts_group_application", "app", ("Ctrl+Shift+P",)),
    ShortcutAction("app.settings", "shortcut_action_app_settings", "shortcuts_group_application", "app", ("Ctrl+,",)),
    ShortcutAction("app.tool_search", "shortcut_action_app_tool_search", "shortcuts_group_application", "app", ("Ctrl+K",)),
    ShortcutAction("editor.focus_search", "shortcut_action_editor_focus_search", "shortcuts_group_editor", "editor", ("Ctrl+F",)),
    ShortcutAction("editor.open", "shortcut_action_editor_open", "shortcuts_group_editor", "editor", ("Ctrl+O",)),
    ShortcutAction("editor.save", "shortcut_action_editor_save", "shortcuts_group_editor", "editor", ("Ctrl+S",)),
    ShortcutAction("editor.save_as", "btn_save_as", "shortcuts_group_editor", "editor", ("Ctrl+Shift+S",)),
    ShortcutAction("editor.compare", "qol_compare_from_file", "shortcuts_group_editor", "editor", ()),
    ShortcutAction("editor.clear_filters", "filters_clear", "shortcuts_group_editor", "editor", ("Ctrl+Shift+F",)),
    ShortcutAction("editor.toggle_sidebar", "shortcut_action_toggle_sidebar", "shortcuts_group_editor", "editor", ("Ctrl+B",)),
    ShortcutAction("editor.toggle_preview", "shortcut_action_toggle_preview", "shortcuts_group_editor", "editor", ("Ctrl+Shift+B",)),
    ShortcutAction("editor.copy", "credit_support_copy", "shortcuts_group_editor", "editor", ("Ctrl+C",)),
    ShortcutAction("editor.next", "shortcut_action_next_entry", "shortcuts_group_editor", "editor", ("Alt+Down",)),
    ShortcutAction("editor.previous", "shortcut_action_previous_entry", "shortcuts_group_editor", "editor", ("Alt+Up",)),
    ShortcutAction("editor.undo", "shortcut_action_editor_undo", "shortcuts_group_editor", "editor", ("Ctrl+Z",)),
    ShortcutAction("editor.redo", "shortcut_action_editor_redo", "shortcuts_group_editor", "editor", ("Ctrl+Y", "Ctrl+Shift+Z")),
    ShortcutAction("editor.new", "shortcut_action_editor_new", "shortcuts_group_editor", "editor", ("Ctrl+N",)),
    ShortcutAction("editor.duplicate", "shortcut_action_editor_duplicate", "shortcuts_group_editor", "editor", ("Ctrl+D",)),
    ShortcutAction("editor.delete", "shortcut_action_editor_delete", "shortcuts_group_editor", "editor", ("Delete",)),
)


ACTION_BY_ID = {action.action_id: action for action in SHORTCUT_ACTIONS}
TEXT_NATIVE_ACTIONS = {"editor.undo", "editor.redo", "editor.delete", "editor.copy"}
MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
}


def normalize_sequence(sequence) -> str:
    if sequence is None:
        return ""
    if isinstance(sequence, QKeySequence):
        key_sequence = sequence
    else:
        key_sequence = QKeySequence(str(sequence).strip())
    return key_sequence.toString(QKeySequence.SequenceFormat.PortableText)


def default_shortcut_settings() -> dict[str, list[str]]:
    return {
        action.action_id: [normalize_sequence(sequence) for sequence in action.defaults]
        for action in SHORTCUT_ACTIONS
    }


def normalize_shortcut_settings(value) -> dict[str, list[str]]:
    defaults = default_shortcut_settings()
    if not isinstance(value, dict):
        return defaults

    reserved = {}
    for action in SHORTCUT_ACTIONS:
        raw = value.get(action.action_id, [])
        raw = [raw] if isinstance(raw, str) else raw
        if isinstance(raw, list):
            for sequence in raw[:2]:
                normalized = normalize_sequence(sequence)
                if normalized:
                    reserved.setdefault((action.context, normalized), set()).add(action.action_id)
    result: dict[str, list[str]] = {}
    for action in SHORTCUT_ACTIONS:
        raw_sequences = value.get(action.action_id, defaults[action.action_id])
        if isinstance(raw_sequences, str):
            raw_sequences = [raw_sequences]
        if not isinstance(raw_sequences, list):
            raw_sequences = defaults[action.action_id]
        sequences = []
        for raw_sequence in raw_sequences[:2]:
            sequence = normalize_sequence(raw_sequence)
            if (action.action_id not in value and
                    reserved.get((action.context, sequence), set()) - {action.action_id}):
                continue
            if sequence and sequence not in sequences:
                sequences.append(sequence)
        result[action.action_id] = sequences
    return result


def find_shortcut_conflict(shortcuts: dict[str, list[str]]):
    seen: dict[tuple[str, str], str] = {}
    for action in SHORTCUT_ACTIONS:
        for sequence in shortcuts.get(action.action_id, []):
            normalized = normalize_sequence(sequence)
            if not normalized:
                continue
            key = (action.context, normalized)
            existing = seen.get(key)
            if existing and existing != action.action_id:
                return normalized, existing, action.action_id
            seen[key] = action.action_id
    return None


class _EditorShortcutVisibility(QObject):
    """Observe one editor; only visible standalone windows need an app filter."""
    def __init__(self, manager):
        super().__init__(manager)
        self.manager = manager
        manager._editor.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.manager._update_editor_visibility()
        return False


class ShortcutManager(QObject):
    def __init__(self, app_window, *, editor=None, settings=None):
        super().__init__(app_window)
        self._app_window = app_window
        self._editor = editor
        self._standalone_settings = settings
        self._installed = False
        self._sequence_to_actions: dict[str, list[str]] = {}
        self.reload()
        if editor is None:
            self._set_active(True)
        else:
            self._visibility = _EditorShortcutVisibility(self)
            editor.objectNameChanged.connect(self._update_editor_visibility)
            self._update_editor_visibility()

    def _set_active(self, active):
        if active == self._installed:
            return
        app = QApplication.instance()
        if active:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._installed = active

    def _update_editor_visibility(self, *args):
        self._set_active(self._editor.isVisible() and self._editor.objectName() != "EmbeddedToolEditor")

    def reload(self):
        settings = self._standalone_settings if self._editor is not None else self._app_window._settings
        shortcuts = normalize_shortcut_settings(settings.get("shortcuts", {}))
        settings["shortcuts"] = shortcuts
        self._sequence_to_actions = {}
        for action_id, sequences in shortcuts.items():
            for sequence in sequences:
                normalized = normalize_sequence(sequence)
                if normalized:
                    self._sequence_to_actions.setdefault(normalized, []).append(action_id)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() in MODIFIER_KEYS or event.key() == Qt.Key.Key_unknown:
            return False
        if self._focus_is_shortcut_editor():
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        if self._editor is not None:
            if self._editor.objectName() == "EmbeddedToolEditor" or not self._editor.isVisible():
                return False
            focus = QApplication.focusWidget()
            if focus is None or (focus is not self._editor and not self._editor.isAncestorOf(focus)):
                return False

        sequence = normalize_sequence(QKeySequence(event.keyCombination()))
        action_ids = self._sequence_to_actions.get(sequence, [])
        if not action_ids:
            return False

        handler = (lambda action: trigger_editor_action(self._editor, action)) if self._editor is not None else getattr(self._app_window, "_handle_shortcut_action", None)
        if not callable(handler):
            return False
        for action_id in self._ordered_actions(action_ids):
            if action_id in TEXT_NATIVE_ACTIONS and self._focus_is_text_editor():
                continue
            if handler(action_id):
                return True
        return False

    def _ordered_actions(self, action_ids: list[str]) -> list[str]:
        has_editor = getattr(self._app_window, "_embedded_editor", None) is not None
        if has_editor:
            return sorted(action_ids, key=lambda action_id: 0 if action_id.startswith("editor.") else 1)
        return sorted(action_ids, key=lambda action_id: 0 if action_id.startswith("app.") else 1)

    @staticmethod
    def _focus_is_shortcut_editor() -> bool:
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, QKeySequenceEdit):
                return True
            widget = widget.parentWidget()
        return False

    @staticmethod
    def _focus_is_text_editor() -> bool:
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return True
            if isinstance(widget, QComboBox) and widget.isEditable():
                return True
            widget = widget.parentWidget()
        return False



def install_editor_shortcuts(editor):
    """Reuse the settings-backed manager for standalone editor windows too."""
    if hasattr(editor, "_editor_shortcut_manager"):
        return
    from core.settings import load_settings
    editor._editor_shortcut_manager = ShortcutManager(editor, editor=editor, settings=load_settings())


def trigger_editor_action(editor, action_id):
    """Dispatch existing UI commands; never implement editing algorithms here."""
    if editor is None:
        return False
    custom = getattr(editor, "shortcut_action", None)
    if callable(custom) and custom(action_id):
        return True
    from PyQt6.QtWidgets import QPushButton
    from core.ui.editor_widgets import EditorListRow
    from core.ui.editor_chrome import EditorSidebarPane
    if action_id == "editor.focus_search":
        fields = [w for w in editor.findChildren(QLineEdit)
                  if w.property("designControlRole") == "search" and w.isVisible() and w.isEnabled()]
        if not fields:
            panes = [p for p in editor.findChildren(EditorSidebarPane) if p.label == "sidebar" and p.isVisible()]
            for pane in panes:
                candidates = [w for w in pane.findChildren(QLineEdit)
                              if w.property("designControlRole") == "search" and w.isEnabled()]
                if candidates:
                    if pane.sidebar.isHidden():
                        pane.toggle()
                    fields = candidates
                    break
        if fields:
            fields[0].setFocus()
            fields[0].selectAll()
            return True
        return False
    if action_id in ("editor.toggle_sidebar", "editor.toggle_preview"):
        label = "preview" if action_id.endswith("preview") else "sidebar"
        panes = [p for p in editor.findChildren(EditorSidebarPane) if p.label == label and p.isVisible()]
        if panes:
            panes[0].button.click()
            return True
        return False
    if action_id in ("editor.next", "editor.previous"):
        from core.ui.record_list import EditorRecordList
        catalogs = [w for w in editor.findChildren(EditorRecordList) if w.isVisible() and w.isEnabled()]
        if catalogs:
            catalog = next((w for w in catalogs if w.hasFocus()), catalogs[0])
            count = catalog.model().rowCount()
            if not count:
                return False
            step = 1 if action_id.endswith("next") else -1
            row = max(0, min(count - 1, catalog.currentIndex().row() + step))
            catalog.setCurrentIndex(catalog.model().index(row, 0))
            # The form owner can reject a change to retain incomplete input.
            catalog.scrollTo(catalog.currentIndex())
            return True
        from core.style_helpers import ss_sidebar_btn
        rows = [w for w in editor.findChildren(EditorListRow) if w.isVisible() and w.isEnabled()]
        if not rows:
            return False
        selected = next((i for i, row in enumerate(rows) if row.styleSheet() == ss_sidebar_btn(True)), -1)
        step = 1 if action_id.endswith("next") else -1
        rows[max(0, min(len(rows) - 1, selected + step))].click()
        return True
    action = action_id.removeprefix("editor.")
    buttons = [button for button in editor.findChildren(QPushButton)
               if button.property("designAction") == action and button.isVisible() and button.isEnabled()]
    if action == "save":
        manager = getattr(editor, "_file_actions", None)
        button = getattr(manager, "save_button", None)
        buttons = [button] if button is not None and button.isVisible() and button.isEnabled() else []
    if buttons:
        buttons[0].click()
        return True
    return False
