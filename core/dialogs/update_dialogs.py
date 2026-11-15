from core.design_tokens import (
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    ss_dialog,
)
from core.ui.editor_widgets import (
    configure_button,
    configure_textedit,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from core import updater
from core.themes import P


class UpdateDialogsMixin:
    def _show_update_changelog_dialog(self, info, message):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("updates_changelog_window_title", version=info.get("latest_version", "")))
        dialog.setModal(True)
        dialog.resize(680, 520)
        dialog.setStyleSheet(ss_dialog())

        result = {"action": "cancel"}

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(self.t("updates_changelog_title", version=info.get("latest_version", "")))
        title.setFont(ui_font(TypeSize.ANNOUNCEMENT, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        layout.addWidget(title)

        summary = QLabel(message)
        summary.setFont(ui_font(TypeSize.BODY))
        summary.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        can_auto_install = bool(info.get("asset_url") and info.get("automatic_install_supported", True))

        if not info.get("asset_url"):
            no_asset = QLabel(self.t("updates_no_download_asset_dialog"))
            no_asset.setFont(ui_font(TypeSize.BODY))
            no_asset.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            no_asset.setWordWrap(True)
            layout.addWidget(no_asset)
        elif not can_auto_install:
            manual_only = QLabel(self.t("updates_manual_install_only"))
            manual_only.setFont(ui_font(TypeSize.BODY))
            manual_only.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            manual_only.setWordWrap(True)
            layout.addWidget(manual_only)

        changelog_label = QLabel(self.t("updates_changelog_label"))
        changelog_label.setFont(ui_font(TypeSize.CODE, QFont.Weight.Bold))
        changelog_label.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        layout.addWidget(changelog_label)

        body = str(info.get("body") or "").strip() or self.t("updates_changelog_empty")
        changelog = QTextEdit()
        changelog.setReadOnly(True)
        changelog.setMinimumHeight(260)
        configure_textedit(changelog)
        try:
            changelog.setMarkdown(body)
        except Exception:
            changelog.setPlainText(body)
        layout.addWidget(changelog, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)
        button_row.setSpacing(Size.GAP)
        button_row.addStretch()

        def add_dialog_button(text, action, accent=False):
            btn = QPushButton(text)
            configure_button(btn, accent=accent, height=32)
            btn.clicked.connect(lambda _checked=False, a=action: (result.update(action=a), dialog.accept()))
            button_row.addWidget(btn)
            return btn

        if info.get("release_url"):
            add_dialog_button(self.t("updates_open_release"), "release", accent=not can_auto_install)
        if can_auto_install:
            add_dialog_button(self.t("updates_install_now"), "download", accent=True)
        cancel_btn = QPushButton(self.t("unsaved_changes_cancel"))
        configure_button(cancel_btn, height=32)
        cancel_btn.clicked.connect(dialog.reject)
        button_row.addWidget(cancel_btn)

        layout.addLayout(button_row)
        dialog.exec()
        return result["action"] if dialog.result() == QDialog.DialogCode.Accepted else "cancel"

    def _prompt_for_update(self, info):
        asset_size = updater.human_size(info.get("asset_size", 0))
        message = self.t(
            "updates_available_message",
            current=info.get("current_version", updater.APP_VERSION),
            latest=info.get("latest_version", ""),
            asset=info.get("asset_name", ""),
            size=asset_size,
        )
        action = self._show_update_changelog_dialog(info, message)
        if action == "download":
            if not self._confirm_close_embedded_editor():
                return
            self._delete_tool_frame()
            self._download_and_install_update(info)
        elif action == "release":
            QDesktopServices.openUrl(QUrl(info.get("release_url", "")))
