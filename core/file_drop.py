import inspect
import os

from PyQt6.QtCore import QObject, QEvent, QTimer
from PyQt6.QtWidgets import QFileDialog, QWidget


def install_file_drop(widget: QWidget):
    """Enable dropping one local file onto an editor widget."""
    loader = _resolve_file_loader(widget)
    if loader is None:
        return None

    handler = _FileDropHandler(widget, loader)
    handler.install(widget)
    widget._file_drop_handler = handler
    QTimer.singleShot(0, lambda: handler.install_children(widget))
    return handler


class _FileDropHandler(QObject):
    def __init__(self, root: QWidget, loader):
        super().__init__(root)
        self._loader = loader
        self._installed = set()

    def install(self, widget):
        if not isinstance(widget, QWidget):
            return
        key = id(widget)
        if key in self._installed:
            return
        self._installed.add(key)
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def install_children(self, root):
        self.install(root)
        for child in root.findChildren(QWidget):
            self.install(child)

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                QTimer.singleShot(0, lambda child=child: self.install_children(child))
            return False

        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            path = _first_local_file(event.mimeData())
            if path:
                event.acceptProposedAction()
                return True
            return False

        if event_type == QEvent.Type.Drop:
            path = _first_local_file(event.mimeData())
            if path:
                event.acceptProposedAction()
                self._loader(path)
                return True
            return False

        return False


def _first_local_file(mime_data):
    if not mime_data or not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if os.path.isfile(path):
            return path
    return None


def _resolve_file_loader(editor):
    path_methods = ("load_file", "_do_load", "_start_load", "_load", "_load_file")
    for name in path_methods:
        method = getattr(editor, name, None)
        if callable(method) and _can_call_with_path(method):
            return method

    opener_methods = ("_on_open", "_do_open", "_open_file", "_load_file")
    for name in opener_methods:
        method = getattr(editor, name, None)
        if callable(method) and _can_call_without_args(method):
            return lambda path, method=method: _call_opener_with_path(method, path)

    return None


def _can_call_with_path(method):
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False

    required = 0
    positional = 0
    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if param.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        positional += 1
        if param.default is inspect.Parameter.empty:
            required += 1
    return required <= 1 <= positional


def _can_call_without_args(method):
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.default is inspect.Parameter.empty:
            return False
    return True


def _call_opener_with_path(method, path):
    original = QFileDialog.getOpenFileName

    def dropped_file(*args, **kwargs):
        return path, ""

    QFileDialog.getOpenFileName = dropped_file
    try:
        method()
    finally:
        QFileDialog.getOpenFileName = original
