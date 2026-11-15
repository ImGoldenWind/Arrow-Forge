from __future__ import annotations

from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    ss_dialog,
    ss_settings_check,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_layout,
    configure_table,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from core.editor_diff import ChangeItem
from core.themes import P


def _change_text(item: ChangeItem) -> str:
    if item.before or item.after:
        return f"{item.label}: {item.before} -> {item.after}"
    return item.label


class ChangeSummaryDialog(QDialog):
    def __init__(self, parent, t, changes: list[ChangeItem]):
        super().__init__(parent)
        self._changes = changes
        self.setWindowTitle(t("qol_change_summary_title"))
        self.setModal(True)
        self.resize(620, 420)
        self.setStyleSheet(ss_dialog())
        self.skip_future = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(Size.CARD_GAP)

        title = QLabel(t("qol_change_summary_heading"), self)
        title.setFont(ui_font(TypeSize.SUBHEADING, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; border: none;")
        layout.addWidget(title)

        self._list = QListWidget(self)
        configure_table(self._list)
        for change in changes:
            self._list.addItem(_change_text(change))
        layout.addWidget(self._list, 1)

        self._skip = QCheckBox(t("qol_change_summary_skip"), self)
        self._skip.setStyleSheet(ss_settings_check())
        self._skip.toggled.connect(lambda value: setattr(self, "skip_future", bool(value)))
        layout.addWidget(self._skip)

        buttons = QDialogButtonBox(self)
        save_btn = buttons.addButton(t("qol_save"), QDialogButtonBox.ButtonRole.AcceptRole)
        copy_btn = buttons.addButton(t("qol_copy_diff"), QDialogButtonBox.ButtonRole.ActionRole)
        cancel_btn = buttons.addButton(t("qol_cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        configure_button(save_btn, accent=True)
        configure_button(copy_btn)
        configure_button(cancel_btn)
        copy_btn.clicked.connect(self._copy_summary)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_summary(self):
        QApplication.clipboard().setText("\n".join(_change_text(change) for change in self._changes))


class CompareCopyDialog(QDialog):
    def __init__(self, parent, t, changes: list[ChangeItem]):
        super().__init__(parent)
        self._t = t
        self._changes = changes
        self.setWindowTitle(t("qol_compare_title"))
        self.setModal(True)
        self.resize(720, 480)
        self.setStyleSheet(ss_dialog())
        self.selected_item_ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(Size.CARD_GAP)

        title = QLabel(t("qol_compare_heading"), self)
        title.setFont(ui_font(TypeSize.SUBHEADING, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; border: none;")
        layout.addWidget(title)

        self._filter = QComboBox(self)
        self._filter.addItem(t("qol_filter_all"), "")
        self._filter.addItem(t("qol_filter_changed"), "changed")
        self._filter.addItem(t("qol_filter_added"), "added")
        self._filter.addItem(t("qol_filter_removed"), "removed")
        self._filter.currentIndexChanged.connect(self._render_checks)
        layout.addWidget(self._filter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._checks: list[tuple[QCheckBox, ChangeItem]] = []
        list_frame = QFrame(self)
        list_frame.setStyleSheet("background: transparent; border: none;")
        self._list_layout = QVBoxLayout(list_frame)
        configure_layout(self._list_layout, LayoutRole.FIELD)
        scroll.setWidget(list_frame)
        layout.addWidget(scroll, 1)
        self._render_checks()

        row = QHBoxLayout()
        row.addStretch()
        copy_btn = QPushButton(t("qol_copy_selected"), self)
        configure_button(copy_btn, accent=True)
        copy_btn.clicked.connect(self._copy_selected)
        row.addWidget(copy_btn)
        close_btn = QPushButton(t("qol_close"), self)
        configure_button(close_btn)
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _copy_selected(self):
        self.selected_item_ids = [
            change.item_id for checkbox, change in self._checks
            if checkbox.isChecked() and change.copyable
        ]
        if self.selected_item_ids:
            self.accept()

    def _render_checks(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._checks = []
        kind_filter = self._filter.currentData() if hasattr(self, "_filter") else ""
        for change in self._changes:
            if kind_filter and change.kind != kind_filter:
                continue
            cb = QCheckBox(_change_text(change), self)
            cb.setEnabled(change.copyable)
            cb.setChecked(change.copyable)
            cb.setStyleSheet(ss_settings_check())
            self._list_layout.addWidget(cb)
            self._checks.append((cb, change))
        self._list_layout.addStretch()
