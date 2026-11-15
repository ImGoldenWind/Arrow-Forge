"""Shared file actions. Format-specific writers and validation stay in editors."""
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QFileDialog, QPushButton

from core.translations import ui_text
from core.ui.editor_widgets import configure_button


def editor_path(editor):
    for name in ("_filepath", "_xfbin_path", "_original_path"):
        value = getattr(editor, name, None)
        if value:
            return str(value)
    document = getattr(editor, "_doc", None)
    return str(getattr(document, "path", "") or "")


def commit_save_path(editor, path):
    """Called only after the existing writer succeeds."""
    if hasattr(editor, "_filepath"):
        editor._filepath = path
    elif hasattr(editor, "_xfbin_path"):
        editor._xfbin_path = path
    document = getattr(editor, "_doc", None)
    if document is not None and hasattr(document, "path"):
        document.path = path
    actions = getattr(editor, "_file_actions", None)
    if actions:
        actions.pending_path = None
        actions.refresh()


def refresh_file_actions(widget, *, loaded=None):
    while widget is not None:
        actions = getattr(widget, "_file_actions", None)
        if actions:
            if loaded is not None:
                actions.loaded = loaded
            actions.refresh()
        widget = widget.parentWidget()


class EditorFileActions(QObject):
    def __init__(self, editor, button, save_to=None, native=None, asynchronous=False, save_button=None):
        super().__init__(editor)
        self.editor = editor
        self.button = button
        self.save_to = save_to
        self.native = native
        self.asynchronous = asynchronous
        self.loaded = False
        self.pending_path = None
        self.managed = True
        self.save_button = save_button
        if native and save_button is not None:
            save_button.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.refresh()
        return False

    def refresh(self):
        from core.ui.editor_chrome import refresh_editor_filters
        refresh_editor_filters(self.editor)
        if not self.managed:
            return
        if self.native and self.save_button is not None:
            self.button.setEnabled(self.save_button.isEnabled())
            return
        busy = getattr(self.editor, "_busy", False)
        if callable(busy):
            busy = busy()
        self.button.setEnabled(bool(self.loaded and editor_path(self.editor) and not busy and not self.pending_path))

    def trigger(self):
        if self.native:
            return self.native()
        if not self.loaded or self.pending_path:
            return
        source = editor_path(self.editor)
        suffix = Path(source).suffix
        file_filter = f"{suffix.lstrip('.').upper()} files (*{suffix});;All files (*)" if suffix else "All files (*)"
        path, _ = QFileDialog.getSaveFileName(self.editor, ui_text("btn_save_as"), source, file_filter)
        if not path:
            return
        if suffix and not Path(path).suffix:
            path += suffix
        self.pending_path = path
        self.refresh()
        try:
            return self.save_to(path)
        except Exception:
            self.pending_path = None
            self.refresh()
            raise
        finally:
            if not self.asynchronous:
                self.pending_path = None
                self.refresh()


def install_file_actions(editor, save_button, *, save_to=None, native=None,
                         existing_button=None, asynchronous=False):
    """One Save as action per editor, beside Save, including standalone windows."""
    if getattr(editor, "_file_actions", None) is not None:
        return editor._file_actions
    button = existing_button
    if button is None:
        button = configure_button(QPushButton(ui_text("btn_save_as")))
        layout = save_button.parentWidget().layout()
        index = layout.indexOf(save_button)
        layout.insertWidget(index + 1, button)
    else:
        button.setText(ui_text("btn_save_as"))
    button.setObjectName("EditorSaveAs")
    button.setProperty("designAction", "save_as")
    actions = EditorFileActions(editor, button, save_to, native, asynchronous, save_button)
    actions.managed = existing_button is None
    editor._file_actions = actions
    if existing_button is None:
        button.clicked.connect(actions.trigger)
    if existing_button is not None:
        # Existing implementations keep their format-specific availability rules.
        return actions
    actions.refresh()
    return actions
