from core.themes import P


class ToolCardEffectsMixin:
    def _perspective_enabled(self):
        if self._app is None:
            return True
        settings = getattr(self._app, "_settings", {})
        return settings.get("animation_card_perspective", True)

    def _theme_personality_enabled(self):
        if self._app is None:
            return True
        settings = getattr(self._app, "_settings", {})
        return settings.get("animation_theme_personality", True)

    def _theme_personality_motion_enabled(self):
        if self._app is None:
            return True
        settings = getattr(self._app, "_settings", {})
        return settings.get("animation_theme_personality_motion", True)

    def _has_animated_theme_texture(self):
        return (
            self._theme_personality_enabled()
            and self._theme_personality_motion_enabled()
            and P.get("card_texture") in {
                "bubbles", "rain", "star_particles", "aero_glass", "frosted_glass", "nightmare_chaos"
            }
        )

    def _sync_effect_timer(self):
        if self._hovered or (self.isVisible() and self._has_animated_theme_texture()):
            if not self._glow_timer.isActive():
                self._glow_timer.start()
        else:
            self._glow_timer.stop()

    def _advance_hover_glow(self):
        if not self._hovered and not self._has_animated_theme_texture():
            self._glow_timer.stop()
            return
        step = 0.003 if self._has_animated_theme_texture() and not self._hovered else 0.006
        self._hover_phase = (self._hover_phase + step) % 1.0
        self.update()

    def _set_hover_pos(self, pos):
        if self.width() <= 1 or self.height() <= 1:
            return
        self._mouse_pos = pos
        if self._perspective_enabled():
            self._tilt_x = max(-1.0, min(1.0, (pos.x() / self.width()) * 2.0 - 1.0))
            self._tilt_y = max(-1.0, min(1.0, (pos.y() / self.height()) * 2.0 - 1.0))
        else:
            self._tilt_x = 0.0
            self._tilt_y = 0.0
        action = self._action_at(pos)
        self.setToolTip(self._favorite_tooltip if action == "favorite" else self._pin_tooltip if action == "pin" else "")
        self.update()

    def _reset_hover_motion(self):
        self._tilt_x = 0.0
        self._tilt_y = 0.0
        self.setToolTip("")
