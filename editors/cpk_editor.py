"""
CPK Unpacker / Packer widget for the ASBR ToolBox.
Embedded inline in the main window via _show_frame(), same as all other tools.
"""

import os
import subprocess

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QProgressBar,
    QTextEdit, QFileDialog, QMessageBox, QFrame,
    QApplication, QSizePolicy, QMenu,
)
from PyQt6.QtGui import QFont, QColor, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize

from core.themes import P
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    add_editor_card_title, make_editor_card, ss_bg_dark, ss_bg_panel, ss_btn,
    ss_dim_label, ss_main_label, ss_progressbar, ss_sep,
    ss_splitter, ss_textedit, ss_transparent, ss_treewidget,
)


# Worker thread for long operations

class _Worker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, path
    log      = pyqtSignal(str)
    finished = pyqtSignal(bool, str)       # success, message

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self._task   = task
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            self._task(*self._args, **self._kwargs,
                       progress_cb=self._on_progress,
                       log_cb=self._on_log)
            self.finished.emit(True, "")
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _on_progress(self, done, total, path):
        self.progress.emit(done, total, path)

    def _on_log(self, msg):
        self.log.emit(msg)


# Helpers

def _make_btn(text, bg, hover, fg, font, w=0, h=32, icon_name=None):
    btn = QPushButton(text)
    btn.setFont(font)
    btn.setToolTip(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(ss_btn(accent=(bg == P["accent"])))
    if icon_name:
        btn.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
        btn.setIconSize(QSize(13, 13))
    if w:
        btn.setFixedWidth(w)
        btn.setMinimumWidth(w)
    btn.setFixedHeight(h)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return btn


def _label(text, bold=False, size=11, color=None):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", size,
                      QFont.Weight.Bold if bold else QFont.Weight.Normal))
    if color == P["text_dim"]:
        lbl.setStyleSheet(ss_dim_label())
    else:
        lbl.setStyleSheet(ss_main_label())
    return lbl


def _fmt_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# CPK tree widget

class CpkTreeWidget(QTreeWidget):
    """Shows CPK directory tree on the left; files on the right of each dir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels([ui_text("ui_cpk_path"), ui_text("sound_field_size"), ui_text("ui_cpk_compressed")])
        self.setColumnWidth(0, 420)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 90)
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(ss_treewidget())
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setRootIsDecorated(True)
        self.setAnimated(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def populate(self, reader):
        self.clear()
        from parsers.cpk_parser import CpkReader
        dir_items: dict[str, QTreeWidgetItem] = {}

        for entry in reader.entries:
            # Ensure parent dir item exists
            if entry.dir_name not in dir_items:
                parts = entry.dir_name.split("/")
                parent = self.invisibleRootItem()
                built  = ""
                for part in parts:
                    built = (built + "/" + part).lstrip("/")
                    if built not in dir_items:
                        item = QTreeWidgetItem(parent, [part, "", ""])
                        item.setForeground(0, QColor(P["secondary"]))
                        item.setFont(0, QFont("Segoe UI", 10, QFont.Weight.Bold))
                        item.setData(0, Qt.ItemDataRole.UserRole, ("dir", built))
                        dir_items[built] = item
                        parent.addChild(item) if parent is not self.invisibleRootItem() else None
                    parent = dir_items[built]

            dir_item = dir_items[entry.dir_name]
            disp     = _fmt_size(entry.display_size)
            comp_txt = (f"{_fmt_size(entry.file_size)} ({100*entry.file_size//entry.display_size}%)"
                        if entry.is_compressed else "—")
            file_item = QTreeWidgetItem(
                dir_item,
                [entry.file_name, disp, comp_txt]
            )
            file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", entry))
            file_item.setForeground(0, QColor(P["text_main"]))
            file_item.setForeground(1, QColor(P["text_dim"]))
            file_item.setForeground(2, QColor(P["text_dim"]))

        self.expandAll()

    def selected_dir(self) -> str | None:
        """Return the CPK dir name of the selected item (or its parent dir)."""
        items = self.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return None
        kind, val = data
        if kind == "dir":
            return val
        if kind == "file":
            return val.dir_name
        return None

    def selected_entry(self):
        """Return the CpkEntry if a file node is selected."""
        items = self.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            return data[1]
        return None


# Main widget (embedded inline in the main window)

class CpkEditor(QWidget):
    def __init__(self, parent=None, t_func=None):
        super().__init__(parent)
        self.t = t_func or (lambda k, **kw: k)
        self._reader   = None
        self._worker   = None
        self._cpk_path: str | None = None

        self.setStyleSheet(ss_bg_dark() + ss_splitter())

        self._build_ui()

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # button toolbar
        tb = QFrame()
        self._toolbar = tb
        self._toolbar_compact = None
        self._toolbar_narrow = None
        tb.setFixedHeight(52)
        tb.setStyleSheet(ss_bg_panel())
        tb_l = QVBoxLayout(tb)
        tb_l.setContentsMargins(12, 8, 12, 8)
        tb_l.setSpacing(6)
        self._toolbar_l = tb_l

        unpack_l = QHBoxLayout()
        unpack_l.setContentsMargins(0, 0, 0, 0)
        unpack_l.setSpacing(8)
        self._toolbar_top_l = unpack_l

        pack_l = QHBoxLayout()
        pack_l.setContentsMargins(0, 0, 0, 0)
        pack_l.setSpacing(8)
        self._toolbar_bottom_l = pack_l

        self._path_lbl = _label(self.t("cpk_no_file"), size=10, color=P["text_dim"])
        self._path_lbl.setMaximumWidth(400)
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._path_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        font_btn = QFont("Segoe UI", 11)

        self._btn_open = _make_btn(
            self.t("cpk_btn_open"), P["accent"], P["secondary"],
            P["bg_dark"], font_btn, w=150, icon_name="fa6s.folder-open")
        self._btn_open.clicked.connect(self._open_cpk)
        unpack_l.addWidget(self._btn_open)

        self._sep_after_open = self._vsep()
        unpack_l.addWidget(self._sep_after_open)

        self._btn_unpack_all = _make_btn(
            self.t("cpk_btn_unpack_all"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=160, icon_name="fa6s.box-open")
        self._btn_unpack_all.clicked.connect(self._unpack_all)
        self._btn_unpack_all.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_all)

        self._btn_unpack_dir = _make_btn(
            self.t("cpk_btn_unpack_dir"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=226, icon_name="fa6s.folder-tree")
        self._btn_unpack_dir.clicked.connect(self._unpack_selected_dir)
        self._btn_unpack_dir.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_dir)

        self._btn_unpack_file = _make_btn(
            self.t("cpk_btn_unpack_file"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=236, icon_name="fa6s.file-export")
        self._btn_unpack_file.clicked.connect(self._unpack_selected_file)
        self._btn_unpack_file.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_file)

        unpack_l.addStretch()
        tb_l.addLayout(unpack_l)

        self._sep_before_pack = self._vsep()

        self._btn_repack_dir = _make_btn(
            self.t("cpk_btn_repack_dir"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=250, icon_name="fa6s.folder-plus")
        self._btn_repack_dir.clicked.connect(self._replace_dir)
        self._btn_repack_dir.setEnabled(False)
        pack_l.addWidget(self._btn_repack_dir)

        self._btn_replace_file = _make_btn(
            self.t("cpk_btn_replace_file"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=256, icon_name="fa6s.file-import")
        self._btn_replace_file.clicked.connect(self._replace_file)
        self._btn_replace_file.setEnabled(False)
        pack_l.addWidget(self._btn_replace_file)

        self._btn_delete = _make_btn(
            self.t("cpk_btn_delete"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=136, icon_name="fa6s.trash-can")
        self._btn_delete.clicked.connect(self._delete_selected)
        self._btn_delete.setEnabled(False)
        pack_l.addWidget(self._btn_delete)

        self._btn_save_as = _make_btn(
            self.t("cpk_btn_save_as"), P["mid"], P["bg_card_hov"],
            P["secondary"], font_btn, w=200, icon_name="fa6s.floppy-disk")
        self._btn_save_as.clicked.connect(self._save_as)
        self._btn_save_as.setEnabled(False)
        pack_l.addWidget(self._btn_save_as)

        pack_l.addStretch()
        pack_l.addWidget(self._path_lbl)
        tb_l.addLayout(pack_l)
        self._set_toolbar_compact(False)
        root.addWidget(tb)

        # main splitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(ss_splitter())

        # Tree + stats panel
        top_widget = QWidget()
        top_widget.setStyleSheet(ss_bg_dark())
        top_l = QVBoxLayout(top_widget)
        top_l.setContentsMargins(12, 12, 12, 6)
        top_l.setSpacing(8)

        tree_card, tree_l = make_editor_card(top_widget, margins=(14, 12, 14, 14), spacing=8)
        _row, _title, self._tree_subtitle_lbl = add_editor_card_title(
            tree_l,
            self.t("cpk_title"),
            "fa6s.box-archive",
            self.t("cpk_no_file"),
        )
        self._stats_lbl = _label("", size=10, color=P["text_dim"])
        tree_l.addWidget(self._stats_lbl)

        self._tree = CpkTreeWidget()
        tree_l.addWidget(self._tree, 1)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        top_l.addWidget(tree_card, 1)

        splitter.addWidget(top_widget)

        # Log + progress panel
        bot_widget = QWidget()
        bot_widget.setStyleSheet(ss_bg_dark())
        bot_l = QVBoxLayout(bot_widget)
        bot_l.setContentsMargins(12, 6, 12, 12)
        bot_l.setSpacing(8)

        log_card, log_l = make_editor_card(bot_widget, margins=(14, 12, 14, 14), spacing=8)

        log_header_l = QHBoxLayout()
        log_header_l.setContentsMargins(0, 0, 0, 0)
        log_header_l.setSpacing(8)
        title_wrap = QWidget(log_card)
        title_wrap.setStyleSheet(ss_transparent())
        title_l = QVBoxLayout(title_wrap)
        title_l.setContentsMargins(0, 0, 0, 0)
        title_l.setSpacing(0)
        add_editor_card_title(title_l, self.t("cpk_log"), "fa6s.terminal")
        log_header_l.addWidget(title_wrap, 1)
        log_header_l.addStretch()
        self._clear_log_btn = _make_btn(
            self.t("cpk_clear_log"), P["mid"], P["bg_card_hov"],
            P["text_dim"], QFont("Segoe UI", 9), w=86, h=24, icon_name="fa6s.eraser")
        self._clear_log_btn.clicked.connect(self._log_widget.clear
                                            if hasattr(self, "_log_widget")
                                            else lambda: None)
        log_header_l.addWidget(self._clear_log_btn)
        log_l.addLayout(log_header_l)

        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setFont(QFont("Consolas", 9))
        self._log_widget.setMaximumHeight(160)
        self._log_widget.setStyleSheet(ss_textedit())
        log_l.addWidget(self._log_widget)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(10)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setStyleSheet(ss_progressbar())
        log_l.addWidget(self._progress)

        self._status_lbl = _label("", size=9, color=P["text_dim"])
        log_l.addWidget(self._status_lbl)
        bot_l.addWidget(log_card, 1)

        splitter.addWidget(bot_widget)
        splitter.setSizes([460, 200])

        root.addWidget(splitter, 1)

        # Wire clear-log button properly now that _log_widget exists
        self._clear_log_btn.clicked.disconnect()
        self._clear_log_btn.clicked.connect(self._log_widget.clear)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_toolbar"):
            self._set_toolbar_compact(self.width() < self._toolbar_one_row_min_width())
            self._set_toolbar_narrow(self.width() < 900)

    @staticmethod
    def _take_all(layout):
        while layout.count():
            layout.takeAt(0)

    def _set_toolbar_compact(self, compact: bool):
        if self._toolbar_compact == compact:
            return
        self._toolbar_compact = compact

        self._take_all(self._toolbar_top_l)
        self._take_all(self._toolbar_bottom_l)

        if compact:
            self._toolbar.setFixedHeight(88)
            self._toolbar_l.setContentsMargins(12, 6, 12, 6)

            for widget in (
                self._btn_open, self._sep_after_open, self._btn_unpack_all,
                self._btn_unpack_dir, self._btn_unpack_file,
            ):
                self._toolbar_top_l.addWidget(widget)
            self._toolbar_top_l.addStretch()

            for widget in (
                self._btn_repack_dir, self._btn_replace_file,
                self._btn_delete, self._btn_save_as,
            ):
                self._toolbar_bottom_l.addWidget(widget)
            self._toolbar_bottom_l.addStretch()
            self._toolbar_bottom_l.addWidget(self._path_lbl)
            return

        self._toolbar.setFixedHeight(52)
        self._toolbar_l.setContentsMargins(12, 8, 12, 8)

        for widget in (
            self._btn_open, self._sep_after_open, self._btn_unpack_all,
            self._btn_unpack_dir, self._btn_unpack_file, self._sep_before_pack,
            self._btn_repack_dir, self._btn_replace_file, self._btn_delete,
            self._btn_save_as,
        ):
            self._toolbar_top_l.addWidget(widget)
        self._toolbar_top_l.addStretch()
        self._toolbar_top_l.addWidget(self._path_lbl)
        self._set_toolbar_narrow(self.width() < 900)

    def _set_toolbar_narrow(self, narrow: bool):
        if self._toolbar_narrow == narrow:
            return
        self._toolbar_narrow = narrow

        if narrow:
            compact_specs = (
                (self._btn_open, self.t("cpk_btn_open"), 160),
                (self._btn_unpack_all, self.t("cpk_btn_unpack_all"), 158),
                (self._btn_unpack_dir, "", 38),
                (self._btn_unpack_file, "", 38),
                (self._btn_repack_dir, "", 38),
                (self._btn_replace_file, "", 38),
                (self._btn_delete, "", 38),
                (self._btn_save_as, self.t("ui_texture_save_as"), 136),
            )
            self._path_lbl.setMaximumWidth(140)
        else:
            compact_specs = (
                (self._btn_open, self.t("cpk_btn_open"), 160),
                (self._btn_unpack_all, self.t("cpk_btn_unpack_all"), 160),
                (self._btn_unpack_dir, "", 38),
                (self._btn_unpack_file, "", 38),
                (self._btn_repack_dir, "", 38),
                (self._btn_replace_file, "", 38),
                (self._btn_delete, "", 38),
                (self._btn_save_as, self.t("ui_texture_save_as"), 136),
            )
            self._path_lbl.setMaximumWidth(400)

        for btn, text, width in compact_specs:
            btn.setText(text)
            btn.setFixedWidth(width)
            btn.setMinimumWidth(width)

    def _toolbar_one_row_min_width(self):
        widgets = (
            self._btn_open, self._sep_after_open, self._btn_unpack_all,
            self._btn_unpack_dir, self._btn_unpack_file, self._sep_before_pack,
            self._btn_repack_dir, self._btn_replace_file, self._btn_delete,
            self._btn_save_as,
        )
        margins = self._toolbar_l.contentsMargins()
        spacing = self._toolbar_top_l.spacing() * (len(widgets) - 1)
        return (
            margins.left() + margins.right() + spacing
            + sum(max(w.minimumSizeHint().width(), w.sizeHint().width(), w.minimumWidth()) for w in widgets)
        )

    @staticmethod
    def _vsep():
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(ss_sep())
        return sep

    # Logging

    def _log(self, msg: str):
        self._log_widget.append(msg)
        sb = self._log_widget.verticalScrollBar()
        sb.setValue(sb.maximum())

    # File open

    def _open_cpk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("cpk_open_dialog"), game_files_dialog_dir(target_patterns="*.cpk"), "CPK Archives (*.cpk);;All Files (*)")
        if not path:
            return
        create_backup_on_open(path)
        self._load_cpk(path)

    def load_file(self, path: str):
        """Called externally to pre-load a CPK path."""
        self._load_cpk(path)

    def _load_cpk(self, path: str):
        from parsers.cpk_parser import CpkReader
        self._log(self.t("cpk_log_loading", path=path))
        try:
            reader = CpkReader(path)
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            QMessageBox.critical(self, self.t("dlg_title_error"), str(exc))
            return

        self._reader   = reader
        self._cpk_path = path
        self._tree.populate(reader)
        self._path_lbl.setText(os.path.basename(path))
        self._path_lbl.setToolTip(path)
        if getattr(self, "_tree_subtitle_lbl", None) is not None:
            self._tree_subtitle_lbl.setText(os.path.basename(path))
            self._tree_subtitle_lbl.setToolTip(path)

        dirs = reader.directories
        self._stats_lbl.setText(
            self.t("cpk_stats",
                   files=reader.num_files,
                   dirs=len(dirs)))

        self._log(self.t("cpk_log_loaded",
                          files=reader.num_files,
                          dirs=len(dirs)))

        self._btn_unpack_all.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._update_dir_btns()

    def _on_selection_changed(self):
        self._update_dir_btns()

    def _update_dir_btns(self):
        has_dir  = self._tree.selected_dir()   is not None and self._reader is not None
        has_file = self._tree.selected_entry() is not None and self._reader is not None
        self._btn_unpack_dir.setEnabled(has_dir)
        self._btn_unpack_file.setEnabled(has_file)
        self._btn_repack_dir.setEnabled(has_dir)
        self._btn_replace_file.setEnabled(has_file)
        self._btn_delete.setEnabled(has_dir or has_file)

    def _show_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None or self._reader is None:
            return
        self._tree.setCurrentItem(item)
        action = QAction(self.t("cpk_delete_context"), self)
        action.triggered.connect(self._delete_selected)
        menu = QMenu(self._tree)
        menu.addAction(action)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _delete_selected(self):
        if not self._reader or not self._cpk_path:
            return
        entry = self._tree.selected_entry()
        cpk_dir = None if entry else self._tree.selected_dir()
        if entry:
            paths = [entry.path]
            target_kind, target_value = "file", (entry.dir_name, entry.file_name)
            prompt = self.t("cpk_delete_file_confirm", path=entry.path)
        elif cpk_dir is not None:
            prefix = cpk_dir.rstrip("/")
            paths = [
                e.path for e in self._reader.entries
                if e.dir_name == prefix or e.dir_name.startswith(prefix + "/")
            ]
            target_kind, target_value = "dir", cpk_dir
            prompt = self.t("cpk_delete_dir_confirm", path=cpk_dir, count=len(paths))
        else:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.t("cpk_delete_confirm_title"))
        box.setText(prompt)
        box.setInformativeText(self.t("cpk_delete_irreversible"))
        box.setDetailedText("\n".join(paths))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        self._log(self.t(
            "cpk_log_delete",
            count=len(paths),
            target=entry.path if entry else cpk_dir,
        ))
        self._start_worker(
            _task_delete_entries,
            self._cpk_path,
            target_kind,
            target_value,
        )

    # Unpack all

    def _unpack_all(self):
        if not self._reader:
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_out_dir"))
        if not out_dir:
            return

        self._log(self.t("cpk_log_unpack_all", out=out_dir))
        self._start_worker(
            _task_extract_all,
            self._cpk_path,
            out_dir,
        )

    # Unpack selected dir

    def _unpack_selected_dir(self):
        if not self._reader:
            return
        cpk_dir = self._tree.selected_dir()
        if not cpk_dir:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("cpk_no_dir_selected"))
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_out_dir"))
        if not out_dir:
            return

        self._log(self.t("cpk_log_unpack_dir", cpk_dir=cpk_dir, out=out_dir))
        self._start_worker(
            _task_extract_dir,
            self._cpk_path,
            cpk_dir,
            out_dir,
        )

    # Unpack selected file

    def _unpack_selected_file(self):
        if not self._reader:
            return
        entry = self._tree.selected_entry()
        if not entry:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("cpk_no_file_selected"))
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_out_dir"))
        if not out_dir:
            return

        self._log(self.t("cpk_log_unpack_file",
                          file_name=entry.file_name,
                          cpk_dir=entry.dir_name,
                          out=out_dir))
        self._start_worker(
            _task_extract_file,
            self._cpk_path,
            entry.dir_name,
            entry.file_name,
            out_dir,
        )

    # Save as new CPK

    def _save_as(self):
        """Rebuild the current CPK and save to a new file."""
        if not self._reader:
            return
        src_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_src_dir"))
        if not src_dir:
            return

        dest, _ = QFileDialog.getSaveFileName(
            self, self.t("cpk_save_as_dialog"),
            "", "CPK Archives (*.cpk);;All Files (*)")
        if not dest:
            return

        self._log(self.t("cpk_log_repack", src=src_dir, dest=dest))
        self._start_worker(
            _task_repack,
            src_dir,
            dest,
        )

    # Replace single file inside CPK

    def _replace_file(self):
        if not self._reader or not self._cpk_path:
            return
        entry = self._tree.selected_entry()
        if not entry:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("cpk_no_file_selected"))
            return

        src_file, _ = QFileDialog.getOpenFileName(
            self,
            self.t("cpk_choose_src_file_replace", file_name=entry.file_name),
            game_files_dialog_dir(target_patterns=os.path.basename(entry.file_name)), ui_text("ui_cpk_all_files"))
        if not src_file:
            return

        answer = QMessageBox.question(
            self,
            self.t("cpk_repack_confirm_title"),
            self.t("cpk_repack_confirm_msg", path=self._cpk_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._log(self.t("cpk_log_replace_file",
                          file_name=entry.file_name,
                          cpk_dir=entry.dir_name,
                          src=src_file))
        self._start_worker(
            _task_replace_file,
            self._cpk_path,
            entry.dir_name,
            entry.file_name,
            src_file,
        )

    # Replace single dir inside CPK

    def _replace_dir(self):
        """Replace one CPK directory from a local folder, rebuild CPK."""
        if not self._reader or not self._cpk_path:
            return
        cpk_dir = self._tree.selected_dir()
        if not cpk_dir:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("cpk_no_dir_selected"))
            return

        src_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_src_dir_replace", cpk_dir=cpk_dir))
        if not src_dir:
            return

        answer = QMessageBox.question(
            self,
            self.t("cpk_repack_confirm_title"),
            self.t("cpk_repack_confirm_msg", path=self._cpk_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._log(self.t("cpk_log_replace_dir",
                          cpk_dir=cpk_dir, src=src_dir))
        self._start_worker(
            _task_replace_dir,
            self._cpk_path,
            cpk_dir,
            src_dir,
        )

    # Worker management

    def _set_buttons_enabled(self, enabled: bool):
        for btn in (self._btn_open, self._btn_unpack_all, self._btn_unpack_dir,
                    self._btn_unpack_file, self._btn_repack_dir,
                    self._btn_replace_file, self._btn_delete,
                    self._btn_save_as):
            btn.setEnabled(enabled and (
                btn is self._btn_open or self._reader is not None))
        if enabled:
            self._update_dir_btns()

    def _start_worker(self, task, *args):
        if self._worker and self._worker.isRunning():
            return

        self._progress.setValue(0)
        self._status_lbl.setText(self.t("cpk_working"))
        self._set_buttons_enabled(False)

        self._worker = _Worker(task, *args)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done, total, path):
        if total > 0:
            pct = int(done * 100 / total)
            self._progress.setValue(pct)
        self._status_lbl.setText(
            self.t("cpk_progress", done=done, total=total,
                   name=os.path.basename(path)))
        QApplication.processEvents()

    def _on_finished(self, success, message):
        self._progress.setValue(100 if success else 0)
        self._set_buttons_enabled(True)
        if success:
            self._status_lbl.setText(self.t("cpk_done"))
            self._log(self.t("cpk_log_done"))
            # Reload tree if CPK was modified
            if self._cpk_path:
                QTimer.singleShot(200, lambda: self._load_cpk(self._cpk_path))
        else:
            self._status_lbl.setText(self.t("cpk_failed"))
            self._log(f"[ERROR] {message}")
            QMessageBox.critical(self, self.t("dlg_title_error"), message)


# Worker task functions (run in QThread)

def _task_extract_all(cpk_path: str, out_dir: str,
                      progress_cb=None, log_cb=None):
    from core.external_tools import find_cpkforge, tool_command

    helper = find_cpkforge()
    if helper:
        if log_cb:
            log_cb(f"Fast unpack via CPKForge: {cpk_path}")
        if progress_cb:
            progress_cb(0, 0, os.path.basename(cpk_path))
        result = subprocess.run(
            [*tool_command(helper), "unpack", cpk_path, out_dir],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            details = (result.stderr or result.stdout or "").strip()
            if log_cb:
                suffix = f": {details}" if details else ""
                log_cb(
                    f"[WARN] CPKForge failed with exit code "
                    f"{result.returncode}{suffix}")
                log_cb("Falling back to the Python CPK extractor.")
        else:
            if log_cb:
                log_cb(f"Fast unpack completed: {out_dir}")
            return

    from parsers.cpk_parser import CpkReader
    reader = CpkReader(cpk_path)
    total  = reader.num_files
    if log_cb:
        log_cb(f"Extracting {total} files to: {out_dir}")

    warn_count = 0
    for i, entry in enumerate(reader.entries):
        dest, decomp_ok = reader.extract_entry(entry, out_dir, decompress=True)
        status = "" if decomp_ok else ui_text("ui_cpk_raw_decompression_not_supported")
        if not decomp_ok:
            warn_count += 1
        if log_cb:
            log_cb(f"  [{i+1}/{total}] {entry.path}{status}")
        if progress_cb:
            progress_cb(i + 1, total, dest)

    if warn_count and log_cb:
        log_cb(f"[WARN] {warn_count} file(s) written as raw compressed bytes "
               f"(CRILAYLA variant not supported — use a dedicated CPK tool to decompress).")


def _task_extract_dir(cpk_path: str, cpk_dir: str, out_dir: str,
                      progress_cb=None, log_cb=None):
    from parsers.cpk_parser import CpkReader
    reader  = CpkReader(cpk_path)
    entries = reader.entries_for_dir(cpk_dir)
    total   = len(entries)
    if log_cb:
        log_cb(f"Extracting {total} files from '{cpk_dir}' to: {out_dir}")

    warn_count = 0
    for i, entry in enumerate(entries):
        dest, decomp_ok = reader.extract_entry(entry, out_dir, decompress=True)
        status = "" if decomp_ok else ui_text("ui_cpk_raw")
        if not decomp_ok:
            warn_count += 1
        if log_cb:
            log_cb(f"  [{i+1}/{total}] {entry.file_name}{status}")
        if progress_cb:
            progress_cb(i + 1, total, dest)

    if warn_count and log_cb:
        log_cb(f"[WARN] {warn_count} file(s) written as raw compressed bytes "
               f"(CRILAYLA variant not supported).")


def _task_repack(src_dir: str, dest_cpk: str,
                 progress_cb=None, log_cb=None):
    from parsers.cpk_parser import collect_files_from_dir, build_cpk

    if log_cb:
        log_cb(f"Collecting files from: {src_dir}")
    entries = collect_files_from_dir(src_dir)
    total   = len(entries)
    if log_cb:
        log_cb(f"Building CPK with {total} files...")

    if progress_cb:
        progress_cb(0, total, "")

    cpk_data = build_cpk(entries)

    if log_cb:
        log_cb(f"Writing CPK ({len(cpk_data)/1024/1024:.2f} MB) to: {dest_cpk}")

    with open(dest_cpk, "wb") as f:
        f.write(cpk_data)

    if progress_cb:
        progress_cb(total, total, dest_cpk)
    if log_cb:
        log_cb(ui_text("cpk_done"))


def _task_extract_file(cpk_path: str, cpk_dir: str, file_name: str, out_dir: str,
                       progress_cb=None, log_cb=None):
    from parsers.cpk_parser import CpkReader
    reader = CpkReader(cpk_path)
    entry = next(
        (e for e in reader.entries
         if e.dir_name == cpk_dir and e.file_name == file_name),
        None)
    if entry is None:
        raise ValueError(f"File not found in CPK: {cpk_dir}/{file_name}")

    if log_cb:
        log_cb(f"Extracting: {entry.path}")
    dest, decomp_ok = reader.extract_entry(entry, out_dir, decompress=True)
    status = "" if decomp_ok else ui_text("ui_cpk_raw")
    if log_cb:
        log_cb(f"  → {dest}{status}")
    if progress_cb:
        progress_cb(1, 1, dest)


def _task_replace_file(cpk_path: str, cpk_dir: str, file_name: str, src_file: str,
                       progress_cb=None, log_cb=None):
    from parsers.cpk_parser import (CpkReader, replace_file_in_entries, build_cpk)

    if log_cb:
        log_cb(f"Reading existing CPK: {cpk_path}")
    reader = CpkReader(cpk_path)

    if log_cb:
        log_cb(f"Replacing '{cpk_dir}/{file_name}' with: {src_file}")
    entries = replace_file_in_entries(
        reader.entries, cpk_path, cpk_dir, file_name, src_file)

    total = len(entries)
    if log_cb:
        log_cb(f"Building new CPK with {total} files...")
    if progress_cb:
        progress_cb(0, total, "")

    cpk_data = build_cpk(entries)

    if log_cb:
        log_cb(f"Writing CPK ({len(cpk_data)/1024/1024:.2f} MB) to: {cpk_path}")
    with open(cpk_path, "wb") as f:
        f.write(cpk_data)

    if progress_cb:
        progress_cb(total, total, cpk_path)
    if log_cb:
        log_cb(ui_text("cpk_done"))


def _task_replace_dir(cpk_path: str, cpk_dir: str, src_dir: str,
                      progress_cb=None, log_cb=None):
    from parsers.cpk_parser import (CpkReader, replace_dir_in_entries,
                                     build_cpk)

    if log_cb:
        log_cb(f"Reading existing CPK: {cpk_path}")
    reader  = CpkReader(cpk_path)

    if log_cb:
        log_cb(f"Replacing '{cpk_dir}' with files from: {src_dir}")
    entries = replace_dir_in_entries(
        reader.entries, cpk_path, src_dir, cpk_dir)

    total = len(entries)
    if log_cb:
        log_cb(f"Building new CPK with {total} files...")
    if progress_cb:
        progress_cb(0, total, "")

    cpk_data = build_cpk(entries)

    if log_cb:
        log_cb(f"Writing CPK ({len(cpk_data)/1024/1024:.2f} MB) to: {cpk_path}")
    with open(cpk_path, "wb") as f:
        f.write(cpk_data)

    if progress_cb:
        progress_cb(total, total, cpk_path)
    if log_cb:
        log_cb(ui_text("cpk_done"))


def _task_delete_entries(cpk_path: str, target_kind: str, target_value,
                         progress_cb=None, log_cb=None):
    """Rebuild a CPK without one file or directory, then replace it atomically."""
    from parsers.cpk_parser import delete_entries_from_cpk

    removed = delete_entries_from_cpk(
        cpk_path,
        target_kind,
        target_value,
        progress_cb=progress_cb,
    )

    if log_cb:
        log_cb(ui_text("cpk_delete_done", count=removed))
