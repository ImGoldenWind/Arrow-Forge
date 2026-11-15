"""Shared editor typography and reversible sidebar collapse handles."""
from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractScrollArea, QBoxLayout, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget

from core.design_tokens import IconButtonRole, LayoutRole, ui_font
from core.icons import _themed_icon
from core.style_helpers import ss_bg_panel
from core.themes import P
from core.translations import ui_text
from core.ui.editor_widgets import EditorFilterCombo, EditorFilterReset, EditorSidebar, configure_icon_button, configure_layout, configure_tabs


def capture_pending_fields(editor):
    def context(owner):
        # Responsive rebuilding may replace widgets, but a queued restoration
        # must never cross a document/record change. Retain identity for mutable
        # records instead of comparing their (possibly equal) contents.
        def identity(value):
            return value if isinstance(value, (str, int, float, type(None))) else id(value)
        return tuple(identity(getattr(owner, key, None)) for key in (
            '_filepath', '_doc', '_result', '_current_idx', '_current_index',
            '_selected_idx', '_selected_index', '_current_entry', '_current_scene'))

    editor_context = context(editor)
    snapshots = []
    for owner in [editor, *editor.findChildren(QWidget)]:
        for attribute in ("_fields", "_field_widgets", "_key_fields"):
            fields = getattr(owner, attribute, None)
            if not isinstance(fields, dict):
                continue
            for key, control in fields.items():
                controls = control if isinstance(control, tuple) else (control,)
                for index, widget in enumerate(controls):
                    if isinstance(widget, QLineEdit):
                        value = widget.text()
                    elif isinstance(widget, QComboBox):
                        value = widget.currentText()
                    elif isinstance(widget, QLabel):
                        value = widget.text()
                    else:
                        continue
                    snapshots.append((owner, attribute, key, index, value, widget.styleSheet(), widget, context(owner)))

    def restore():
        from PyQt6 import sip
        if sip.isdeleted(editor):
            return
        if context(editor) != editor_context:
            return
        for owner, attribute, key, index, value, stylesheet, original_widget, owner_context in snapshots:
            try:
                if context(owner) != owner_context:
                    continue
                control = getattr(owner, attribute, {}).get(key)
                controls = control if isinstance(control, tuple) else (control,)
                if index >= len(controls):
                    continue
                widget = controls[index]
                # Retained controls already carry their latest input/undo and
                # validation. A subsequent edit or Restore command takes priority.
                if widget is None or widget is original_widget:
                    continue
                with QSignalBlocker(widget):
                    if isinstance(widget, QComboBox):
                        if widget.currentText() != value:
                            widget.setCurrentText(value)
                    else:
                        # Adaptive forms can retain the original control. Even
                        # setText(the_same_text) clears QLineEdit's undo stack.
                        if widget.text() != value:
                            widget.setText(value)
                    if widget.styleSheet() != stylesheet:
                        widget.setStyleSheet(stylesheet)
            except (RuntimeError, AttributeError):
                continue
    return restore


class EditorSidebarPane(QWidget):
    collapsedChanged = pyqtSignal(bool)

    def __init__(self, sidebar, editor, *, edge="left", resizable=False, label="sidebar"):
        super().__init__()
        self.sidebar = sidebar
        self.editor = editor
        self._syncing = False
        self.edge = edge
        self.resizable = resizable
        self.label = label
        self._expanded_sizes = None
        self.setStyleSheet(ss_bg_panel())
        layout = configure_layout(QHBoxLayout(self), LayoutRole.ROOT)
        if edge == "left":
            layout.addWidget(sidebar)
        rail = QWidget()
        rail.setFixedWidth(IconButtonRole.SIDEBAR_TOGGLE.value[0])
        rail_layout = configure_layout(QVBoxLayout(rail), LayoutRole.ROOT)
        rail_layout.addStretch()
        self.button = configure_icon_button(QPushButton(), IconButtonRole.SIDEBAR_TOGGLE)
        self.button.setObjectName("EditorSidebarToggle")
        self.button.clicked.connect(self.toggle)
        rail_layout.addWidget(self.button)
        rail_layout.addStretch()
        layout.addWidget(rail)
        if edge == "right":
            layout.addWidget(sidebar, 1)
        sidebar._design_sidebar_pane = self
        sidebar.installEventFilter(self)
        self._sync()

    def _sync(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_geometry()
        finally:
            self._syncing = False

    def _sync_geometry(self):
        hidden = self.sidebar.isHidden()
        width = IconButtonRole.SIDEBAR_TOGGLE.value[0] + (0 if hidden else self.sidebar.width())
        if self.resizable and not hidden:
            self.setMinimumWidth(IconButtonRole.SIDEBAR_TOGGLE.value[0] + self.sidebar.minimumWidth())
            self.setMaximumWidth(16777215)
        elif self.width() != width:
            self.setFixedWidth(width)
        if getattr(self, "_collapsed", None) == hidden:
            return
        self._collapsed = hidden
        text = ui_text(self.label + ("_show" if hidden else "_hide"))
        self.button.setToolTip(text)
        self.button.setAccessibleName(text)
        right = hidden if self.edge == "left" else not hidden
        self.button.setIcon(_themed_icon("fa6s.chevron-right" if right else "fa6s.chevron-left",
                                        color=P.get("button_text", P["text_main"]), size=12))
        self.collapsedChanged.emit(hidden)

    def toggle(self):
        restore = capture_pending_fields(self.editor)
        parent = self.parentWidget()
        if self.resizable and isinstance(parent, QSplitter) and not self.sidebar.isHidden():
            self._expanded_sizes = parent.sizes()
        self.sidebar.setVisible(self.sidebar.isHidden())
        self._sync()
        if self.resizable and isinstance(parent, QSplitter) and not self.sidebar.isHidden() and self._expanded_sizes:
            parent.setSizes(self._expanded_sizes)
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()
        QTimer.singleShot(0, restore)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            self._sync()
        return False


def install_editor_chrome(editor):
    editor.setFont(ui_font())
    for tabs in editor.findChildren(QTabWidget):
        configure_tabs(tabs)
    for sidebar in list(editor.findChildren(EditorSidebar)):
        if hasattr(sidebar, "_design_sidebar_pane"):
            continue
        parent = sidebar.parentWidget()
        if isinstance(parent, QSplitter):
            index = parent.indexOf(sidebar)
            placeholder = QWidget()
            parent.replaceWidget(index, placeholder)
            pane = EditorSidebarPane(sidebar, editor)
            parent.replaceWidget(index, pane)
            placeholder.deleteLater()
            continue
        for layout in editor.findChildren(QBoxLayout):
            index = layout.indexOf(sidebar)
            if index >= 0:
                layout.removeWidget(sidebar)
                pane = EditorSidebarPane(sidebar, editor)
                layout.insertWidget(index, pane)
                break
    install_editor_filters(editor)
    from core.shortcuts import install_editor_shortcuts
    install_editor_shortcuts(editor)


def _item_controls(item):
    """Walk header wrappers and rows, without entering list or preview content."""
    widget = item.widget()
    if widget is not None:
        yield widget
        if isinstance(widget, (QAbstractScrollArea, QTabWidget, EditorSidebar)):
            return
    layout = item.layout() or (widget.layout() if widget is not None else None)
    if layout is not None:
        for index in range(layout.count()):
            yield from _item_controls(layout.itemAt(index))


def _install_sidebar_filters(scope, search, filters):
    # The closest vertical layout also handles a sidebar implemented by an
    # inner widget (textures), and search fields wrapped in a horizontal row.
    candidates = [layout for layout in scope.findChildren(QVBoxLayout)
                  if any(search in _item_controls(layout.itemAt(index))
                         for index in range(layout.count()))]
    if not candidates:
        return False
    layout = candidates[-1]
    search_index = next(index for index in range(layout.count())
                        if search in _item_controls(layout.itemAt(index)))
    search_item = layout.takeAt(search_index)
    layout.insertItem(0, search_item)

    # Keep filter wrappers, horizontal filter rows, and their existing order.
    # Section/bank selectors and sorting belong to this block too; only the
    # explicitly registered filters participate in Clear Filters.
    position = 1
    groups = []
    for index in range(1, layout.count()):
        if any(isinstance(control, QComboBox)
               for control in _item_controls(layout.itemAt(index))):
            item = layout.takeAt(index)
            layout.insertItem(position, item)
            groups.extend([item.widget()] if item.widget() is not None else
                          [control for control in _item_controls(item) if isinstance(control, QComboBox)])
            position += 1
    button = EditorFilterReset(search, filters)
    search._design_filter_reset = button
    button._filter_groups = groups
    layout.insertWidget(position, button)
    return True


def install_editor_filters(editor):
    """One reset per search scope, using explicitly registered list filters only."""
    for search in editor.findChildren(QLineEdit):
        if search.property("designControlRole") != "search" or hasattr(search, "_design_filter_reset"):
            continue
        scope = search.parentWidget()
        current = scope
        while current is not None and current is not editor:
            if isinstance(current, EditorSidebar):
                scope = current
                break
            current = current.parentWidget()
        filters = scope.findChildren(EditorFilterCombo)
        if isinstance(scope, EditorSidebar) and _install_sidebar_filters(scope, search, filters):
            continue
        for layout in editor.findChildren(QBoxLayout):
            index = layout.indexOf(search)
            if index >= 0:
                button = EditorFilterReset(search, filters)
                search._design_filter_reset = button
                layout.insertWidget(index + 1, button)
                break
    refresh_editor_filters(editor)


def refresh_editor_filters(editor):
    """Reveal list filters only after a document has loaded successfully."""
    from PyQt6 import sip
    loaded = bool(getattr(getattr(editor, "_file_actions", None), "loaded", False))
    for reset in editor.findChildren(EditorFilterReset):
        reset.setVisible(loaded)
        for group in getattr(reset, "_filter_groups", ()):
            if sip.isdeleted(group) or isinstance(group, EditorFilterCombo):
                continue
            choices = group.findChildren(EditorFilterCombo)
            group.setVisible(loaded and (not choices or any(combo.count() > 1 for combo in choices)))
        for combo in reset.filters:
            if not sip.isdeleted(combo):
                combo.setProperty("editorFileLoaded", loaded)
                combo._sync_choices()
