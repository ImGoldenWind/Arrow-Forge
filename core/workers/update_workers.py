from PyQt6.QtCore import QThread, pyqtSignal

from core import updater


class _UpdateCheckWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(updater.check_for_update())
        except Exception as exc:
            self.failed.emit(str(exc))


class _UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info

    def run(self):
        try:
            result = updater.download_and_prepare_update(
                self._info,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
