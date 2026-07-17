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
    ShortcutAction("editor.undo", "shortcut_action_editor_undo", "shortcuts_group_editor", "editor", ("Ctrl+Z",)),
    ShortcutAction("editor.redo", "shortcut_action_editor_redo", "shortcuts_group_editor", "editor", ("Ctrl+Y", "Ctrl+Shift+Z")),
    ShortcutAction("editor.new", "shortcut_action_editor_new", "shortcuts_group_editor", "editor", ("Ctrl+N",)),
    ShortcutAction("editor.duplicate", "shortcut_action_editor_duplicate", "shortcuts_group_editor", "editor", ("Ctrl+D",)),
    ShortcutAction("editor.delete", "shortcut_action_editor_delete", "shortcuts_group_editor", "editor", ("Delete",)),
)


ACTION_BY_ID = {action.action_id: action for action in SHORTCUT_ACTIONS}
TEXT_NATIVE_ACTIONS = {"editor.undo", "editor.redo", "editor.delete"}
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


class ShortcutManager(QObject):
    def __init__(self, app_window):
        super().__init__(app_window)
        self._app_window = app_window
        self._sequence_to_actions: dict[str, list[str]] = {}
        self.reload()
        QApplication.instance().installEventFilter(self)

    def reload(self):
        shortcuts = normalize_shortcut_settings(self._app_window._settings.get("shortcuts", {}))
        self._app_window._settings["shortcuts"] = shortcuts
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

        sequence = normalize_sequence(QKeySequence(event.keyCombination()))
        action_ids = self._sequence_to_actions.get(sequence, [])
        if not action_ids:
            return False

        handler = getattr(self._app_window, "_handle_shortcut_action", None)
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
