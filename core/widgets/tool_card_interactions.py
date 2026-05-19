from PyQt6.QtCore import QRectF, Qt


class ToolCardInteractionMixin:
    def _position_action_btns(self):
        self._favorite_rect = QRectF(self.width() - 37, 11, 26, 26)
        self._pin_rect = QRectF(self.width() - 68, 11, 26, 26)

    def resizeEvent(self, event):
        self._position_action_btns()
        super().resizeEvent(event)

    def _action_at(self, point):
        mapped = self._map_from_visual_card(point)
        if self._favorite_rect.contains(mapped):
            return "favorite"
        if self._pin_rect.contains(mapped):
            return "pin"
        return None

    def _toggle_favorite(self, checked):
        self._favorite = checked
        self.update()
        if self._on_toggle_favorite:
            self._on_toggle_favorite(self._tool_id)

    def _toggle_pin(self, checked):
        self._pinned = checked
        self.update()
        if self._on_toggle_pin:
            self._on_toggle_pin(self._tool_id, self._pin_category_key)

    def enterEvent(self, event):
        self._hovered = True
        self._set_hover_pos(event.position().toPoint())
        self._sync_effect_timer()
        if self._on_hover_cb:
            self._on_hover_cb(self._dlg_key, self._category_key)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._reset_hover_motion()
        self._sync_effect_timer()
        self.update()
        if self._on_leave_cb:
            self._on_leave_cb()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_effect_timer()

    def hideEvent(self, event):
        self._glow_timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_action = self._action_at(event.position().toPoint())
            self._pressed_inside = self._press_action is None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            action = self._action_at(event.position().toPoint())
            if self._press_action and action == self._press_action:
                if action == "favorite":
                    self._toggle_favorite(not self._favorite)
                elif action == "pin":
                    self._toggle_pin(not self._pinned)
                self._press_action = None
                self._pressed_inside = False
                event.accept()
                return

            if self._pressed_inside:
                self._pressed_inside = False
                if self.rect().contains(event.position().toPoint()):
                    if self._on_activate:
                        self._on_activate()
                    elif self._app:
                        self._app._open_tool_inline(self._label, self._file_hint, self._tool_id)
            self._press_action = None
            event.accept()
            return
        self._pressed_inside = False
        self._press_action = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._hovered:
            self._set_hover_pos(event.position().toPoint())
        if self._pressed_inside and not self.rect().contains(event.position().toPoint()):
            self._pressed_inside = False
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and (self._on_activate or self._app):
            self._pressed_inside = False
            if self._on_activate:
                self._on_activate()
            else:
                self._app._open_tool_inline(self._label, self._file_hint, self._tool_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
