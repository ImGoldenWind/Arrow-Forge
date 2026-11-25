"""
CPK Unpacker / Packer widget for the ASBR ToolBox.
Embedded inline in the main window via _show_frame(), same as all other tools.
"""

from core.design_tokens import (
    LayoutRole,
    Size,
    TypeSize,
    mono_font,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    ss_bg_dark,
    ss_dialog,
    ss_dim_label,
    ss_main_label,
    ss_progressbar,
    ss_splitter,
    ss_transparent,
    ss_treewidget,
)
from core.ui.editor_widgets import (
    EditorSeparator,
    EditorToolbar,
    configure_button,
    configure_file_label,
    configure_layout,
    configure_textedit,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import install_file_actions
import os
import re
import subprocess

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QProgressBar,
    QTextEdit, QFileDialog, QMessageBox, QFrame,
    QSizePolicy, QMenu, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
)
from PyQt6.QtGui import QFont, QColor, QAction
from PyQt6.QtCore import QCoreApplication, Qt, QThread, pyqtSignal, QSize

from core.themes import P
from core.translations import ui_text
from core.settings import create_backup_on_open, game_files_dialog_dir
from parsers.cpk_parser import CpkReader


# Worker thread for long operations

class _Worker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, path
    log      = pyqtSignal(str)

    def __init__(self, task, *args, reload_archive=False):
        app = QCoreApplication.instance()
        super().__init__(app)
        self._task   = task
        self._args   = args
        self.reload_archive = reload_archive
        self.error = None
        app.aboutToQuit.connect(self.wait)
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            self._task(*self._args,
                       progress_cb=self._on_progress,
                       log_cb=self._on_log)
        except Exception as exc:
            self.error = str(exc)

    def _on_progress(self, done, total, path):
        self.progress.emit(done, total, path)

    def _on_log(self, msg):
        self.log.emit(msg)


# Helpers

def _make_btn(text, *, accent=False, danger=False, width=0, height=Size.CONTROL, icon_name=None):
    btn = QPushButton(text)
    btn.setToolTip(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    configure_button(btn, accent=accent, danger=danger, height=height)
    if icon_name:
        btn.setIcon(qta.icon(icon_name, color=P.get("button_text", P["text_main"])))
        btn.setIconSize(QSize(13, 13))
    if width:
        btn.setFixedWidth(width)
        btn.setMinimumWidth(width)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return btn


def _label(text, bold=False, size=11, color=None):
    lbl = QLabel(text)
    lbl.setFont(ui_font(size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
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


def _archive_priority(path: str) -> tuple[int, int]:
    name = os.path.splitext(os.path.basename(path))[0].casefold()
    if name == "data":
        return 0, 0
    patch = re.fullmatch(r"patch[ ._-]*([0-9]+)", name)
    if patch:
        return 1, int(patch[1])
    return 2, 0


def _choose_cpk_paths(parent, title, directory):
    paths, _ = QFileDialog.getOpenFileNames(
        parent, title, directory, "CPK Archives (*.cpk);;All Files (*)")
    return paths


def _entry_path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.replace("\\", "/")))


def _merged_entries(readers):
    by_path = {}
    for reader in readers:
        for entry in reader.entries:
            by_path[_entry_path_key(entry.path)] = (entry, reader)
    return dict(by_path.values())


class _ArchiveOrderDialog(QDialog):
    def __init__(self, parent, paths, t):
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(t("cpk_order_title"))
        self.setStyleSheet(ss_dialog())
        layout = QVBoxLayout(self)
        configure_layout(layout, LayoutRole.PAGE)

        hint = _label(t("cpk_order_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._archives = QListWidget(self)
        for row, path in enumerate(paths):
            self._insert(row, path)
        layout.addWidget(self._archives)

        controls = QHBoxLayout()
        configure_layout(controls, LayoutRole.FIELD)
        self._add = _make_btn(t("cpk_order_add"), icon_name="fa6s.folder-plus")
        self._up = _make_btn(t("cpk_order_up"), icon_name="fa6s.arrow-up")
        self._down = _make_btn(t("cpk_order_down"), icon_name="fa6s.arrow-down")
        self._add.clicked.connect(self._add_archives)
        self._up.clicked.connect(lambda: self._move(-1))
        self._down.clicked.connect(lambda: self._move(1))
        controls.addWidget(self._add)
        controls.addWidget(self._up)
        controls.addWidget(self._down)
        controls.addStretch()
        layout.addLayout(controls)

        buttons = QDialogButtonBox(self)
        open_button = buttons.addButton(t("cpk_order_open"), QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(t("qol_cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        configure_button(open_button, accent=True)
        configure_button(cancel_button)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._archives.currentRowChanged.connect(self._update_buttons)
        self._archives.setCurrentRow(0)

    def _insert(self, row, path):
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self._archives.insertItem(row, item)

    def _add_archives(self):
        directory = os.path.dirname(self.paths()[self._archives.currentRow()])
        paths = _choose_cpk_paths(self, self.t("cpk_open_dialog"), directory)
        existing = self.paths()
        known = {os.path.normcase(os.path.realpath(path)) for path in existing}
        for path in sorted(paths, key=_archive_priority):
            key = os.path.normcase(os.path.realpath(path))
            if key in known:
                continue
            priority = _archive_priority(path)
            row = next((i for i, current in enumerate(existing)
                        if _archive_priority(current) > priority), len(existing))
            self._insert(row, path)
            existing.insert(row, path)
            known.add(key)
        self._update_buttons(self._archives.currentRow())

    def _update_buttons(self, row):
        self._up.setEnabled(row > 0)
        self._down.setEnabled(0 <= row < self._archives.count() - 1)

    def _move(self, offset):
        row = self._archives.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self._archives.count():
            self._archives.insertItem(target, self._archives.takeItem(row))
            self._archives.setCurrentRow(target)

    def paths(self):
        return [
            self._archives.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._archives.count())
        ]


# CPK tree widget

class CpkTreeWidget(QTreeWidget):
    """Shows CPK directory tree on the left; files on the right of each dir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels([ui_text("ui_cpk_path"), ui_text("sound_field_size"), ui_text("ui_cpk_compressed")])
        self.setColumnWidth(0, 420)
        self.setColumnWidth(1, 90)
        self.setColumnWidth(2, 90)
        self.setFont(mono_font(TypeSize.BODY))
        self.setStyleSheet(ss_treewidget())
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setRootIsDecorated(True)
        self.setAnimated(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def populate(self, entries, *, sources=None):
        self.clear()
        dir_items: dict[str, QTreeWidgetItem] = {}
        root = self.invisibleRootItem()

        for entry in entries:
            parent = root
            built = ""
            dir_name = entry.dir_name.replace("\\", "/") if sources is not None else entry.dir_name
            for part in filter(None, dir_name.split("/")):
                built = f"{built}/{part}" if built else part
                key = _entry_path_key(built) if sources is not None else built
                if key not in dir_items:
                    item = QTreeWidgetItem(parent, [part, "", ""])
                    item.setForeground(0, QColor(P["secondary"]))
                    item.setFont(0, ui_font(TypeSize.BODY, QFont.Weight.Bold))
                    item.setData(0, Qt.ItemDataRole.UserRole, ("dir", built))
                    dir_items[key] = item
                parent = dir_items[key]

            disp     = _fmt_size(entry.display_size)
            comp_txt = (f"{_fmt_size(entry.file_size)} ({100*entry.file_size//entry.display_size}%)"
                        if entry.is_compressed else "—")
            file_item = QTreeWidgetItem(
                parent,
                [entry.file_name, disp, comp_txt]
            )
            file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", entry))
            if sources is not None:
                file_item.setToolTip(0, sources[entry].path)
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
        self.t = t_func or ui_text
        self._reader = None
        self._worker = None
        self._archives = ()
        self._sources = {}

        self.setStyleSheet(ss_bg_dark() + ss_splitter())

        self._build_ui()
        install_file_actions(self, self._btn_save_as, existing_button=self._btn_save_as)
        install_editor_chrome(self)

    # UI construction

    def _build_ui(self):
        root = QVBoxLayout(self)
        configure_layout(root, LayoutRole.ROOT)

        # button toolbar
        tb = EditorToolbar(stacked=True)
        self._toolbar = tb
        self._toolbar_compact = None
        self._toolbar_narrow = None
        tb_l = tb.content_layout
        self._toolbar_l = tb_l

        unpack_l = QHBoxLayout()
        configure_layout(unpack_l, LayoutRole.FIELD)
        self._toolbar_top_l = unpack_l

        pack_l = QHBoxLayout()
        configure_layout(pack_l, LayoutRole.FIELD)
        self._toolbar_bottom_l = pack_l

        self._path_lbl = configure_file_label(QLabel(self.t("cpk_no_file")))
        self._path_lbl.setMaximumWidth(400)
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._path_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)


        self._btn_open = _make_btn(self.t('cpk_btn_open'), accent=True, width=150, icon_name='fa6s.folder-open')
        self._btn_open.clicked.connect(self._open_cpk)
        self._btn_open.setProperty("designAction", 'open')
        unpack_l.addWidget(self._btn_open)

        self._sep_after_open = self._vsep()
        unpack_l.addWidget(self._sep_after_open)

        self._btn_unpack_all = _make_btn(self.t('cpk_btn_unpack_all'), width=160, icon_name='fa6s.box-open')
        self._btn_unpack_all.clicked.connect(self._unpack_all)
        self._btn_unpack_all.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_all)

        self._btn_unpack_dir = _make_btn(self.t('cpk_btn_unpack_dir'), width=226, icon_name='fa6s.folder-tree')
        self._btn_unpack_dir.clicked.connect(self._unpack_selected_dir)
        self._btn_unpack_dir.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_dir)

        self._btn_unpack_file = _make_btn(self.t('cpk_btn_unpack_file'), width=236, icon_name='fa6s.file-export')
        self._btn_unpack_file.clicked.connect(self._unpack_selected_file)
        self._btn_unpack_file.setEnabled(False)
        unpack_l.addWidget(self._btn_unpack_file)

        unpack_l.addStretch()
        tb_l.addLayout(unpack_l)

        self._sep_before_pack = self._vsep()

        self._btn_repack_dir = _make_btn(self.t('cpk_btn_repack_dir'), width=250, icon_name='fa6s.folder-plus')
        self._btn_repack_dir.clicked.connect(self._replace_dir)
        self._btn_repack_dir.setEnabled(False)
        pack_l.addWidget(self._btn_repack_dir)

        self._btn_replace_file = _make_btn(self.t('cpk_btn_replace_file'), width=256, icon_name='fa6s.file-import')
        self._btn_replace_file.clicked.connect(self._replace_file)
        self._btn_replace_file.setEnabled(False)
        pack_l.addWidget(self._btn_replace_file)

        self._btn_delete = _make_btn(self.t('cpk_btn_delete'), danger=True, width=136, icon_name='fa6s.trash-can')
        self._btn_delete.clicked.connect(self._delete_selected)
        self._btn_delete.setProperty("designAction", 'delete')
        self._btn_delete.setEnabled(False)
        pack_l.addWidget(self._btn_delete)

        self._btn_save_as = _make_btn(self.t('cpk_btn_save_as'), width=200, icon_name='fa6s.floppy-disk')
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
        top_l.setSpacing(Size.GAP)

        tree_card, tree_l = make_editor_card(top_widget)
        row, _title, self._tree_subtitle_lbl = add_editor_card_title(
            tree_l,
            self.t("cpk_title"),
            "fa6s.box-archive",
            self.t("cpk_no_file"),
        )
        self._btn_archive_order = _make_btn(
            self.t("cpk_order_manage"), icon_name="fa6s.layer-group")
        self._btn_archive_order.clicked.connect(self._edit_archive_order)
        self._btn_archive_order.hide()
        row.layout().addWidget(self._btn_archive_order)

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
        bot_l.setSpacing(Size.GAP)

        log_card, log_l = make_editor_card(bot_widget)

        log_header_l = QHBoxLayout()
        configure_layout(log_header_l, LayoutRole.TITLE)
        title_wrap = QWidget(log_card)
        title_wrap.setStyleSheet(ss_transparent())
        title_l = QVBoxLayout(title_wrap)
        configure_layout(title_l, LayoutRole.ROOT)
        add_editor_card_title(title_l, self.t("cpk_log"), "fa6s.terminal")
        log_header_l.addWidget(title_wrap, 1)
        log_header_l.addStretch()
        self._clear_log_btn = _make_btn(self.t('cpk_clear_log'), width=86, height=Size.COMPACT_CONTROL, icon_name='fa6s.eraser')
        self._clear_log_btn.clicked.connect(self._log_widget.clear
                                            if hasattr(self, "_log_widget")
                                            else lambda: None)
        log_header_l.addWidget(self._clear_log_btn)
        log_l.addLayout(log_header_l)

        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setMaximumHeight(160)
        configure_textedit(self._log_widget, monospace=True)
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
            self._toolbar.set_rows(2)

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

        self._toolbar.set_rows(1)

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
                (self._btn_save_as, self.t("btn_save_as"), 136),
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
                (self._btn_save_as, self.t("btn_save_as"), 136),
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
        sep = EditorSeparator(orientation=Qt.Orientation.Vertical)
        sep.setFrameShape(QFrame.Shape.VLine)


        return sep

    # Logging

    def _log(self, msg: str):
        self._log_widget.append(msg)
        sb = self._log_widget.verticalScrollBar()
        sb.setValue(sb.maximum())

    # File open

    def _open_cpk(self):
        paths = _choose_cpk_paths(
            self, self.t("cpk_open_dialog"), game_files_dialog_dir(target_patterns="*.cpk"),
        )
        if not paths:
            return
        if len(paths) == 1:
            create_backup_on_open(paths[0])
            self._load_cpks(paths)
        else:
            self._confirm_archive_order(sorted(paths, key=_archive_priority))

    def _edit_archive_order(self):
        self._confirm_archive_order([reader.path for reader in self._archives])

    def _confirm_archive_order(self, paths):
        dialog = _ArchiveOrderDialog(self, paths, self.t)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_cpks(dialog.paths())
        dialog.deleteLater()

    def load_file(self, path: str):
        """Called externally to pre-load a CPK path."""
        self._load_cpks([path])

    def _load_cpks(self, paths):
        if self._worker is not None:
            return

        readers = []
        try:
            for path in paths:
                self._log(self.t("cpk_log_loading", path=path))
                readers.append(CpkReader(path))
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            QMessageBox.critical(self, self.t("dlg_title_error"), f"{path}\n{exc}")
            return

        self._archives = tuple(readers)
        self._reader = readers[0] if len(readers) == 1 else None
        self._sources = _merged_entries(readers) if self._reader is None else {}

        if self._reader is not None:
            entries = self._reader.entries
            self._tree.populate(entries)
            title = os.path.basename(self._reader.path)
            dirs = self._reader.directories
        else:
            entries = self._sources
            self._tree.populate(entries, sources=self._sources)
            title = self.t("cpk_archive_count", count=len(readers))
            dirs = {_entry_path_key(entry.dir_name) for entry in entries if entry.dir_name}

        tooltip = "\n".join(reader.path for reader in readers)
        for label in (self._path_lbl, self._tree_subtitle_lbl):
            label.setText(title)
            label.setToolTip(tooltip)
        self._log(self.t("cpk_log_loaded",
                          files=len(entries),
                          dirs=len(dirs)))
        self._update_buttons()

    def _on_selection_changed(self):
        self._update_buttons()

    def _update_buttons(self):
        idle = self._worker is None
        loaded = idle and bool(self._archives)
        editable = loaded and self._reader is not None
        selected_dir = self._tree.selected_dir()
        has_dir = loaded and bool(selected_dir)
        has_file = loaded and self._tree.selected_entry() is not None
        self._btn_open.setEnabled(idle)
        self._btn_archive_order.setVisible(bool(self._archives))
        self._btn_archive_order.setEnabled(loaded)
        self._btn_unpack_all.setEnabled(loaded)
        self._btn_unpack_dir.setEnabled(has_dir)
        self._btn_unpack_file.setEnabled(has_file)
        self._btn_repack_dir.setEnabled(editable and has_dir)
        self._btn_replace_file.setEnabled(editable and has_file)
        self._btn_delete.setEnabled(editable and selected_dir is not None)
        self._btn_save_as.setEnabled(loaded)

    def _show_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None or self._reader is None or self._worker is not None:
            return
        self._tree.setCurrentItem(item)
        action = QAction(self.t("cpk_delete_context"), self)
        action.triggered.connect(self._delete_selected)
        menu = QMenu(self._tree)
        menu.addAction(action)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _delete_selected(self):
        if self._reader is None or self._worker is not None:
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
            self._reader.path,
            target_kind,
            target_value,
            reload_archive=True,
        )

    # Unpack all

    def _unpack_all(self):
        if not self._archives:
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, self.t("cpk_choose_out_dir"))
        if not out_dir:
            return

        self._log(self.t("cpk_log_unpack_all", out=out_dir))
        if self._reader is None:
            self._start_worker(_task_extract_archives, self._archives, out_dir)
        else:
            self._start_worker(_task_extract_all, self._reader, out_dir)

    # Unpack selected dir

    def _unpack_selected_dir(self):
        if not self._archives:
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
        if self._reader is None:
            directory = _entry_path_key(cpk_dir)
            sources = {
                entry: reader for entry, reader in self._sources.items()
                if _entry_path_key(entry.dir_name) == directory
                or _entry_path_key(entry.dir_name).startswith(directory + os.sep)
            }
            self._start_worker(_task_extract_entries, sources, out_dir)
        else:
            self._start_worker(_task_extract_dir, self._reader.path, cpk_dir, out_dir)

    # Unpack selected file

    def _unpack_selected_file(self):
        if not self._archives:
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
        if self._reader is None:
            self._start_worker(_task_extract_entries, {entry: self._sources[entry]}, out_dir)
        else:
            self._start_worker(
                _task_extract_file, self._reader.path, entry.dir_name, entry.file_name, out_dir)

    # Save as new CPK

    def _save_as(self):
        """Build a new CPK from a local directory."""
        if not self._archives:
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
        if self._reader is None or self._worker is not None:
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
            self.t("cpk_repack_confirm_msg", path=self._reader.path),
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
            self._reader.path,
            entry.dir_name,
            entry.file_name,
            src_file,
            reload_archive=True,
        )

    # Replace single dir inside CPK

    def _replace_dir(self):
        """Replace one CPK directory from a local folder, rebuild CPK."""
        if self._reader is None or self._worker is not None:
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
            self.t("cpk_repack_confirm_msg", path=self._reader.path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._log(self.t("cpk_log_replace_dir",
                          cpk_dir=cpk_dir, src=src_dir))
        self._start_worker(
            _task_replace_dir,
            self._reader.path,
            cpk_dir,
            src_dir,
            reload_archive=True,
        )

    # Worker management

    def _start_worker(self, task, *args, reload_archive=False):
        if self._worker is not None:
            return

        self._progress.setValue(0)
        self._status_lbl.setText(self.t("cpk_working"))
        self._worker = _Worker(task, *args, reload_archive=reload_archive)
        self._update_buttons()
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

    def _on_finished(self):
        worker = self._worker
        self._worker = None
        message = worker.error
        success = message is None
        self._progress.setValue(100 if success else 0)
        self._update_buttons()
        if success:
            self._status_lbl.setText(self.t("cpk_done"))
            self._log(self.t("cpk_log_done"))
            if worker.reload_archive:
                self.load_file(self._reader.path)
        else:
            self._status_lbl.setText(self.t("cpk_failed"))
            self._log(f"[ERROR] {message}")
            QMessageBox.critical(self, self.t("dlg_title_error"), message)


# Worker task functions (run in QThread)

def _task_extract_archives(readers, out_dir: str, progress_cb=None, log_cb=None):
    archive_paths = {os.path.normcase(os.path.realpath(reader.path)) for reader in readers}
    for reader in readers:
        for entry in reader.entries:
            dest = os.path.normcase(os.path.realpath(reader.extraction_path(entry, out_dir)))
            if dest in archive_paths:
                raise ValueError(ui_text("cpk_error_output_is_source", path=dest))

    total = sum(reader.num_files for reader in readers)
    done = 0

    def report(count, _archive_total, path):
        progress_cb(done + count, total, path)

    for reader in readers:
        if log_cb:
            log_cb(ui_text("cpk_log_extract_archive", path=reader.path))
        _task_extract_all(reader, out_dir, progress_cb=report if progress_cb else None, log_cb=log_cb)
        done += reader.num_files


def _task_extract_all(reader: CpkReader, out_dir: str,
                      progress_cb=None, log_cb=None):
    from core.external_tools import find_cpkforge, tool_command

    helper = find_cpkforge()
    if helper and reader.uses_default_file_encryption:
        cpk_path = reader.path
        if log_cb:
            log_cb(f"Fast unpack via CPKForge: {cpk_path}")
        if progress_cb:
            progress_cb(0, reader.num_files, cpk_path)
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
            if progress_cb:
                progress_cb(reader.num_files, reader.num_files, cpk_path)
            return

    _task_extract_entries(dict.fromkeys(reader.entries, reader), out_dir,
                          progress_cb=progress_cb, log_cb=log_cb)


def _task_extract_entries(sources, out_dir: str, progress_cb=None, log_cb=None):
    total = len(sources)
    if log_cb:
        log_cb(f"Extracting {total} files to: {out_dir}")

    warn_count = 0
    for i, (entry, reader) in enumerate(sources.items(), start=1):
        dest, decomp_ok = reader.extract_entry(entry, out_dir, decompress=True)
        status = "" if decomp_ok else ui_text("ui_cpk_raw_decompression_not_supported")
        if not decomp_ok:
            warn_count += 1
        if log_cb:
            log_cb(f"  [{i}/{total}] {entry.path}{status}")
        if progress_cb:
            progress_cb(i, total, dest)

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
