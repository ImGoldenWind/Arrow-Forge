import os
import copy
import threading
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QTabBar, QTabWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QBrush, QCursor
from core.themes import P
from core.style_helpers import (
    ss_btn, ss_sep, ss_input, ss_search, ss_tab_widget, ss_scrollarea,
    ss_tab_bar, TOOLBAR_H, TOOLBAR_BTN_H,
)
from core.skeleton import SkeletonListRow
from parsers.info_parser import (
    parse_info_xfbin, save_info_xfbin,
    get_scene_description, make_default_collision,
    analyze_char_select, COLLISION_FIELDS, INT_FIELDS,
)
from core.translations import ui_text


# Helpers

def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _make_font(family="Segoe UI", size=12, bold=False):
    f = QFont(family, size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def _set_bg(widget, color):
    widget.setAutoFillBackground(True)
    p = widget.palette()
    p.setColor(widget.backgroundRole(), QColor(color))
    widget.setPalette(p)


def _style_entry(entry, *, h=32, font=None):
    entry.setStyleSheet(ss_input())
    entry.setFixedHeight(h)
    if font:
        entry.setFont(font)


# Collision canvas (visual map - read only)

class _CollisionMapCanvas(QWidget):
    """Read-only miniature visual representation of collision boxes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collisions = []
        self._canvas_w = 600
        self._canvas_h = 180
        self.setFixedHeight(self._canvas_h)
        self.setMinimumWidth(self._canvas_w)

    def set_collisions(self, collisions):
        self._collisions = list(collisions)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(P["bg_dark"]))

        collisions = self._collisions
        if not collisions:
            painter.end()
            return

        min_x = min(c.get('x', 0) for c in collisions)
        min_y = min(c.get('y', 0) for c in collisions)
        max_x = max(c.get('x', 0) + c.get('w', 0) for c in collisions)
        max_y = max(c.get('y', 0) + c.get('h', 0) for c in collisions)

        range_x = max(max_x - min_x, 1)
        range_y = max(max_y - min_y, 1)

        pad = 10
        draw_w = self.width() - 2 * pad
        draw_h = self.height() - 2 * pad
        scale_x = draw_w / range_x
        scale_y = draw_h / range_y
        scale = min(scale_x, scale_y)

        palette = [ui_text("ui_info_e74c3c"), ui_text("ui_info_3498db"), ui_text("ui_info_2ecc71"), ui_text("ui_info_f39c12"), ui_text("ui_info_9b59b6"),
                   ui_text("ui_info_1abc9c"), ui_text("ui_info_e67e22"), ui_text("ui_info_e91e63"), ui_text("ui_info_00bcd4"), ui_text("ui_info_8bc34a")]
        colors_by_name = {}

        for coll in collisions:
            cname = coll.get('name', '')
            if cname not in colors_by_name:
                colors_by_name[cname] = palette[len(colors_by_name) % len(palette)]

            cx = pad + (coll.get('x', 0) - min_x) * scale
            cy = pad + (coll.get('y', 0) - min_y) * scale
            cw = max(coll.get('w', 0) * scale, 2)
            ch = max(coll.get('h', 0) * scale, 2)

            color = QColor(colors_by_name[cname])
            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(cx), int(cy), int(cw), int(ch))

        painter.end()


# Interactive collision canvas (drag & resize)

class _InteractiveCollisionCanvas(QWidget):
    """Interactive visual map where the selected collision can be dragged / resized."""

    fields_changed = pyqtSignal()  # emitted when collision data changed by drag

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collisions = []
        self._selected_coll = None
        self._canvas_w = 620
        self._canvas_h = 260
        self.setFixedHeight(self._canvas_h)
        self.setMinimumWidth(self._canvas_w)
        self.setMouseTracking(True)

        self._drag_mode = None
        self._drag_start = None
        self._orig_x = 0
        self._orig_y = 0
        self._orig_w = 0
        self._orig_h = 0

        self._scale = 1.0
        self._min_x = 0
        self._min_y = 0
        self._pad = 14
        self._cursor_world = (0, 0)

        self._palette = [ui_text("ui_info_e74c3c"), ui_text("ui_info_3498db"), ui_text("ui_info_2ecc71"), ui_text("ui_info_f39c12"), ui_text("ui_info_9b59b6"),
                         ui_text("ui_info_1abc9c"), ui_text("ui_info_e67e22"), ui_text("ui_info_e91e63"), ui_text("ui_info_00bcd4"), ui_text("ui_info_8bc34a")]
        self._colors_by_name = {}

    def set_data(self, collisions, selected_coll):
        self._collisions = list(collisions)
        self._selected_coll = selected_coll
        self._colors_by_name = {}
        self._recompute_transform()
        self.update()

    def _recompute_transform(self):
        collisions = self._collisions
        if not collisions:
            return
        min_x = min(c.get('x', 0) for c in collisions)
        min_y = min(c.get('y', 0) for c in collisions)
        max_x = max(c.get('x', 0) + c.get('w', 0) for c in collisions)
        max_y = max(c.get('y', 0) + c.get('h', 0) for c in collisions)
        margin = 80
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin
        range_x = max(max_x - min_x, 1)
        range_y = max(max_y - min_y, 1)
        draw_w = self.width() - 2 * self._pad
        draw_h = self.height() - 2 * self._pad
        scale_x = draw_w / range_x
        scale_y = draw_h / range_y
        self._scale = min(scale_x, scale_y)
        self._min_x = min_x
        self._min_y = min_y

    def _w2c(self, wx, wy):
        return (self._pad + (wx - self._min_x) * self._scale,
                self._pad + (wy - self._min_y) * self._scale)

    def _c2w(self, cx, cy):
        return ((cx - self._pad) / self._scale + self._min_x,
                (cy - self._pad) / self._scale + self._min_y)

    def _handle_rects(self):
        """Return dict of handle_tag -> QRectF for the selected collision."""
        sel = self._selected_coll
        if not sel:
            return {}
        sx, sy = self._w2c(sel.get('x', 0), sel.get('y', 0))
        sw = max(sel.get('w', 0) * self._scale, 4)
        sh = max(sel.get('h', 0) * self._scale, 4)
        hs = 5
        positions = {
            'h_tl': (sx, sy), 'h_tr': (sx + sw, sy),
            'h_bl': (sx, sy + sh), 'h_br': (sx + sw, sy + sh),
            'h_t': (sx + sw / 2, sy), 'h_b': (sx + sw / 2, sy + sh),
            'h_l': (sx, sy + sh / 2), 'h_r': (sx + sw, sy + sh / 2),
        }
        from PyQt6.QtCore import QRectF
        return {tag: QRectF(hx - hs, hy - hs, 2 * hs, 2 * hs) for tag, (hx, hy) in positions.items()}

    def _sel_rect_canvas(self):
        sel = self._selected_coll
        if not sel:
            return None
        sx, sy = self._w2c(sel.get('x', 0), sel.get('y', 0))
        sw = max(sel.get('w', 0) * self._scale, 4)
        sh = max(sel.get('h', 0) * self._scale, 4)
        from PyQt6.QtCore import QRectF
        return QRectF(sx, sy, sw, sh)

    # Paint

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(P["bg_dark"]))

        collisions = self._collisions
        sel = self._selected_coll
        if not collisions:
            painter.end()
            return

        # Draw non-selected (dimmed, dashed)
        for coll_item in collisions:
            if coll_item is sel:
                continue
            cname = coll_item.get('name', '')
            if cname not in self._colors_by_name:
                self._colors_by_name[cname] = self._palette[len(self._colors_by_name) % len(self._palette)]
            cx, cy = self._w2c(coll_item.get('x', 0), coll_item.get('y', 0))
            cw = max(coll_item.get('w', 0) * self._scale, 2)
            ch = max(coll_item.get('h', 0) * self._scale, 2)
            color = QColor(self._colors_by_name[cname])
            pen = QPen(color, 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(cx), int(cy), int(cw), int(ch))

        # Draw selected collision
        if sel:
            cname = sel.get('name', '')
            if cname not in self._colors_by_name:
                self._colors_by_name[cname] = self._palette[len(self._colors_by_name) % len(self._palette)]
            sel_fill = QColor(self._colors_by_name[cname])
            sel_fill.setAlpha(60)

            sx, sy = self._w2c(sel.get('x', 0), sel.get('y', 0))
            sw = max(sel.get('w', 0) * self._scale, 4)
            sh = max(sel.get('h', 0) * self._scale, 4)

            painter.setPen(QPen(QColor(ui_text("ui_costume_ffffff")), 2))
            painter.setBrush(QBrush(sel_fill))
            painter.drawRect(int(sx), int(sy), int(sw), int(sh))

            # Label
            idx = 0
            try:
                idx = collisions.index(sel)
            except ValueError:
                pass
            painter.setPen(QColor(ui_text("ui_costume_ffffff")))
            painter.setFont(QFont('Consolas', 8))
            from PyQt6.QtCore import QRectF
            painter.drawText(QRectF(sx, sy, sw, sh), Qt.AlignmentFlag.AlignCenter,
                             f"#{idx} {cname}")

            # Handles
            handle_rects = self._handle_rects()
            for tag, rect in handle_rects.items():
                painter.setPen(QPen(QColor(P["accent"]), 1))
                painter.setBrush(QBrush(QColor(ui_text("ui_costume_ffffff"))))
                painter.drawRect(rect)

        painter.end()

    # Mouse events

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._selected_coll:
            return
        pos = event.position()
        ex, ey = pos.x(), pos.y()

        # Check handles first
        from PyQt6.QtCore import QPointF
        pt = QPointF(ex, ey)
        for tag, rect in self._handle_rects().items():
            inflated = rect.adjusted(-4, -4, 4, 4)
            if inflated.contains(pt):
                self._start_drag(tag, ex, ey)
                return

        # Check if inside selected rect
        sr = self._sel_rect_canvas()
        if sr and sr.contains(pt):
            self._start_drag('move', ex, ey)

    def _start_drag(self, mode, ex, ey):
        self._drag_mode = mode
        self._drag_start = (ex, ey)
        sel = self._selected_coll
        self._orig_x = sel.get('x', 0)
        self._orig_y = sel.get('y', 0)
        self._orig_w = sel.get('w', 0)
        self._orig_h = sel.get('h', 0)

    def mouseMoveEvent(self, event):
        pos = event.position()
        ex, ey = pos.x(), pos.y()
        self._cursor_world = self._c2w(ex, ey)

        if not self._drag_mode or not self._drag_start or not self._selected_coll:
            return

        dx_px = ex - self._drag_start[0]
        dy_px = ey - self._drag_start[1]
        sc = self._scale
        dx_world = round(dx_px / sc)
        dy_world = round(dy_px / sc)

        coll = self._selected_coll
        mode = self._drag_mode

        if mode == 'move':
            coll['x'] = self._orig_x + dx_world
            coll['y'] = self._orig_y + dy_world
        elif mode == 'h_br':
            coll['w'] = max(self._orig_w + dx_world, 1)
            coll['h'] = max(self._orig_h + dy_world, 1)
        elif mode == 'h_bl':
            coll['x'] = self._orig_x + dx_world
            coll['w'] = max(self._orig_w - dx_world, 1)
            coll['h'] = max(self._orig_h + dy_world, 1)
        elif mode == 'h_tr':
            coll['y'] = self._orig_y + dy_world
            coll['w'] = max(self._orig_w + dx_world, 1)
            coll['h'] = max(self._orig_h - dy_world, 1)
        elif mode == 'h_tl':
            coll['x'] = self._orig_x + dx_world
            coll['y'] = self._orig_y + dy_world
            coll['w'] = max(self._orig_w - dx_world, 1)
            coll['h'] = max(self._orig_h - dy_world, 1)
        elif mode == 'h_r':
            coll['w'] = max(self._orig_w + dx_world, 1)
        elif mode == 'h_l':
            coll['x'] = self._orig_x + dx_world
            coll['w'] = max(self._orig_w - dx_world, 1)
        elif mode == 'h_t':
            coll['y'] = self._orig_y + dy_world
            coll['h'] = max(self._orig_h - dy_world, 1)
        elif mode == 'h_b':
            coll['h'] = max(self._orig_h + dy_world, 1)

        self.update()
        self.fields_changed.emit()

    def mouseReleaseEvent(self, event):
        if self._drag_mode:
            self.fields_changed.emit()
        self._drag_mode = None
        self._drag_start = None

    def get_cursor_world(self):
        return self._cursor_world


# Set / Collision list button widgets

class _SetButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, desc, sub_text, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._selected = False
        self._hovered = False
        self._desc = desc
        self._sub = sub_text

    def set_selected(self, val):
        self._selected = val
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            bg = QColor(P["bg_card"])
        elif self._hovered:
            bg = QColor(P["bg_card_hov"])
        else:
            bg = QColor("transparent")

        if bg.alpha() > 0:
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 6, 6)

        painter.setPen(QColor(P["text_main"]))
        painter.setFont(_make_font("Segoe UI", 12, bold=True))
        painter.drawText(8, 16, self._desc)

        painter.setPen(QColor(P["text_dim"]))
        painter.setFont(_make_font("Consolas", 10))
        painter.drawText(8, 34, self._sub)
        painter.end()


class _CollButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, idx, coll, t_func, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._selected = False
        self._hovered = False
        self._idx = idx
        self._coll = coll
        self.t = t_func

    def set_selected(self, val):
        self._selected = val
        self.update()

    def update_from_coll(self):
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            bg = QColor(P["bg_card"])
        elif self._hovered:
            bg = QColor(P["bg_card_hov"])
        else:
            bg = QColor("transparent")

        if bg.alpha() > 0:
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 4, 4)

        coll = self._coll
        painter.setPen(QColor(P["accent"]))
        painter.setFont(_make_font("Consolas", 10, bold=True))
        painter.drawText(4, 14, f"#{self._idx:02d}")

        cname = coll.get('name', '') or self.t("coll_unnamed")
        painter.setPen(QColor(P["text_main"]))
        painter.setFont(_make_font("Segoe UI", 11))
        painter.drawText(34, 14, cname)

        pos_text = f"{coll.get('x', 0)},{coll.get('y', 0)} {coll.get('w', 0)}x{coll.get('h', 0)}"
        painter.setPen(QColor(P["text_dim"]))
        painter.setFont(_make_font("Consolas", 9))
        painter.drawText(34, 30, pos_text)
        painter.end()


#  InfoEditor  –  main widget

class InfoEditor(QWidget):
    """Full-featured editor for info.xfbin UI collision files.

    Displays all scene sets and their collision rectangles,
    allows editing, adding, deleting collisions, and provides
    analysis of the character select screen layout.
    """

    _load_done_signal = pyqtSignal(str, object, list, object)
    _load_error_signal = pyqtSignal(str)

    def __init__(self, parent, lang_func, embedded=False):
        super().__init__(parent)
        self.t = lang_func

        self._raw_data = None
        self._sets = []
        self._meta = None
        self._current_set = None
        self._current_coll = None
        self._set_buttons = []
        self._coll_buttons = []
        self._coll_button_groups = {}
        self._coll_tabs = []
        self._updating_coll_tabs = False
        self._fields = {}
        self._interactive_canvas = None
        self._computed_labels = {}
        self._coord_timer = None
        self._vis_coord_label = None

        self._filepath = None
        self._dirty = False

        self._load_done_signal.connect(self._on_load_done)
        self._load_error_signal.connect(self._on_load_error)

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Toolbar
        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        open_btn = QPushButton(self.t("btn_open_file"))
        open_btn.setFixedHeight(TOOLBAR_BTN_H)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(f"color: {P['text_dim']};")
        top_layout.addWidget(self._file_label)

        top_layout.addStretch()

        self._info_label = QLabel("")
        self._info_label.setFont(QFont("Consolas", 10))
        self._info_label.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        top_layout.addWidget(self._info_label)

        root_layout.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root_layout.addWidget(sep)

        # Main area: left sidebar (scenes) + collision tabs + editor
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left sidebar: scene set list
        left_panel = self._build_set_list()
        main_layout.addWidget(left_panel)

        # Separator
        sep_l = QFrame()
        sep_l.setFixedWidth(1)
        sep_l.setStyleSheet(ss_sep())
        main_layout.addWidget(sep_l)

        # Tab widget — "Collisions" tab (collision list + editor)
        right_panel = QWidget()
        right_panel.setStyleSheet(f"background-color: {P['bg_dark']};")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        coll_tabs_bar = self._build_collision_tabs_bar()
        right_layout.addWidget(coll_tabs_bar)

        sep_tabs = QFrame()
        sep_tabs.setFixedHeight(1)
        sep_tabs.setStyleSheet(ss_sep())
        right_layout.addWidget(sep_tabs)

        # Right panel: editor (scrollable)
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_content = QWidget()
        self._editor_content.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_content)
        self._editor_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_content)
        right_layout.addWidget(self._editor_scroll, 1)

        # Placeholder
        self._placeholder = QLabel(self.t("placeholder_info"))
        self._placeholder.setFont(_make_font("Segoe UI", 16))
        self._placeholder.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setContentsMargins(0, 60, 0, 60)
        self._editor_layout.addWidget(self._placeholder)

        main_layout.addWidget(right_panel, 1)

        root_layout.addWidget(main, 1)

    def _build_set_list(self):
        panel = QWidget()
        panel.setFixedWidth(260)
        panel.setStyleSheet(f"background-color: {P['bg_panel']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)

        # Search
        self._set_search_entry = QLineEdit()
        self._set_search_entry.setPlaceholderText(self.t("search_scenes_placeholder"))
        self._set_search_entry.setFixedHeight(32)
        self._set_search_entry.setFont(QFont("Segoe UI", 13))
        self._set_search_entry.setStyleSheet(ss_search())
        self._set_search_entry.textChanged.connect(self._filter_set_list)
        layout.addWidget(self._set_search_entry)

        # Actions
        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_set_btn = QPushButton(self.t("btn_add_scene"))
        self._add_set_btn.setFixedHeight(28)
        self._add_set_btn.setFont(btn_font)
        self._add_set_btn.setStyleSheet(ss_btn())
        self._add_set_btn.setEnabled(False)
        self._add_set_btn.clicked.connect(self._add_new_set)
        al.addWidget(self._add_set_btn, 1)

        self._del_set_btn = QPushButton(self.t("btn_delete"))
        self._del_set_btn.setFixedHeight(28)
        self._del_set_btn.setFont(btn_font)
        self._del_set_btn.setStyleSheet(ss_btn(danger=True))
        self._del_set_btn.setEnabled(False)
        self._del_set_btn.clicked.connect(self._delete_set)
        al.addWidget(self._del_set_btn, 1)

        layout.addWidget(actions)

        # Scrollable set list
        self._set_scroll = QScrollArea()
        self._set_scroll.setWidgetResizable(True)
        self._set_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._set_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 10px; }}"
            f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 5px; min-height: 20px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {P['secondary']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        self._set_list_widget = QWidget()
        self._set_list_widget.setStyleSheet("background: transparent;")
        self._set_list_layout = QVBoxLayout(self._set_list_widget)
        self._set_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._set_list_layout.setContentsMargins(0, 0, 0, 0)
        self._set_list_layout.setSpacing(1)
        self._set_scroll.setWidget(self._set_list_widget)
        layout.addWidget(self._set_scroll, 1)

        return panel

    def _build_collision_tabs_bar(self):
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self._coll_header = QLabel(self.t("collisions_header"))
        self._coll_header.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._coll_header.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        layout.addWidget(self._coll_header)

        self._coll_tab_widget = QTabBar()
        self._coll_tab_widget.setFont(QFont("Segoe UI", 10))
        self._coll_tab_widget.setExpanding(False)
        self._coll_tab_widget.setDrawBase(False)
        self._coll_tab_widget.setUsesScrollButtons(True)
        self._coll_tab_widget.setStyleSheet(ss_tab_bar())
        self._coll_tab_widget.currentChanged.connect(self._on_collision_tab_changed)
        layout.addWidget(self._coll_tab_widget, 1)

        btn_font = QFont("Segoe UI", 10)

        self._add_coll_btn = QPushButton(self.t("btn_new"))
        self._add_coll_btn.setFixedHeight(28)
        self._add_coll_btn.setFont(btn_font)
        self._add_coll_btn.setStyleSheet(ss_btn())
        self._add_coll_btn.setEnabled(False)
        self._add_coll_btn.clicked.connect(self._add_collision)
        layout.addWidget(self._add_coll_btn)

        self._dup_coll_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_coll_btn.setFixedHeight(28)
        self._dup_coll_btn.setFont(btn_font)
        self._dup_coll_btn.setStyleSheet(ss_btn())
        self._dup_coll_btn.setEnabled(False)
        self._dup_coll_btn.clicked.connect(self._duplicate_collision)
        layout.addWidget(self._dup_coll_btn)

        self._del_coll_btn = QPushButton(self.t("btn_delete"))
        self._del_coll_btn.setFixedHeight(28)
        self._del_coll_btn.setFont(btn_font)
        self._del_coll_btn.setStyleSheet(ss_btn(danger=True))
        self._del_coll_btn.setEnabled(False)
        self._del_coll_btn.clicked.connect(self._delete_collision)
        layout.addWidget(self._del_coll_btn)

        return bar

    def _build_coll_list(self):
        panel = QWidget()
        panel.setFixedWidth(220)
        panel.setStyleSheet(f"background-color: {P['bg_panel']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(4)

        # Header
        self._coll_header = QLabel(self.t("collisions_header"))
        self._coll_header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._coll_header.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        layout.addWidget(self._coll_header)

        # Search
        self._coll_search_entry = QLineEdit()
        self._coll_search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._coll_search_entry.setFixedHeight(32)
        self._coll_search_entry.setFont(QFont("Segoe UI", 13))
        self._coll_search_entry.setStyleSheet(ss_search())
        self._coll_search_entry.textChanged.connect(self._filter_coll_list)
        layout.addWidget(self._coll_search_entry)

        # Actions — same as Character Stats
        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 2, 0, 4)
        al.setSpacing(4)

        btn_font = QFont("Segoe UI", 10)

        self._add_coll_btn = QPushButton(self.t("btn_new"))
        self._add_coll_btn.setFixedHeight(28)
        self._add_coll_btn.setFont(btn_font)
        self._add_coll_btn.setStyleSheet(ss_btn())
        self._add_coll_btn.setEnabled(False)
        self._add_coll_btn.clicked.connect(self._add_collision)
        al.addWidget(self._add_coll_btn, 1)

        self._dup_coll_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_coll_btn.setFixedHeight(28)
        self._dup_coll_btn.setFont(btn_font)
        self._dup_coll_btn.setStyleSheet(ss_btn())
        self._dup_coll_btn.setEnabled(False)
        self._dup_coll_btn.clicked.connect(self._duplicate_collision)
        al.addWidget(self._dup_coll_btn, 1)

        self._del_coll_btn = QPushButton(self.t("btn_delete"))
        self._del_coll_btn.setFixedHeight(28)
        self._del_coll_btn.setFont(btn_font)
        self._del_coll_btn.setStyleSheet(ss_btn(danger=True))
        self._del_coll_btn.setEnabled(False)
        self._del_coll_btn.clicked.connect(self._delete_collision)
        al.addWidget(self._del_coll_btn, 1)

        layout.addWidget(actions)

        # Collision list tabs, grouped by collision name
        self._coll_tab_widget = QTabWidget()
        self._coll_tab_widget.setFont(QFont("Segoe UI", 10))
        self._coll_tab_widget.setStyleSheet(ss_tab_widget())
        self._coll_tab_widget.setDocumentMode(True)
        self._coll_tab_widget.setUsesScrollButtons(True)
        layout.addWidget(self._coll_tab_widget, 1)

        return panel

    # File I/O

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_info"), "",
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        self._file_label.setText(self.t("loading"))
        self._show_set_skeleton()

        def worker():
            try:
                raw_data, sets, meta = parse_info_xfbin(path)
            except Exception as e:
                self._load_error_signal.emit(str(e))
                return
            self._load_done_signal.emit(path, raw_data, sets, meta)

        threading.Thread(target=worker, daemon=True).start()

    def _show_set_skeleton(self):
        _clear_layout(self._set_list_layout)
        self._set_buttons = []
        for _ in range(12):
            skel = SkeletonListRow(self._set_list_widget)
            self._set_list_layout.addWidget(skel)

    def _on_load_error(self, msg):
        _clear_layout(self._set_list_layout)
        self._file_label.setText(self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_load_error", error=msg))

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.setEnabled(True)
        name = os.path.basename(self._filepath) if self._filepath else self.t("no_file_loaded")
        self._file_label.setText(ui_text("ui_effect_value", p0=name))
        self._file_label.setStyleSheet(f"color: {P['accent']};")

    def _on_load_done(self, path, raw_data, sets, meta):
        self._raw_data = raw_data
        self._sets = sets
        self._meta = meta
        self._filepath = path
        self._dirty = False
        self._current_set = None
        self._current_coll = None
        self._file_label.setText(os.path.basename(path))
        self._file_label.setStyleSheet(f"color: {P['text_file']};")
        self._info_label.setText(self.t("scenes_count", n=len(sets)))
        self._save_btn.setEnabled(True)
        self._add_set_btn.setEnabled(True)
        self._del_set_btn.setEnabled(True)
        self._populate_set_list()

    def _save_file(self):
        if not self._raw_data or not self._filepath:
            return
        self._apply_fields()
        try:
            save_info_xfbin(self._filepath, self._raw_data, self._sets, self._meta)
            self._dirty = False
            self._file_label.setText(os.path.basename(self._filepath))
            self._file_label.setStyleSheet(f"color: {P['text_file']};")
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                 self.t("msg_save_error", error=e))

    # Set list

    def _populate_set_list(self):
        _clear_layout(self._set_list_layout)
        self._set_buttons = []

        for s in self._sets:
            desc = get_scene_description(s['name'])
            num = len(s['collisions'])
            sub_text = f"{s['name']}  ({num})"

            btn = _SetButton(desc, sub_text, self._set_list_widget)
            btn.clicked.connect(lambda ss=s: self._select_set(ss))
            self._set_list_layout.addWidget(btn)
            self._set_buttons.append((btn, s))

        if self._sets:
            self._select_set(self._sets[0])

    def _filter_set_list(self):
        query = self._set_search_entry.text().lower()
        for btn, s in self._set_buttons:
            desc = get_scene_description(s['name']).lower()
            match = query in s['name'].lower() or query in desc
            btn.setVisible(match)

    def _select_set(self, s):
        self._apply_fields()
        self._current_set = s
        self._current_coll = None
        for btn, ss in self._set_buttons:
            btn.set_selected(ss is s)

        self._coll_header.setText(self.t("collisions_header_count", n=len(s['collisions'])))
        self._add_coll_btn.setEnabled(True)
        self._dup_coll_btn.setEnabled(True)
        self._del_coll_btn.setEnabled(True)
        self._populate_coll_list()
        if s['collisions']:
            self._select_collision(s['collisions'][0])
        else:
            self._build_set_overview()

    # Collision list

    def _coll_tab_label(self, idx, coll):
        cname = coll.get('name', '') or self.t("coll_unnamed")
        return f"#{idx:02d} {cname}"

    def _populate_coll_list(self, preferred_coll=None):
        current_tab = self._coll_tab_widget.currentIndex() if hasattr(self, '_coll_tab_widget') else 0
        self._updating_coll_tabs = True
        while self._coll_tab_widget.count():
            self._coll_tab_widget.removeTab(0)
        self._coll_buttons = []
        self._coll_button_groups = {}
        self._coll_tabs = []
        if not self._current_set:
            self._updating_coll_tabs = False
            return

        preferred_tab = -1
        for i, coll in enumerate(self._current_set['collisions']):
            self._coll_tab_widget.addTab(self._coll_tab_label(i, coll))
            self._coll_tabs.append(coll)
            if preferred_coll is not None and coll is preferred_coll:
                preferred_tab = i

        if preferred_tab >= 0:
            self._coll_tab_widget.setCurrentIndex(preferred_tab)
        elif self._coll_tab_widget.count():
            self._coll_tab_widget.setCurrentIndex(min(current_tab, self._coll_tab_widget.count() - 1))
        self._updating_coll_tabs = False

    def _refresh_collision_tabs(self, preferred_coll=None):
        self._populate_coll_list(preferred_coll=preferred_coll or self._current_coll)

    def _filter_coll_list(self):
        pass

    def _on_collision_tab_changed(self, idx):
        if self._updating_coll_tabs or idx < 0 or idx >= len(self._coll_tabs):
            return
        self._select_collision(self._coll_tabs[idx])

    def _select_collision(self, coll):
        self._apply_fields()
        self._current_coll = coll
        if coll in self._coll_tabs:
            idx = self._coll_tabs.index(coll)
            if self._coll_tab_widget.currentIndex() != idx:
                self._updating_coll_tabs = True
                self._coll_tab_widget.setCurrentIndex(idx)
                self._updating_coll_tabs = False
        self._build_collision_editor(coll)

    # Apply field changes

    def _apply_fields(self):
        if not self._current_coll or not self._fields:
            return
        coll = self._current_coll
        for field in COLLISION_FIELDS:
            if field in self._fields:
                try:
                    val = self._fields[field].text().strip()
                    if field in INT_FIELDS:
                        coll[field] = int(val)
                    else:
                        coll[field] = val
                except (ValueError, KeyError, RuntimeError):
                    pass

        # Also apply set name if present
        if '_set_name' in self._fields:
            try:
                new_name = self._fields['_set_name'].text().strip()
                if self._current_set and new_name:
                    self._current_set['name'] = new_name
            except (KeyError, RuntimeError):
                pass

        self._update_coll_list_labels()

    # Set overview (shown when set selected, no collision selected)

    def _build_set_overview(self):
        if self._coord_timer is not None:
            self._coord_timer.stop()
        self._vis_coord_label = None
        self._interactive_canvas = None
        _clear_layout(self._editor_layout)
        self._fields = {}

        s = self._current_set
        if not s:
            return

        desc = get_scene_description(s['name'])

        # Set header
        hdr = QWidget()
        hdr.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        hdr_inner = QWidget()
        hdr_inner.setStyleSheet("background: transparent;")
        hdr_grid = QGridLayout(hdr_inner)
        hdr_grid.setContentsMargins(0, 0, 0, 0)
        hdr_grid.setColumnStretch(0, 1)
        hdr_grid.setColumnStretch(1, 1)

        # Scene name (editable)
        name_w = QWidget()
        name_w.setStyleSheet("background: transparent;")
        name_l = QVBoxLayout(name_w)
        name_l.setContentsMargins(0, 0, 16, 0)
        name_l.setSpacing(2)
        lbl = QLabel(self.t("label_scene_name"))
        lbl.setFont(_make_font("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        name_l.addWidget(lbl)
        e_name = QLineEdit()
        e_name.setText(s['name'])
        _style_entry(e_name, h=36, font=_make_font("Consolas", 16, bold=True))
        e_name.setStyleSheet(e_name.styleSheet() + f" QLineEdit {{ color: {P['accent']}; }}")
        name_l.addWidget(e_name)
        self._fields['_set_name'] = e_name
        hdr_grid.addWidget(name_w, 0, 0)

        # Description (read-only)
        desc_w = QWidget()
        desc_w.setStyleSheet("background: transparent;")
        desc_l = QVBoxLayout(desc_w)
        desc_l.setContentsMargins(0, 0, 0, 0)
        desc_l.setSpacing(2)
        lbl2 = QLabel(self.t("label_description"))
        lbl2.setFont(_make_font("Segoe UI", 12))
        lbl2.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        desc_l.addWidget(lbl2)
        lbl3 = QLabel(desc)
        lbl3.setFont(_make_font("Segoe UI", 15, bold=True))
        lbl3.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        lbl3.setContentsMargins(0, 4, 0, 0)
        desc_l.addWidget(lbl3)
        hdr_grid.addWidget(desc_w, 0, 1)

        hdr_layout.addWidget(hdr_inner)
        self._editor_layout.addWidget(hdr)

        # Stats
        self._add_section(self.t("section_statistics"))
        stats_panel = QWidget()
        stats_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        sp_layout = QVBoxLayout(stats_panel)
        sp_layout.setContentsMargins(16, 12, 16, 12)

        sg = QWidget()
        sg.setStyleSheet("background: transparent;")
        sg_grid = QGridLayout(sg)
        sg_grid.setContentsMargins(0, 0, 0, 0)

        collisions = s['collisions']
        unique_names = set(c.get('name', '') for c in collisions)
        unique_types = set(str(c.get('type', 0)) for c in collisions)

        stats = [
            (self.t("stats_total_collisions"), str(len(collisions))),
            (self.t("stats_unique_names"), str(len(unique_names))),
            (self.t("stats_types_used"), ", ".join(sorted(unique_types)) if unique_types else self.t("stats_types_none")),
        ]
        for i, (label, value) in enumerate(stats):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(8, 0, 8, 0)
            fl.setSpacing(0)
            sl = QLabel(label)
            sl.setFont(_make_font("Segoe UI", 12))
            sl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(sl)
            vl = QLabel(value)
            vl.setFont(_make_font("Consolas", 20, bold=True))
            vl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
            fl.addWidget(vl)
            sg_grid.addWidget(fw, 0, i)
            sg_grid.setColumnStretch(i, 1)

        sp_layout.addWidget(sg)
        self._editor_layout.addWidget(stats_panel)

        # Collision name breakdown
        if collisions:
            self._add_section(self.t("section_coll_names"))
            names_panel = QWidget()
            names_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
            np_layout = QVBoxLayout(names_panel)
            np_layout.setContentsMargins(16, 12, 16, 12)

            name_counts = {}
            for c in collisions:
                n = c.get('name', '') or self.t("coll_unnamed")
                name_counts[n] = name_counts.get(n, 0) + 1

            for n, count in sorted(name_counts.items()):
                row_w = QWidget()
                row_w.setStyleSheet("background: transparent;")
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(0, 1, 0, 1)
                rl.setSpacing(8)
                cl = QLabel(ui_text("ui_info_value_x", p0=count))
                cl.setFont(_make_font("Consolas", 12, bold=True))
                cl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
                cl.setFixedWidth(40)
                rl.addWidget(cl)
                nl = QLabel(n)
                nl.setFont(_make_font("Consolas", 12))
                nl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
                rl.addWidget(nl)
                rl.addStretch()
                np_layout.addWidget(row_w)

            self._editor_layout.addWidget(names_panel)

        # Visual map for this set
        if collisions:
            self._add_section(self.t("section_visual_layout"))
            self._build_visual_map(collisions)

        # Special analysis for character select
        if s['name'] == ui_text("ui_info_ccscenebattleselectchar"):
            self._add_section(self.t("section_css_analysis"))
            self._build_css_analysis()

        # Bottom spacer
        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)

    def _build_visual_map(self, collisions):
        """Draw a miniature visual representation of collision boxes."""
        map_panel = QWidget()
        map_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        mp_layout = QVBoxLayout(map_panel)
        mp_layout.setContentsMargins(12, 12, 12, 12)

        canvas = _CollisionMapCanvas()
        canvas.set_collisions(collisions)
        mp_layout.addWidget(canvas)

        self._editor_layout.addWidget(map_panel)

    def _build_css_analysis(self):
        """Build character select screen analysis."""
        analysis = analyze_char_select(self._sets)
        if not analysis:
            return

        panel = QWidget()
        panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        p_layout = QVBoxLayout(panel)
        p_layout.setContentsMargins(16, 12, 16, 12)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        ig = QGridLayout(inner)
        ig.setContentsMargins(0, 0, 0, 0)

        # Stats
        stats = [
            (self.t("css_face_icon_slots"), str(analysis['face_icon_count'])),
            (self.t("css_grid_rows"), str(analysis['row_count'])),
            (self.t("css_typical_size"), f"{analysis['typical_size'][0]}x{analysis['typical_size'][1]}"),
        ]
        for i, (label, value) in enumerate(stats):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(8, 0, 8, 0)
            fl.setSpacing(0)
            sl = QLabel(label)
            sl.setFont(_make_font("Segoe UI", 12))
            sl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(sl)
            vl = QLabel(value)
            vl.setFont(_make_font("Consolas", 20, bold=True))
            vl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
            fl.addWidget(vl)
            ig.addWidget(fw, 0, i)
            ig.setColumnStretch(i, 1)

        # Row breakdown
        row_info = QWidget()
        row_info.setStyleSheet("background: transparent;")
        ri_layout = QVBoxLayout(row_info)
        ri_layout.setContentsMargins(8, 8, 8, 0)
        ri_layout.setSpacing(1)
        for y_val in analysis['y_values']:
            row_colls = analysis['rows'][y_val]
            rl = QLabel(ui_text("ui_info_row_y_value_value_slots_x_value_value", p0=y_val, p1=len(row_colls), p2=row_colls[0]['x'], p3=row_colls[-1]['x'] + row_colls[-1]['w']))
            rl.setFont(_make_font("Consolas", 11))
            rl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            ri_layout.addWidget(rl)
        ig.addWidget(row_info, 1, 0, 1, 3)

        # Note
        note_w = QWidget()
        note_w.setStyleSheet("background: transparent;")
        note_l = QVBoxLayout(note_w)
        note_l.setContentsMargins(8, 10, 8, 0)
        note_text = self.t("css_analysis_note", face_count=analysis['face_icon_count'])
        nl = QLabel(note_text)
        nl.setFont(_make_font("Segoe UI", 12))
        nl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        nl.setWordWrap(True)
        nl.setMaximumWidth(500)
        note_l.addWidget(nl)
        ig.addWidget(note_w, 2, 0, 1, 3)

        p_layout.addWidget(inner)
        self._editor_layout.addWidget(panel)

    # Interactive visual map (collision editor)

    def _build_interactive_map(self, collisions, selected_coll):
        """Draw an interactive visual map where the selected collision can be
        dragged to move and resized via corner handles."""
        self._add_section(self.t("section_visual_layout_drag"))

        map_panel = QWidget()
        map_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        mp_layout = QVBoxLayout(map_panel)
        mp_layout.setContentsMargins(12, 12, 12, 12)

        self._interactive_canvas = _InteractiveCollisionCanvas()
        self._interactive_canvas.set_data(collisions, selected_coll)
        self._interactive_canvas.fields_changed.connect(self._on_canvas_drag)
        mp_layout.addWidget(self._interactive_canvas)

        # Coordinate label
        self._vis_coord_label = QLabel("")
        self._vis_coord_label.setFont(_make_font("Consolas", 10))
        self._vis_coord_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        mp_layout.addWidget(self._vis_coord_label)

        # Timer to update coord label — reuse existing timer if present
        if self._coord_timer is None:
            self._coord_timer = QTimer(self)
            self._coord_timer.setInterval(100)
            self._coord_timer.timeout.connect(self._update_coord_label)
        self._coord_timer.start()

        self._editor_layout.addWidget(map_panel)

    def _update_coord_label(self):
        try:
            if self._interactive_canvas and self._vis_coord_label:
                wx, wy = self._interactive_canvas.get_cursor_world()
                self._vis_coord_label.setText(self.t("vis_cursor", x=int(wx), y=int(wy)))
        except RuntimeError:
            pass

    def _on_canvas_drag(self):
        """Called when the interactive canvas changes collision data via drag."""
        self._mark_dirty()
        self._update_fields_from_coll()
        self._update_computed_labels()
        self._update_coll_list_labels()

    def _update_fields_from_coll(self):
        """Update form fields from the current collision data (after drag)."""
        coll = self._current_coll
        if not coll or not self._fields:
            return
        for key in ('x', 'y', 'w', 'h'):
            if key in self._fields:
                entry = self._fields[key]
                entry.blockSignals(True)
                entry.setText(str(coll.get(key, 0)))
                entry.blockSignals(False)

    def _update_computed_labels(self):
        """Update the computed info labels after position/size change."""
        if not self._computed_labels:
            return
        coll = self._current_coll
        if not coll:
            return
        x, y = coll.get('x', 0), coll.get('y', 0)
        w, h = coll.get('w', 0), coll.get('h', 0)
        rtoX, rtoY = coll.get(ui_text("ui_info_rtox"), 0), coll.get(ui_text("ui_info_rtoy"), 0)
        lboX, lboY = coll.get(ui_text("ui_info_lbox"), 0), coll.get(ui_text("ui_info_lboy"), 0)
        values = {
            'center': f"({x + w // 2}, {y + h // 2})",
            'br': f"({x + w}, {y + h})",
            'eff': f"({x + lboX}, {y + rtoY}) to ({x + w + rtoX}, {y + h + lboY})",
        }
        for key, lbl in self._computed_labels.items():
            if key in values:
                try:
                    lbl.setText(values[key])
                except RuntimeError:
                    pass

    def _update_coll_list_labels(self):
        """Update the current collision tab label."""
        coll = self._current_coll
        if not coll or not self._current_set or coll not in self._current_set['collisions']:
            return
        idx = self._current_set['collisions'].index(coll)
        if idx < self._coll_tab_widget.count():
            self._coll_tab_widget.setTabText(idx, self._coll_tab_label(idx, coll))

    def _update_vis_from_fields(self):
        """Update the canvas visualization when form fields change."""
        if not self._interactive_canvas or not self._current_coll or not self._fields:
            return
        coll = self._current_coll
        changed = False
        for key in ('x', 'y', 'w', 'h'):
            if key in self._fields:
                try:
                    val = self._fields[key].text().strip()
                    coll[key] = int(val)
                    changed = True
                except (ValueError, KeyError):
                    pass
        if changed:
            self._mark_dirty()
        self._interactive_canvas.update()
        self._update_computed_labels()

    # Collision editor

    def _build_collision_editor(self, coll):
        if self._coord_timer is not None:
            self._coord_timer.stop()
        self._vis_coord_label = None
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._interactive_canvas = None
        self._computed_labels = {}

        idx = 0
        if self._current_set:
            try:
                idx = self._current_set['collisions'].index(coll)
            except ValueError:
                pass

        set_desc = get_scene_description(self._current_set['name']) if self._current_set else ''

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        lbl = QLabel(self.t("coll_header_label", idx=idx, desc=set_desc))
        lbl.setFont(_make_font("Segoe UI", 14, bold=True))
        lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        hdr_layout.addWidget(lbl)
        self._editor_layout.addWidget(hdr)

        # Interactive visual map
        if self._current_set:
            self._build_interactive_map(self._current_set['collisions'], coll)

        # Identity fields
        self._add_section(self.t("section_identity"))
        id_panel = QWidget()
        id_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        ip_layout = QVBoxLayout(id_panel)
        ip_layout.setContentsMargins(12, 12, 12, 12)

        ig = QWidget()
        ig.setStyleSheet("background: transparent;")
        ig_grid = QGridLayout(ig)
        ig_grid.setContentsMargins(0, 0, 0, 0)

        # Type
        type_w = QWidget()
        type_w.setStyleSheet("background: transparent;")
        type_l = QVBoxLayout(type_w)
        type_l.setContentsMargins(8, 0, 8, 0)
        type_l.setSpacing(2)
        tl = QLabel(self.t("label_coll_type"))
        tl.setFont(_make_font("Segoe UI", 12))
        tl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        type_l.addWidget(tl)
        e_type = QLineEdit()
        e_type.setText(str(coll.get('type', 0)))
        _style_entry(e_type, h=34, font=_make_font("Consolas", 16, bold=True))
        e_type.setFixedWidth(80)
        type_l.addWidget(e_type)
        self._fields['type'] = e_type
        ig_grid.addWidget(type_w, 0, 0)
        ig_grid.setColumnStretch(0, 0)

        # Name
        name_w = QWidget()
        name_w.setStyleSheet("background: transparent;")
        name_l = QVBoxLayout(name_w)
        name_l.setContentsMargins(8, 0, 8, 0)
        name_l.setSpacing(2)
        nl = QLabel(self.t("label_coll_name"))
        nl.setFont(_make_font("Segoe UI", 12))
        nl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        name_l.addWidget(nl)
        e_name = QLineEdit()
        e_name.setText(coll.get('name', ''))
        _style_entry(e_name, h=34, font=_make_font("Consolas", 16))
        name_l.addWidget(e_name)
        self._fields['name'] = e_name
        ig_grid.addWidget(name_w, 0, 1)
        ig_grid.setColumnStretch(1, 1)

        ip_layout.addWidget(ig)
        self._editor_layout.addWidget(id_panel)

        # Position & Size
        self._add_section(self.t("section_pos_size"))
        pos_panel = QWidget()
        pos_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        pp_layout = QVBoxLayout(pos_panel)
        pp_layout.setContentsMargins(12, 12, 12, 12)

        pg = QWidget()
        pg.setStyleSheet("background: transparent;")
        pg_grid = QGridLayout(pg)
        pg_grid.setContentsMargins(0, 0, 0, 0)

        pos_fields = [
            ('x', self.t("pos_x"), self.t("pos_x_hint")),
            ('y', self.t("pos_y"), self.t("pos_y_hint")),
            ('w', self.t("pos_w"), self.t("pos_w_hint")),
            ('h', self.t("pos_h"), self.t("pos_h_hint")),
        ]
        for i, (key, label, hint) in enumerate(pos_fields):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(8, 0, 8, 0)
            fl.setSpacing(2)
            sl = QLabel(label)
            sl.setFont(_make_font("Segoe UI", 12))
            sl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(sl)
            e = QLineEdit()
            e.setText(str(coll.get(key, 0)))
            _style_entry(e, h=32, font=_make_font("Consolas", 14))
            fl.addWidget(e)
            self._fields[key] = e
            hl = QLabel(hint)
            hl.setFont(_make_font("Segoe UI", 10))
            hl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            fl.addWidget(hl)
            pg_grid.addWidget(fw, 0, i)
            pg_grid.setColumnStretch(i, 1)

        pp_layout.addWidget(pg)
        self._editor_layout.addWidget(pos_panel)

        # Margin / Padding (rto/lbo)
        self._add_section(self.t("section_margins"))
        margin_panel = QWidget()
        margin_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        mgp_layout = QVBoxLayout(margin_panel)
        mgp_layout.setContentsMargins(12, 12, 12, 12)

        mg = QWidget()
        mg.setStyleSheet("background: transparent;")
        mg_grid = QGridLayout(mg)
        mg_grid.setContentsMargins(0, 0, 0, 0)

        margin_fields = [
            (ui_text("ui_info_rtox"), self.t(ui_text("ui_info_margin_rtox")), self.t(ui_text("ui_info_margin_rtox_hint"))),
            (ui_text("ui_info_rtoy"), self.t(ui_text("ui_info_margin_rtoy")), self.t(ui_text("ui_info_margin_rtoy_hint"))),
            (ui_text("ui_info_lbox"), self.t(ui_text("ui_info_margin_lbox")), self.t(ui_text("ui_info_margin_lbox_hint"))),
            (ui_text("ui_info_lboy"), self.t(ui_text("ui_info_margin_lboy")), self.t(ui_text("ui_info_margin_lboy_hint"))),
        ]
        for i, (key, label, hint) in enumerate(margin_fields):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(8, 0, 8, 0)
            fl.setSpacing(2)
            sl = QLabel(label)
            sl.setFont(_make_font("Segoe UI", 12))
            sl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(sl)
            e = QLineEdit()
            e.setText(str(coll.get(key, 0)))
            _style_entry(e, h=32, font=_make_font("Consolas", 14))
            fl.addWidget(e)
            self._fields[key] = e
            hl = QLabel(hint)
            hl.setFont(_make_font("Segoe UI", 10))
            hl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            fl.addWidget(hl)
            mg_grid.addWidget(fw, 0, i)
            mg_grid.setColumnStretch(i, 1)

        mgp_layout.addWidget(mg)
        self._editor_layout.addWidget(margin_panel)

        # Computed info
        self._add_section(self.t("section_computed"))
        comp_panel = QWidget()
        comp_panel.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        cp_layout = QVBoxLayout(comp_panel)
        cp_layout.setContentsMargins(16, 12, 16, 12)

        cg = QWidget()
        cg.setStyleSheet("background: transparent;")
        cg_grid = QGridLayout(cg)
        cg_grid.setContentsMargins(0, 0, 0, 0)

        x, y = coll.get('x', 0), coll.get('y', 0)
        w, h = coll.get('w', 0), coll.get('h', 0)
        rtoX, rtoY = coll.get(ui_text("ui_info_rtox"), 0), coll.get(ui_text("ui_info_rtoy"), 0)
        lboX, lboY = coll.get(ui_text("ui_info_lbox"), 0), coll.get(ui_text("ui_info_lboy"), 0)

        self._computed_labels = {}
        computed = [
            (self.t("computed_center"), "center", f"({x + w // 2}, {y + h // 2})"),
            (self.t("computed_br"), "br", f"({x + w}, {y + h})"),
            (self.t("computed_eff"), "eff", f"({x + lboX}, {y + rtoY}) to ({x + w + rtoX}, {y + h + lboY})"),
        ]
        for i, (label, key, value) in enumerate(computed):
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(8, 0, 8, 0)
            fl.setSpacing(0)
            sl = QLabel(label)
            sl.setFont(_make_font("Segoe UI", 12))
            sl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
            fl.addWidget(sl)
            vl = QLabel(value)
            vl.setFont(_make_font("Consolas", 14, bold=True))
            vl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
            fl.addWidget(vl)
            self._computed_labels[key] = vl
            cg_grid.addWidget(fw, 0, i)
            cg_grid.setColumnStretch(i, 1)

        cp_layout.addWidget(cg)
        self._editor_layout.addWidget(comp_panel)

        # Bottom spacer
        spacer = QWidget()
        spacer.setFixedHeight(20)
        spacer.setStyleSheet("background: transparent;")
        self._editor_layout.addWidget(spacer)

        # Bind position/size fields to update canvas on typing
        for key in ('x', 'y', 'w', 'h'):
            if key in self._fields:
                self._fields[key].textChanged.connect(self._update_vis_from_fields)

    # Add / Duplicate / Delete

    def _add_new_set(self):
        if self._raw_data is None:
            return
        self._apply_fields()
        new_set = {
            'name': ui_text("ui_info_ccnewscene"),
            'collisions': [make_default_collision()],
        }
        self._sets.append(new_set)
        self._info_label.setText(self.t("scenes_count", n=len(self._sets)))
        self._mark_dirty()
        self._populate_set_list()
        self._select_set(new_set)

    def _delete_set(self):
        if self._raw_data is None or not self._current_set:
            return
        if len(self._sets) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("msg_cannot_delete_last_scene"))
            return
        name = self._current_set['name']
        reply = QMessageBox.question(self, self.t("dlg_title_confirm_delete"),
                                     self.t("msg_confirm_delete_scene", name=name),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        self._sets.remove(self._current_set)
        self._current_set = None
        self._current_coll = None
        self._info_label.setText(self.t("scenes_count", n=len(self._sets)))
        self._mark_dirty()
        self._populate_set_list()

    def _add_collision(self):
        if not self._current_set:
            return
        self._apply_fields()
        coll = make_default_collision()

        # Smart defaults: copy name from last collision in set
        if self._current_set['collisions']:
            last = self._current_set['collisions'][-1]
            coll['name'] = last.get('name', ui_text("ui_info_newcollision"))
            # Position below the last one
            coll['x'] = last.get('x', 0)
            coll['y'] = last.get('y', 0) + last.get('h', 50) + 6
            coll['w'] = last.get('w', 100)
            coll['h'] = last.get('h', 50)
            coll[ui_text("ui_info_rtox")] = last.get(ui_text("ui_info_rtox"), 10)
            coll[ui_text("ui_info_rtoy")] = last.get(ui_text("ui_info_rtoy"), -10)
            coll[ui_text("ui_info_lbox")] = last.get(ui_text("ui_info_lbox"), -10)
            coll[ui_text("ui_info_lboy")] = last.get(ui_text("ui_info_lboy"), 10)

        self._current_set['collisions'].append(coll)
        self._coll_header.setText(self.t("collisions_header_count", n=len(self._current_set['collisions'])))
        self._mark_dirty()
        self._populate_coll_list()
        self._select_collision(coll)

    def _duplicate_collision(self):
        if not self._current_set or not self._current_coll:
            return
        self._apply_fields()
        coll = copy.deepcopy(self._current_coll)
        # Offset slightly
        coll['x'] = coll.get('x', 0) + 10
        coll['y'] = coll.get('y', 0) + 10
        self._current_set['collisions'].append(coll)
        self._coll_header.setText(self.t("collisions_header_count", n=len(self._current_set['collisions'])))
        self._mark_dirty()
        self._populate_coll_list()
        self._select_collision(coll)

    def _delete_collision(self):
        if not self._current_set or not self._current_coll:
            return
        colls = self._current_set['collisions']
        if len(colls) <= 0:
            return
        idx = colls.index(self._current_coll) if self._current_coll in colls else -1
        cname = self._current_coll.get('name', '')
        reply = QMessageBox.question(self, self.t("dlg_title_confirm_delete"),
                                     self.t("msg_confirm_delete_coll", idx=idx, name=cname),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._fields = {}
        colls.remove(self._current_coll)
        self._current_coll = None
        self._coll_header.setText(self.t("collisions_header_count", n=len(colls)))
        self._mark_dirty()
        self._populate_coll_list()
        if colls:
            self._select_collision(colls[min(idx, len(colls) - 1)])
        else:
            self._build_set_overview()

    # Helpers

    def _add_section(self, title):
        lbl = QLabel(title)
        lbl.setFont(_make_font("Segoe UI", 15, bold=True))
        lbl.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        lbl.setContentsMargins(20, 10, 0, 2)
        self._editor_layout.addWidget(lbl)
