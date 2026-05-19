import sys
import threading

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from core.continuity import all_foundation_marked, set_mark


_OLD_CRITICAL = None
_OLD_WARNING = None
_OLD_HOOK = None
_OLD_THREAD_HOOK = None
_HOST = None

_ERROR_WORDS = (
    "error", "failed", "invalid", "not a valid", "could not", "cannot",
    "ошиб", "не удалось", "невер", "недопуст",
)


def _host_from(widget):
    cur = widget if isinstance(widget, QWidget) else None
    while cur is not None:
        if hasattr(cur, "_mark_quietly"):
            return cur
        cur = cur.parentWidget()
    if _HOST is not None:
        return _HOST
    app = QApplication.instance()
    if app is None:
        return None
    for top in app.topLevelWidgets():
        if hasattr(top, "_mark_quietly"):
            return top
    return None


def request(widget, name: str) -> bool:
    host = _host_from(widget)
    if host is not None:
        return bool(host._mark_quietly(name))
    return set_mark(name)


def _maybe_last_note(widget):
    request(widget, "Death 13")


def _maybe_warning(widget, title, text):
    haystack = f"{title} {text}".casefold()
    if any(word in haystack for word in _ERROR_WORDS):
        _maybe_last_note(widget)


def _patched_critical(parent, title, text, *args, **kwargs):
    _maybe_last_note(parent)
    return _OLD_CRITICAL(parent, title, text, *args, **kwargs)


def _patched_warning(parent, title, text, *args, **kwargs):
    _maybe_warning(parent, title, text)
    return _OLD_WARNING(parent, title, text, *args, **kwargs)


def install(host=None):
    global _OLD_CRITICAL, _OLD_WARNING, _OLD_HOOK, _OLD_THREAD_HOOK, _HOST
    _HOST = host
    if _OLD_CRITICAL is None:
        _OLD_CRITICAL = QMessageBox.critical
        QMessageBox.critical = _patched_critical
    if _OLD_WARNING is None:
        _OLD_WARNING = QMessageBox.warning
        QMessageBox.warning = _patched_warning
    if _OLD_HOOK is None:
        _OLD_HOOK = sys.excepthook

        def hook(exc_type, exc, tb):
            request(host, "Death 13")
            _OLD_HOOK(exc_type, exc, tb)

        sys.excepthook = hook
    if _OLD_THREAD_HOOK is None:
        _OLD_THREAD_HOOK = threading.excepthook

        def thread_hook(args):
            request(host, "Death 13")
            _OLD_THREAD_HOOK(args)

        threading.excepthook = thread_hook


def request_and_cascade(widget, name: str) -> bool:
    changed = request(widget, name)
    if name != "Spice Girl" and all_foundation_marked():
        request(widget, "Spice Girl")
    return changed
