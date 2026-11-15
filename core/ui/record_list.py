"""Model-backed sidebar made from the existing EditorListRow widgets.

Only visible rows are instantiated. Geometry, typography and interaction states
belong to EditorListRow; this adapter only binds records and manages scrolling.
"""
from PyQt6.QtCore import QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex, Qt
from PyQt6.QtWidgets import QScrollArea, QWidget

from core.design_tokens import Size
from core.style_helpers import ss_transparent
from core.ui.editor_widgets import EditorListRow, configure_scrollarea


class RecordListModel(QAbstractListModel):
    """Tuple records: first value is the title; UserRole exposes the whole row."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def reset_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[0]
        if role == Qt.ItemDataRole.UserRole:
            return row


class EditorRecordList(QScrollArea):
    def __init__(self, model, describe, parent=None, *, bind_row=None):
        super().__init__(parent)
        self._model, self._describe = model, describe
        self._bind_row = bind_row
        self._rows = []
        self._selection = QItemSelectionModel(model, self)
        configure_scrollarea(self, transparent=True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._content = QWidget()
        self._content.setStyleSheet(ss_transparent())
        self.setWidget(self._content)
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().valueChanged.connect(self.refresh)
        self._selection.currentRowChanged.connect(self.refresh)
        for signal in (model.dataChanged, model.modelReset, model.layoutChanged,
                       model.rowsInserted, model.rowsRemoved):
            signal.connect(self.refresh)
        self.refresh()

    def model(self):
        return self._model

    def selectionModel(self):
        return self._selection

    def currentIndex(self):
        return self._selection.currentIndex()

    def setCurrentIndex(self, index):
        self._selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                       | QItemSelectionModel.SelectionFlag.Rows)
        self.refresh()

    def clearSelection(self):
        self._selection.clearSelection()
        self.refresh()

    def scrollTo(self, index):
        if not index.isValid():
            return
        stride = Size.LIST_ROW + Size.LIST_GAP
        top, height = index.row() * stride, self.viewport().height()
        scroll = self.verticalScrollBar()
        if top < scroll.value():
            scroll.setValue(top)
        elif top + Size.LIST_ROW > scroll.value() + height:
            scroll.setValue(top + Size.LIST_ROW - height)
        self.refresh()

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self.refresh()
        return super().eventFilter(watched, event)

    def refresh(self, *_):
        count = self._model.rowCount()
        stride = Size.LIST_ROW + Size.LIST_GAP
        height = max(0, count * stride - Size.LIST_GAP)
        if self._content.minimumHeight() != height:
            self._content.setMinimumHeight(height)
        first = max(0, self.verticalScrollBar().value() // stride - 1)
        visible = min(count - first, self.viewport().height() // stride + 3)
        while len(self._rows) < visible:
            row = EditorListRow(self._content)
            row.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.clicked.connect(lambda _, button=row: self._clicked(button))
            self._rows.append(row)
        for offset, row in enumerate(self._rows):
            if offset >= visible:
                row.hide()
                continue
            index = self._model.index(first + offset, 0)
            title, subtitle, tooltip = self._describe(index)
            row._record_index = index
            row.set_texts(title, subtitle)
            row.setToolTip(tooltip)
            row.setAccessibleName(title + '\n' + subtitle)
            row.set_selected(index.row() == self.currentIndex().row())
            if self._bind_row is not None:
                self._bind_row(row, index)
            row.setGeometry(0, (first + offset) * stride, self.viewport().width(), Size.LIST_ROW)
            row.show()

    def _clicked(self, row):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setCurrentIndex(row._record_index)

    def keyPressEvent(self, event):
        count = self._model.rowCount()
        row = self.currentIndex().row()
        page = max(1, self.viewport().height() // (Size.LIST_ROW + Size.LIST_GAP))
        targets = {Qt.Key.Key_Up: row - 1, Qt.Key.Key_Down: row + 1,
                   Qt.Key.Key_Home: 0, Qt.Key.Key_End: count - 1,
                   Qt.Key.Key_PageUp: row - page, Qt.Key.Key_PageDown: row + page}
        if count and event.key() in targets:
            index = self._model.index(max(0, min(count - 1, targets[event.key()])), 0)
            self.setCurrentIndex(index)
            # The owner may have rejected navigation to retain incomplete input.
            self.scrollTo(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)
