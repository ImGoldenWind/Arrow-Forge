from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.file_drop import install_file_drop
from core.themes import P
from core.utils.ui_helpers import _make_styled_btn
from editors.cpk_editor import CpkEditor


class CpkPanelMixin:
    def _open_cpk_editor(self):
        if self._loading:
            return
        if not self._confirm_close_embedded_editor():
            return

        if self._settings_win:
            self._settings_win.deleteLater()
            self._settings_win = None
        self._delete_tool_frame()

        self._hide_char_panel()

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._cpk_editor_win = panel

        # Top bar — same pattern as Settings / Credits / tool editors
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P.get('toolbar_bg', P['bg_panel'])};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_cpk_editor_inline)
        bar_layout.addWidget(back_btn)

        title_lbl = QLabel(self.t("cpk_title"))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(title_lbl)
        bar_layout.addStretch()

        panel_layout.addWidget(bar)

        # Embed the CPK editor widget
        editor = CpkEditor(panel, t_func=self.t)
        install_file_drop(editor)
        panel_layout.addWidget(editor, 1)

        self._show_frame(panel)

    def _close_cpk_editor_inline(self):
        if self._cpk_editor_win:
            self._cpk_editor_win.deleteLater()
            self._cpk_editor_win = None
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)
