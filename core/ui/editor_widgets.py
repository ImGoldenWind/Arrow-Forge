"""Shared presentation for existing editor controls; no data or signal ownership.

Use configurators for widgets with existing subclasses/models/delegates. They
deliberately never change selection, edit triggers, validators or input ranges.
"""
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.design_tokens import (
    FontRole, IconButtonRole, Insets, LayoutRole, Size, TypeSize, font, layout_spec, mono_font, ui_font,
)
from core.style_helpers import (
    ss_bg_panel, ss_btn, ss_input, ss_search, ss_table, ss_textedit,
    ss_toggle_btn, ss_sidebar_btn, ss_sidebar_frame, ss_transparent, ss_main_label,
    ss_dim_label, ss_file_label, ss_sep, ss_accent_sep, ss_scrollarea,
    ss_scrollarea_transparent,
    ss_icon_tool_btn, ss_sidebar_edge_toggle,
)


def configure_layout(layout, role: LayoutRole):
    """Apply one immutable layout role without changing order or stretch factors."""
    spec = layout_spec(role)
    layout.setContentsMargins(*spec.margins)
    if spec.horizontal is not None:
        layout.setHorizontalSpacing(spec.horizontal)
        layout.setVerticalSpacing(spec.vertical)
    else:
        layout.setSpacing(spec.spacing)
    layout.setProperty("designLayoutRole", role.value)
    return layout


class EditorToolbar(QFrame):
    def __init__(self, parent=None, *, stacked=False):
        super().__init__(parent)
        self._stacked = stacked
        self.setStyleSheet(ss_bg_panel())
        self.content_layout = QVBoxLayout(self) if stacked else QHBoxLayout(self)
        configure_layout(self.content_layout, LayoutRole.TOOLBAR)
        self.set_rows(1)

    def set_rows(self, rows):
        """CPK reflows commands; row geometry still belongs to the common toolbar."""
        spec = layout_spec(LayoutRole.TOOLBAR)
        if self._stacked:
            self.content_layout.setSpacing(spec.spacing if rows > 1 else 0)
        self.setProperty("designToolbarRows", rows)
        self.setFixedHeight(rows * Size.CONTROL + spec.margins[1] + spec.margins[3]
                            + (rows - 1) * spec.spacing)


class EditorSidebar(QFrame):
    def __init__(self, parent=None, *, width=Size.SIDEBAR_DEFAULT):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.setStyleSheet(ss_sidebar_frame())
        self.content_layout = QVBoxLayout(self)
        configure_layout(self.content_layout, LayoutRole.SIDEBAR)


class EditorActionRow(QWidget):
    """Presentation of a compact action row; commands belong to the editor."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(ss_transparent())
        self.content_layout = QHBoxLayout(self)
        configure_layout(self.content_layout, LayoutRole.ACTIONS)


class EditorSeparator(QFrame):
    def __init__(self, parent=None, *, orientation=Qt.Orientation.Horizontal, accent=False):
        super().__init__(parent)
        thickness = Size.ACCENT_LINE if accent else Size.HAIRLINE
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(thickness)
        else:
            self.setFixedWidth(thickness)
        self.setStyleSheet(ss_accent_sep() if accent else ss_sep())


class EditorFilterCombo(QComboBox):
    """List filter: one neutral caption, original option data and signals."""
    def __init__(self, parent=None):
        super().__init__(parent)
        configure_input(self, monospace=False)
        self.setProperty("designFilter", True)
        self.model().rowsInserted.connect(self._sync_choices)
        self.model().rowsRemoved.connect(self._sync_choices)

    def _sync_choices(self, *args):
        self.setVisible(self.count() > 1 and self.property("editorFileLoaded") is not False)

    def addItem(self, text, userData=None):
        from core.translations import ui_text
        if self.count() == 0:
            self.setToolTip(str(text))
            self.setAccessibleName(str(text))
        super().addItem(ui_text("filter_all") if self.count() == 0 else text, userData)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)


class EditorFilterReset(QPushButton):
    def __init__(self, search, filters=(), parent=None):
        from core.translations import ui_text
        super().__init__(ui_text("filters_clear"), parent)
        self.search = search
        self.filters = tuple(filters)
        configure_button(self, height=Size.COMPACT_CONTROL)
        self.setObjectName("EditorFilterReset")
        self.setProperty("designAction", "clear_filters")
        self.clicked.connect(self.clear)
        search.textChanged.connect(self.refresh)
        for combo in self.filters:
            combo.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.setEnabled(bool(self.search.text() or any(c.currentIndex() > 0 for c in self.filters)))

    def clear(self):
        self.search.clear()
        for combo in self.filters:
            combo.setCurrentIndex(0)
        self.refresh()


class EditorListRow(QPushButton):
    """Standard two-line sidebar row; the editor supplies labels and callbacks."""
    def __init__(self, *args, height=Size.LIST_ROW):
        super().__init__(*args)
        self.setFixedHeight(height)
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(ss_sidebar_btn())
        self.content_layout = QVBoxLayout(self)
        configure_layout(self.content_layout, LayoutRole.LIST_ROW)

    def set_selected(self, selected):
        self.setStyleSheet(ss_sidebar_btn(bool(selected)))

    def add_title(self, text="", *, value_font=None, flexible=False):
        label = configure_list_label(QLabel(str(text), self), title=True, value_font=value_font,
                                     fixed=not flexible)
        self.content_layout.addWidget(label)
        return label

    def add_subtitle(self, text="", *, value_font=None, flexible=False):
        label = configure_list_label(QLabel(str(text), self), value_font=value_font,
                                     fixed=not flexible)
        self.content_layout.addWidget(label)
        return label

    def set_texts(self, title, subtitle, *, title_limit=None, subtitle_limit=None):
        """Populate the common two-line row while preserving findChildren order."""
        for name, text, limit in (
            ("title_label", title, title_limit),
            ("subtitle_label", subtitle, subtitle_limit),
        ):
            label = getattr(self, name, None)
            if label is None:
                label = self.add_title() if name == "title_label" else self.add_subtitle()
                setattr(self, name, label)
            text = str(text)
            label.setText(text if limit is None or len(text) <= limit else text[:max(1, limit - 3)] + "...")
            label.setToolTip(text)


def configure_list_label(widget, *, title=False, value_font=None, fixed=True):
    widget.setFont(value_font or font(FontRole.CARD_TITLE if title else FontRole.LIST_CODE))
    widget.setStyleSheet(ss_main_label() if title else ss_dim_label())
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored,
                         QSizePolicy.Policy.Fixed if fixed else QSizePolicy.Policy.Preferred)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def configure_file_label(widget):
    widget.setFont(font(FontRole.FILE))
    widget.setStyleSheet(ss_file_label())
    return widget


def configure_card(widget, *, maximum_width=16777215, vertical_policy=QSizePolicy.Policy.Fixed):
    widget.setMinimumWidth(0)
    widget.setMaximumWidth(maximum_width)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, vertical_policy)
    return widget


def fit_scroll_page(scrollarea):
    """Fit direct form cards to wrapped content at their actual viewport width.

    A grid's intrinsic minimum can describe a much narrower layout and leave an
    empty scroll tail. This opt-in helper uses each card's height-for-width;
    it changes geometry only and retains the existing controls and layouts.
    """
    page = scrollarea.widget()
    layout = page.layout() if page is not None else None
    if layout is None:
        return
    margins = layout.contentsMargins()
    width = max(1, scrollarea.viewport().width() - margins.left() - margins.right())
    for index in range(layout.count()):
        card = layout.itemAt(index).widget()
        if card is None or card.objectName() != 'EditorCard' or card.layout() is None:
            continue
        # Reflow changes nested grids before Qt delivers their LayoutRequest.
        # Invalidate their owning widgets from the leaves up: invalidating only
        # the outer card keeps cached two-column hints and clips a one-column
        # form until an unrelated later resize.
        for child in reversed(card.findChildren(QWidget)):
            if child.layout() is not None:
                child.layout().invalidate()
                child.updateGeometry()
        card.layout().invalidate()
        height = card.layout().totalHeightForWidth(min(width, card.maximumWidth()))
        if height < 0:
            height = card.layout().totalSizeHint().height()
        if card.minimumHeight() != height or card.maximumHeight() != height:
            card.setFixedHeight(height)
    layout.invalidate()


def configure_field(frame, editor=None, *, minimum_width=0, minimum_height=None,
                    vertical_policy=QSizePolicy.Policy.Fixed):
    frame.setMinimumWidth(minimum_width)
    if minimum_height is not None:
        frame.setMinimumHeight(minimum_height)
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, vertical_policy)
    if editor is not None:
        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return frame


def configure_scrollarea(widget, *, transparent=False):
    """Keep scrollbar policy and content ownership with the editor."""
    widget.setWidgetResizable(True)
    widget.setFrameShape(QFrame.Shape.NoFrame)
    widget.setStyleSheet(ss_scrollarea_transparent() if transparent else ss_scrollarea())
    return widget


def configure_button(widget, *, accent=False, danger=False, height=Size.CONTROL, toggle=False):
    widget.setFont(font(FontRole.BUTTON))
    widget.setFixedHeight(height)
    widget.setStyleSheet(ss_toggle_btn() if toggle else ss_btn(accent=accent, danger=danger, compact=height == Size.COMPACT_CONTROL))
    _control_contract(widget, "button", height)
    return widget


def configure_icon_button(widget, role=IconButtonRole.TOOLBAR):
    width, height, icon_size = role.value
    widget.setFont(font(FontRole.BUTTON))
    widget.setFixedSize(width, height)
    widget.setIconSize(QSize(icon_size, icon_size))
    widget.setStyleSheet(ss_sidebar_edge_toggle() if role == IconButtonRole.SIDEBAR_TOGGLE else ss_icon_tool_btn())
    _control_contract(widget, "icon", height)
    widget.setProperty("designIconRole", role.name)
    return widget


def configure_input(widget, *, height=Size.CONTROL, monospace=None, compact=False, font=None):
    if monospace is None:
        monospace = not isinstance(widget, QComboBox)
    size = TypeSize.BODY if compact else TypeSize.TITLE
    widget.setFont(font or (mono_font(size) if monospace else ui_font(size)))
    widget.setFixedHeight(height)
    widget.setStyleSheet(ss_input(flat=compact))
    _control_contract(widget, "input", height)
    from core.ui.message_preview import install_message_tooltip
    install_message_tooltip(widget)
    return widget


def configure_search(widget):
    from core.translations import ui_text
    widget.setPlaceholderText(ui_text("search_placeholder"))
    widget.setClearButtonEnabled(True)
    widget.setFont(font(FontRole.SEARCH))
    widget.setFixedHeight(Size.SEARCH)
    widget.setStyleSheet(ss_search())
    _control_contract(widget, "search", Size.SEARCH)
    if not getattr(widget, "_design_filter_scheduled", False):
        widget._design_filter_scheduled = True
        QTimer.singleShot(0, lambda: _install_search_reset(widget))
    return widget


def _install_search_reset(widget):
    from PyQt6 import sip
    from core.ui.editor_chrome import install_editor_filters
    if sip.isdeleted(widget):
        return
    current = widget.parentWidget()
    while current is not None:
        if hasattr(current, "_file_actions"):
            install_editor_filters(current)
            return
        current = current.parentWidget()


def configure_tabs(widget):
    """Tab captions use one font; page bodies retain the standard body font."""
    widget.setFont(ui_font(TypeSize.CODE))
    widget.tabBar().setFont(ui_font(TypeSize.CODE))
    for index in range(widget.count()):
        widget.widget(index).setFont(ui_font())
    return widget


def configure_table(widget):
    widget.setFont(ui_font(TypeSize.BODY))
    widget.verticalHeader().setDefaultSectionSize(Size.TABLE_ROW)
    widget.setStyleSheet(ss_table())
    _control_contract(widget, "table")
    return widget


def configure_textedit(widget, *, monospace=False):
    widget.setFont(mono_font(TypeSize.BODY) if monospace else ui_font(TypeSize.BODY))
    widget.setStyleSheet(ss_textedit())
    _control_contract(widget, "textedit")
    return widget


def _control_contract(widget, role, height=None):
    widget.setProperty("designControlRole", role)
    widget.setProperty("designControlHeight", int(height) if height is not None else None)
    widget.setProperty("designFontFamily", widget.font().family())
    widget.setProperty("designFontSize", widget.font().pointSize())


def check_widget_contract(root):
    """Read-only runtime audit, including dynamically built forms and layouts."""
    issues = []
    for widget in [root, *root.findChildren(QWidget)]:
        role = widget.property("designControlRole")
        if not role:
            continue
        name = widget.objectName() or type(widget).__name__
        height = widget.property("designControlHeight")
        if height is not None and (widget.minimumHeight() != height or widget.maximumHeight() != height):
            issues.append(f"{name}: {role} height changed after configuration")
        if (widget.font().family() != widget.property("designFontFamily")
                or widget.font().pointSize() != widget.property("designFontSize")):
            issues.append(f"{name}: {role} font changed after configuration")
        if role == "icon":
            width, _, icon_size = IconButtonRole[widget.property("designIconRole")].value
            if widget.minimumWidth() != width or widget.maximumWidth() != width or widget.iconSize() != QSize(icon_size, icon_size):
                issues.append(f"{name}: icon geometry changed after configuration")
    for layout in root.findChildren(QLayout):
        role = layout.property("designLayoutRole")
        if not role:
            continue
        spec = layout_spec(LayoutRole(role))
        margins = layout.contentsMargins()
        actual = (margins.left(), margins.top(), margins.right(), margins.bottom())
        if actual != spec.margins:
            issues.append(f"{role}: layout margins changed after configuration")
        if spec.horizontal is not None:
            if layout.horizontalSpacing() != spec.horizontal or layout.verticalSpacing() != spec.vertical:
                issues.append(f"{role}: grid spacing changed after configuration")
        elif layout.spacing() != spec.spacing:
            # A stacked toolbar has no gap when its second row is empty.
            parent = layout.parentWidget()
            one_row_toolbar = (isinstance(parent, EditorToolbar) and parent._stacked
                               and parent.property("designToolbarRows") == 1 and layout.spacing() == 0)
            if not one_row_toolbar:
                issues.append(f"{role}: layout spacing changed after configuration")
    return issues
