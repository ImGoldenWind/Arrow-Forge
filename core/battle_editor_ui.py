"""Shared themed controls for the Battle Results and Battle Rewards editors."""
from core.design_tokens import (
    LayoutRole,
)
from core.style_helpers import (
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorFilterCombo,
    configure_input,
    configure_layout,
    configure_search,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

from core.translations import ui_text


class BattleListFilter(QWidget):
    changed = pyqtSignal()

    def __init__(self, search, parent=None):
        super().__init__(parent)
        self.setStyleSheet(ss_transparent())
        self.search = search
        search.setClearButtonEnabled(True)
        configure_search(search)
        layout = QVBoxLayout(self)
        configure_layout(layout, LayoutRole.FIELD)
        self.combo = EditorFilterCombo()
        configure_input(self.combo, monospace=False)
        self.combo.setMinimumContentsLength(1)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setAccessibleName(ui_text('battle_filter'))
        self.combo.addItem(ui_text('battle_filter_all'), None)
        self.combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        layout.addWidget(self.combo)
    def set_options(self, options):
        previous = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(ui_text('battle_filter_all'), None)
        for value, text in options:
            self.combo.addItem(text, value)
        self.combo.setCurrentIndex(max(0, self.combo.findData(previous)))
        self.combo.blockSignals(False)

    def clear(self):
        self.search.clear()
        self.combo.setCurrentIndex(0)
        self.changed.emit()

    def accepts(self, value):
        return self.combo.currentData() is None or self.combo.currentData() == value
