"""Searchable file-backed choices with lossless custom text entry."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QCompleter

from core.ui.editor_widgets import configure_input


class EditorValueCombo(QComboBox):
    @staticmethod
    def choice_model(choices, parent=None):
        """A reusable read-only suggestion model; callers own its lifetime/cache."""
        model = QStandardItemModel(parent)
        for key, caption in choices:
            item = QStandardItem(str(caption))
            item.setData(str(key), Qt.ItemDataRole.UserRole)
            model.appendRow(item)
        return model

    def __init__(self, choices, value, parent=None, *, model=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(1)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setProperty('messageReference', False)
        configure_input(self)
        if model is None:
            for key, caption in choices:
                self.addItem(str(caption), str(key))
        else:
            self.setModel(model)
        index = self.findData(str(value))
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setCurrentIndex(-1)
            self.setEditText(str(value))
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def value_text(self):
        index = self.currentIndex()
        if index >= 0 and self.currentText() == self.itemText(index):
            return str(self.itemData(index))
        return self.currentText()
