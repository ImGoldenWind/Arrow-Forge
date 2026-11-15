"""Qt catalog adapter; record order is never changed by searching/filtering."""
from PyQt6.QtCore import QSortFilterProxyModel
from core.ui.record_list import RecordListModel as RankListModel


class RankFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query, self.modified_only = '', False

    def set_filters(self, query, modified_only):
        self.query, self.modified_only = query.casefold().strip(), modified_only
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        title, subtitle, search, modified = self.sourceModel().rows[row]
        return (not self.modified_only or modified) and all(word in search for word in self.query.split())
