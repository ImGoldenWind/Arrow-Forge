"""Shared inline message preview and lazy, per-control reference tooltips."""
from html import escape

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QComboBox, QLabel, QLineEdit, QToolTip

from core.design_tokens import TypeSize, ui_font
from core.message_text import MessageText
from core.settings import load_settings
from core.style_helpers import ss_dim_label, ss_main_label
from core.translations import current_language, ui_text


def message_lookup(editor):
    from core.ui.editor_actions import editor_path
    path = editor_path(editor)
    language = current_language()
    game_root = load_settings().get('game_files_dir', '')
    signature = (path, language, game_root)
    if getattr(editor, '_message_lookup_signature', None) != signature:
        editor._message_lookup_signature = signature
        editor._message_lookup = MessageText(path, language, game_root)
    return editor._message_lookup


class MessagePreview(QLabel):
    """Selectable, wrapped plain text; never an editable game-data field."""
    def __init__(self, edit, lookup, parent=None, *, crc=False):
        super().__init__(parent)
        self.lookup = lookup
        self.crc = crc
        self.edit = edit
        self._field_help = edit.toolTip()
        self._field_tooltip = None
        # Inline previews already know the exact document and current ID. Keep
        # their input's native tooltip synchronized with that same reference.
        edit._message_preview = self
        install_message_tooltip(edit)
        self.setProperty('designMessagePreview', True)
        self.setFont(ui_font(TypeSize.BODY))
        self.setStyleSheet(ss_main_label())
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        edit.textChanged.connect(self.refresh)
        self.refresh(edit.text())

    def refresh(self, value):
        result = self.lookup.resolve(value, crc=self.crc)
        if not value:
            text = ui_text('message_preview_empty')
        elif result:
            text = f'[{result.source}] {result.text}' if result.text else '\n'.join(result.ids)
            if self.crc and result.text and result.ids:
                text = '\n'.join(result.ids) + '\n' + text
            if not result.text:
                text += '\n' + ui_text('message_preview_not_found' if self.lookup.tables else 'message_preview_missing')
        else:
            text = ui_text('message_preview_not_found' if self.lookup.tables else 'message_preview_missing')
        self.setStyleSheet(ss_main_label() if result and result.text else ss_dim_label())
        self.setText(text)
        self.setToolTip(text)
        if self._field_tooltip is not None and self.edit.toolTip() != self._field_tooltip:
            self._field_help = self.edit.toolTip()
        reference = result.description() if result else text
        content = escape(reference).replace('\n', '<br>')
        if self._field_help:
            content = self._field_help + '<hr>' + content
        self._field_tooltip = '<div>' + content + '</div>'
        self.edit.setToolTip(self._field_tooltip)


class _MessageTooltip(QObject):
    def eventFilter(self, widget, event):
        if event.type() != QEvent.Type.ToolTip:
            return False
        if getattr(widget, '_message_preview', None) is not None:
            QToolTip.showText(event.globalPos(), widget.toolTip(), widget)
            return True
        control = widget
        parent = widget.parentWidget()
        if isinstance(parent, QComboBox) and parent.lineEdit() is widget:
            control = parent
        if control.property('messageReference') is False:
            return False
        owner = widget.parentWidget()
        while owner is not None and not hasattr(owner, '_file_actions'):
            owner = owner.parentWidget()
        if owner is None or control.property('designFilter'):
            return False
        if isinstance(control, QComboBox):
            value = control.currentData()
            if control.isEditable() and control.currentText() != control.itemText(control.currentIndex()):
                value = control.currentText()
            if not isinstance(value, str):
                value = control.currentText() if control.isEditable() else ''
        else:
            value = control.text()
        result = message_lookup(owner).resolve(value, crc=bool(control.property('messageCRC32')))
        if result is None:
            return False
        if control.property('messageTextOnly'):
            if not result.text:
                return False
            QToolTip.showText(event.globalPos(), '<div>' + escape(result.text).replace('\n', '<br>') + '</div>', widget)
            return True
        # Preserve existing field help, including rich text, without mutating it.
        content = escape(result.description()).replace('\n', '<br>')
        existing = widget.toolTip() or control.toolTip()
        if existing:
            content = existing + '<hr>' + content
        QToolTip.showText(event.globalPos(), '<div>' + content + '</div>', widget)
        return True


def install_message_tooltip(widget):
    if not isinstance(widget, (QLineEdit, QComboBox)):
        return
    if not hasattr(widget, '_message_tooltip'):
        widget._message_tooltip = _MessageTooltip(widget)
        widget.installEventFilter(widget._message_tooltip)
    if isinstance(widget, QComboBox) and widget.isEditable():
        install_message_tooltip(widget.lineEdit())
