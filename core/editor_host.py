from __future__ import annotations


def _walk_parents(widget):
    current = widget
    while current is not None:
        yield current
        parent = getattr(current, "parentWidget", lambda: None)()
        current = parent


def notify_editor_file_loaded(editor, path: str) -> None:
    for widget in _walk_parents(editor):
        callback = getattr(widget, "_on_embedded_editor_file_loaded", None)
        if callable(callback):
            callback(editor, path)
            return


def confirm_editor_change_summary(editor) -> bool:
    for widget in _walk_parents(editor):
        callback = getattr(widget, "_confirm_editor_change_summary", None)
        if callable(callback):
            return bool(callback(editor))
    return True
