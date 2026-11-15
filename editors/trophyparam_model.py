"""Numerically sortable TrophyParam catalog data; no presentation or simulation."""
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from core.translations import ui_text
from core.trophy_tools import FIELDS


class TrophyTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = None
        self.duplicates = set()

    @property
    def entries(self):
        return self.session.result['entries'] if self.session else []

    def reset_session(self, session):
        self.beginResetModel()
        self.session = session
        self.duplicates = session.duplicate_ids() if session else set()
        self.endResetModel()

    def refresh(self, row):
        previous = self.duplicates
        self.duplicates = self.session.duplicate_ids()
        if self.rowCount():
            first, last = (0, self.rowCount() - 1) if previous != self.duplicates else (row, row)
            self.dataChanged.emit(self.index(first, 0), self.index(last, 3))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ('#', ui_text('ui_trophyparam_trophy_id'), ui_text('trophy_catalog_value'),
                    ui_text('trophy_catalog_status'))[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        row, column = index.row(), index.column()
        entry = self.entries[row]
        status = self.session.status(entry)
        if role == Qt.ItemDataRole.UserRole:
            return (row, entry[FIELDS[0]], entry[FIELDS[1]], status)[column]
        if role == Qt.ItemDataRole.DisplayRole:
            return (row, entry[FIELDS[0]], entry[FIELDS[1]], ui_text('trophy_status_' + status))[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [ui_text('ui_trophyparam_entry_title', index=row, trophy_id=entry['trophy_id']),
                     ui_text('trophy_status_' + status)]
            for key in FIELDS:
                value = entry[key]
                lines.append(f'{value} / 0x{value:08X}')
            if entry['trophy_id'] in self.duplicates:
                lines.append(ui_text('trophy_duplicate_hint'))
            return '\n'.join(lines)


class TrophyFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query, self.mode = '', 'all'
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def lessThan(self, left, right):
        # Qt's mixed signed/unsigned QVariant comparison can place FFFFFFFF
        # below small positive ints. Keep ordering exact across the full u32.
        return left.data(Qt.ItemDataRole.UserRole) < right.data(Qt.ItemDataRole.UserRole)

    def set_filters(self, query, mode):
        self.query, self.mode = query.casefold().strip(), mode or 'all'
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        entry = model.entries[row]
        status = model.session.status(entry)
        if self.mode == 'duplicates' and entry['trophy_id'] not in model.duplicates:
            return False
        if self.mode not in ('all', 'duplicates') and status != self.mode:
            return False
        original = model.session.original(entry)
        words = [str(row), ui_text('trophy_status_' + status)]
        for record in (entry, original):
            if record:
                for key in FIELDS:
                    words.extend((str(record[key]), f'0x{record[key]:08x}'))
        return all(part in ' '.join(words).casefold() for part in self.query.split())
