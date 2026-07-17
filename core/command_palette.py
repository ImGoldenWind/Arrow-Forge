from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from core.style_helpers import ss_dialog, ss_input, ss_table
from core.themes import P


@dataclass
class Command:
    id: str
    label: str
    keywords: tuple[str, ...]
    enabled: bool
    run: Callable[[], None]
    shortcut: str = ""


class CommandPalette(QDialog):
    def __init__(self, parent, title: str, placeholder: str, commands: list[Command]):
        super().__init__(parent)
        self._commands = commands
        self._visible_commands: list[Command] = []
        self._selected_command: Command | None = None

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(620, 460)
        self.setStyleSheet(ss_dialog())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._entry = QLineEdit(self)
        self._entry.setPlaceholderText(placeholder)
        self._entry.setFixedHeight(34)
        self._entry.setFont(QFont("Segoe UI", 12))
        self._entry.setStyleSheet(ss_input())
        self._entry.textChanged.connect(self._refresh)
        self._entry.returnPressed.connect(self._accept_current)
        layout.addWidget(self._entry)

        self._list = QListWidget(self)
        self._list.setStyleSheet(ss_table())
        self._list.itemDoubleClicked.connect(lambda _item: self._accept_current())
        self._list.currentRowChanged.connect(self._sync_selection)
        layout.addWidget(self._list, 1)

        hint = QLabel(parent.t("command_palette_hint") if hasattr(parent, "t") else "", self)
        hint.setFont(QFont("Segoe UI", 10))
        hint.setStyleSheet(f"color: {P['text_dim']}; border: none; background: transparent;")
        layout.addWidget(hint)

        self._refresh()
        self._entry.setFocus(Qt.FocusReason.PopupFocusReason)

    def _refresh(self):
        query = self._entry.text().strip().lower()
        self._list.clear()
        self._visible_commands = []
        for command in self._commands:
            haystack = " ".join((command.label, command.id, *command.keywords)).lower()
            if query and query not in haystack:
                continue
            self._visible_commands.append(command)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, command.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
            if not command.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(item)
            self._list.setItemWidget(item, self._make_row(command))
        if self._list.count():
            self._list.setCurrentRow(0)

    def _make_row(self, command: Command):
        row = QLabel(command.label if not command.shortcut else f"{command.label}    {command.shortcut}", self._list)
        row.setFont(QFont("Segoe UI", 11))
        color = P["text_main"] if command.enabled else P["text_dim"]
        row.setStyleSheet(f"color: {color}; padding: 7px 8px; background: transparent; border: none;")
        return row

    def _sync_selection(self, row: int):
        if 0 <= row < len(self._visible_commands):
            self._selected_command = self._visible_commands[row]
        else:
            self._selected_command = None

    def _accept_current(self):
        command = self._selected_command
        if command is None or not command.enabled:
            return
        self.accept()
        command.run()
