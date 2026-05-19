from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from core import updater
from core.settings import save_settings
from core.workers.update_workers import _UpdateCheckWorker, _UpdateDownloadWorker


class UpdateControllerMixin:
    def _set_update_status(self, text):
        if self._update_status_label is None:
            return
        try:
            self._update_status_label.setText(text)
        except RuntimeError:
            self._update_status_label = None

    def _auto_check_for_updates(self):
        if not self._settings.get("check_updates_on_startup", True):
            return
        if not updater.should_check_today(self._settings.get("last_update_check")):
            return
        self._check_for_updates(manual=False)

    def _check_for_updates(self, manual=False):
        if self._update_check_worker and self._update_check_worker.isRunning():
            if manual:
                self._set_update_status(self.t("updates_checking"))
            return

        if manual:
            self._set_update_status(self.t("updates_checking"))

        worker = _UpdateCheckWorker(self)
        worker.finished.connect(lambda info, m=manual: self._on_update_check_finished(info, m))
        worker.failed.connect(lambda error, m=manual: self._on_update_check_failed(error, m))
        worker.finished.connect(lambda _info, w=worker: w.deleteLater())
        worker.failed.connect(lambda _error, w=worker: w.deleteLater())
        self._update_check_worker = worker
        worker.start()

    def _download_and_install_update(self, info):
        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self._set_update_status(self.t("updates_downloading"))

        progress = QProgressDialog(self.t("updates_download_progress", asset=info.get("asset_name", "")), "", 0, 100, self)
        progress.setWindowTitle(self.t("updates_title"))
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._update_progress_dialog = progress

        worker = _UpdateDownloadWorker(info, self)
        worker.progress.connect(self._on_update_download_progress)
        worker.finished.connect(self._on_update_download_finished)
        worker.failed.connect(self._on_update_download_failed)
        worker.finished.connect(lambda _result, w=worker: w.deleteLater())
        worker.failed.connect(lambda _error, w=worker: w.deleteLater())
        self._update_download_worker = worker
        worker.start()

    def _on_update_download_progress(self, done, total):
        progress = self._update_progress_dialog
        if progress is None:
            return
        if total > 0:
            progress.setRange(0, 100)
            progress.setValue(min(100, int(done * 100 / total)))
        else:
            progress.setRange(0, 0)

    def _close_update_progress(self):
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
            self._update_progress_dialog.deleteLater()
            self._update_progress_dialog = None

    def _on_update_download_finished(self, result):
        self._update_download_worker = None
        self._close_update_progress()
        self._set_update_status(self.t("updates_installing"))
        QMessageBox.information(self, self.t("updates_title"), self.t("updates_restart_message"))
        try:
            updater.launch_prepared_update(result.get("script_path", ""))
        except Exception as exc:
            QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=str(exc)))
            return
        QApplication.quit()

    def _on_update_download_failed(self, error):
        self._update_download_worker = None
        self._close_update_progress()
        self._set_update_status(self.t("updates_failed"))
        QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=error))

    def _on_update_check_finished(self, info, manual):
        self._update_check_worker = None
        self._settings["last_update_check"] = updater.today_string()
        save_settings(self._settings)

        if not info.get("update_available"):
            status = self.t("updates_up_to_date", version=info.get("current_version", updater.APP_VERSION))
            self._set_update_status(status)
            if manual:
                QMessageBox.information(self, self.t("updates_title"), status)
            return

        self._set_update_status(self.t(
            "updates_available_status",
            version=info.get("latest_version", ""),
        ))
        self._prompt_for_update(info)

    def _on_update_check_failed(self, error, manual):
        self._update_check_worker = None
        self._set_update_status(self.t("updates_failed"))
        if manual:
            QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=error))
