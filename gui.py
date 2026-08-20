"""Simple Peak Normalizer - peak normalization GUI using PySide6.

"""

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QObject, Signal, Slot, QThreadPool, QRunnable, QSize,
    QRect, QPoint,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QProgressBar,
    QGroupBox, QFileDialog, QMessageBox, QDoubleSpinBox,
    QCheckBox, QAbstractItemView, QSizePolicy, QStyle,
)
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon, QFont, QColor, QPainter

from normalizer import (
    find_audio_files, check_ffmpeg,
    normalize_file, NormalizeResult, SKIP_SUFFIX,
)


class WorkerSignals(QObject):
    """Signals for normalization worker."""
    started = Signal(Path)
    progress = Signal(int, int)  # current, total
    finished = Signal(NormalizeResult)


class NormalizeWorker(QRunnable):
    """Worker for normalizing a single file in the thread pool."""

    def __init__(
        self,
        input_path: Path,
        mode: str,
        target_db: float,
        tolerance_db: float,
        output_dir: Optional[Path] = None,
        source_root: Optional[Path] = None,
        preserve_structure: bool = False,
        index: int = 0,
        total: int = 0,
    ):
        super().__init__()
        self.input_path = input_path
        self.mode = mode
        self.target_db = target_db
        self.tolerance_db = tolerance_db
        self.output_dir = output_dir
        self.source_root = source_root
        self.preserve_structure = preserve_structure
        self.index = index
        self.total = total
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit(self.input_path)
        result = normalize_file(
            self.input_path, self.mode, self.target_db, self.tolerance_db,
            self.output_dir, self.source_root, self.preserve_structure,
        )
        self.signals.finished.emit(result)
        self.signals.progress.emit(self.index, self.total)


class DropListWidget(QListWidget):
    """List widget with drag-and-drop support for folders/files."""

    files_dropped = Signal(list)  # list of Paths

    EMPTY_ICON_SIZE = 36

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() > 0 or not self.isEnabled():
            return

        rect = self.viewport().rect()
        if rect.isEmpty():
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        icon_size = self.EMPTY_ICON_SIZE
        icon_rect = QRect(0, 0, icon_size, icon_size)
        icon_rect.moveCenter(QPoint(rect.center().x(), rect.center().y() - icon_size - 4))
        painter.setOpacity(0.35)
        icon.paint(painter, icon_rect)
        painter.setOpacity(1.0)

        font_main = QFont(self.font())
        font_main.setPointSizeF(9)
        font_main.setBold(True)
        painter.setFont(font_main)
        main_rect = QRect(
            rect.left(), icon_rect.bottom() + 12,
            rect.width(), int(font_main.pointSizeF() * 1.8),
        )
        painter.setPen(QColor("#e5e5e5"))
        painter.drawText(
            main_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Drop files or folders",
        )

        font_sub = QFont(self.font())
        font_sub.setPointSizeF(7.5)
        painter.setFont(font_sub)
        sub_rect = QRect(
            rect.left(), main_rect.bottom() + 4,
            rect.width(), int(font_sub.pointSizeF() * 1.6),
        )
        painter.setPen(QColor("#92959a"))
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "WAV · MP3 · FLAC · AIFF · OGG · M4A",
        )

    def __init__(self):
        super().__init__()
        self.setObjectName("dropList")
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.viewport().setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            self.viewport().update()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().update()

        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path:
                    path = Path(local_path)
                    if path.exists():
                        paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Peak Normalizer")
        self.setAcceptDrops(True)

        desired_w, desired_h = 900, 360
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            w = int(min(desired_w, max(geo.width() - 48, 900)))
            h = int(min(desired_h, max(geo.height() - 48, 360)))
        else:
            w, h = desired_w, desired_h
        self.setFixedSize(w, h)

        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            center = geo.center()
            self.move(int(center.x() - self.width() / 2),
                      int(center.y() - self.height() / 2))

        # State
        self.pending_files: list[tuple[Path, Optional[Path]]] = []  # (file, source_root)
        self.output_dir: Optional[Path] = None
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(2)

        self._counts = {"normalized": 0, "skipped_range": 0,
                        "skipped_suffix": 0, "failed": 0}

        self.load_stylesheet()
        self.load_ui()

        if not check_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg is required but not found in PATH.\n"
                "Please install FFmpeg and add it to your system PATH."
            )

    def load_stylesheet(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        style_path = base / "styles.qss"
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def load_ui(self):
        """Build the layout in code and wire the dynamic parts."""
        central = QWidget()
        central.setObjectName("centralwidget")
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(16, 8, 16, 8)

        def panel(title, name):
            box = QGroupBox(title)
            box.setObjectName(name)
            layout = QVBoxLayout(box)
            layout.setSpacing(6)
            layout.setContentsMargins(8, 8, 8, 8)
            return box, layout

        # ---- Title ----
        title_label = QLabel("Simple Peak Normalizer")
        title_label.setObjectName("titleLabel")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setMinimumHeight(32)
        title_label.setMaximumHeight(32)
        root.addWidget(title_label)

        # ---- Sections (FILES / NORMALIZE / PROGRESS, 44 / 28 / 28) ----
        sections = QHBoxLayout()
        sections.setObjectName("sectionsLayout")
        sections.setSpacing(8)
        sections.setContentsMargins(0, 0, 0, 0)
        root.addLayout(sections)
        

        # ---- FILES panel ----
        files_panel, files_layout = panel("FILES", "filesPanel")
        self.file_list = DropListWidget()
        self.file_list.setMinimumHeight(100)
        self.file_list.setMaximumHeight(120)
        self.file_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.file_list.files_dropped.connect(self.add_files)
        files_layout.addWidget(self.file_list)

        self.browse_folder_btn = QPushButton("Add folder")
        self.browse_folder_btn.setObjectName("browse_folder_btn")
        self.browse_folder_btn.setToolTip("Add a folder of samples")
        self.browse_folder_btn.setMinimumHeight(25)
        self.browse_folder_btn.clicked.connect(self.browse_folder_manually)
        files_layout.addWidget(self.browse_folder_btn)

        controls = QHBoxLayout()
        controls.setObjectName("controlsLayout")
        controls.setSpacing(8)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("clear_btn")
        self.clear_btn.setMinimumHeight(25)
        self.clear_btn.clicked.connect(self.clear_queue)
        controls.addWidget(self.clear_btn)
        self.remove_btn = QPushButton("Delete selected")
        self.remove_btn.setObjectName("remove_btn")
        self.remove_btn.setMinimumHeight(32)
        self.remove_btn.clicked.connect(self.remove_selected)
        controls.addWidget(self.remove_btn)
        controls.addStretch(1)
        files_layout.addLayout(controls)
        sections.addWidget(files_panel, 35)

        # ---- NORMALIZE panel ----
        settings_panel, settings_layout = panel("NORMALIZE", "settingsPanel")

        self.replace_cb = QCheckBox("Replace original files")
        self.replace_cb.setObjectName("replace_cb")
        self.replace_cb.setToolTip(
            "When enabled, the original file is replaced in place (deleted "
            "after normalization). This only applies when saving next to the "
            "source. Use an output folder or the structure mirror to keep "
            "originals intact."
        )
        settings_layout.addWidget(self.replace_cb)

        target_row = QHBoxLayout()
        target_row.setSpacing(6)
        target_row.addWidget(QLabel("Target peak"))
        target_row.addStretch(1)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setObjectName("target_spin")
        self.target_spin.setRange(-12.0, -0.1)
        self.target_spin.setDecimals(1)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.setValue(-1.0)
        self.target_spin.setSuffix(" dB")
        self.target_spin.setToolTip(
            "Every clip is normalized so its own peak reaches this level. "
            "0 dB is the maximum; -1 dB leaves headroom to avoid clipping."
        )
        target_row.addWidget(self.target_spin)
        settings_layout.addLayout(target_row)

        tol_row = QHBoxLayout()
        tol_row.setSpacing(6)
        tol_row.addWidget(QLabel("Skip if within"))
        tol_row.addStretch(1)
        self.tol_spin = QDoubleSpinBox()
        self.tol_spin.setObjectName("tol_spin")
        self.tol_spin.setRange(0.0, 6.0)
        self.tol_spin.setDecimals(1)
        self.tol_spin.setSingleStep(0.1)
        self.tol_spin.setValue(0.5)
        self.tol_spin.setSuffix(" dB")
        self.tol_spin.setToolTip(
            "Files whose peak is already within this distance of the target "
            "are left untouched."
        )
        tol_row.addWidget(self.tol_spin)
        settings_layout.addLayout(tol_row)

        hint = QLabel(
            "Each clip is normalized to its own peak level.\n"
            "Use an output folder or keep original structure intact."
        )
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        settings_layout.addWidget(hint)

        self.output_row = QWidget(settings_panel)
        self.output_row.setObjectName("outputRow")
        self.output_row.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self.output_row.setMinimumHeight(38)
        self.output_row.setMaximumHeight(38)
        row_layout = QHBoxLayout(self.output_row)
        row_layout.setObjectName("outputRowLayout")
        row_layout.setSpacing(0)
        row_layout.setContentsMargins(12, 0, 4, 0)
        self.output_label = QLabel("Same folder as source")
        self.output_label.setObjectName("outputFieldText")
        self.output_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        row_layout.addWidget(self.output_label, 1)
        self.output_browse_btn = QPushButton("Browse")
        self.output_browse_btn.setObjectName("browseBtn")
        self.output_browse_btn.clicked.connect(self.choose_output_dir)
        row_layout.addWidget(self.output_browse_btn)
        settings_layout.addWidget(self.output_row)

        self.mirror_cb = QCheckBox("Preserve source folder structure")
        self.mirror_cb.setObjectName("mirror_cb")
        self.mirror_cb.setChecked(True)
        self.mirror_cb.setToolTip(
            "If enabled, the source folder structure is recreated inside the "
            "output folder (or in a <source>_N folder next to it). If no "
            "output folder is set, files are saved next to their source."
        )
        settings_layout.addWidget(self.mirror_cb)
        settings_layout.addStretch(1)
        sections.addWidget(settings_panel, 28)

        # ---- PROGRESS panel ----
        progress_panel = QGroupBox("PROGRESS")
        progress_panel.setObjectName("progressPanel")
        progress_layout = QVBoxLayout(progress_panel)
        progress_layout.setObjectName("progressLayout")
        progress_layout.setSpacing(4)
        progress_layout.setContentsMargins(5, 6, 5, 6)

        self.overall_progress = QProgressBar()
        self.overall_progress.setObjectName("overall_progress")
        self.overall_progress.setValue(0)
        self.overall_progress.setMinimumHeight(20)
        self.overall_progress.setMaximumHeight(20)
        progress_layout.addWidget(self.overall_progress)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)
        progress_layout.addStretch(1)

        self.convert_btn = QPushButton("START")
        self.convert_btn.setObjectName("convertBtn")
        self.convert_btn.setMinimumHeight(20)
        self.convert_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self.start_normalization)
        progress_layout.addWidget(self.convert_btn)
        sections.addWidget(progress_panel, 28)

        # ---- Footer ----
        footer = QLabel(
            "Peak normalization | linear gain only | "
            "preserves sample rate & bit depth | suffix \"_N\""
        )
        footer.setObjectName("footerLabel")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setMinimumHeight(15)
        footer.setMaximumHeight(15)
        root.addWidget(footer)

        self.setCentralWidget(central)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path and Path(local_path).exists():
                    paths.append(Path(local_path))
            if paths:
                self.add_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_files(self, paths: list[Path]):
        """Add files/folders to the queue (skipping already processed *_N).

        Each file keeps its source_root (the scanned folder), so the folder
        structure can be preserved later.
        """
        new_pairs: list[tuple[Path, Optional[Path]]] = []
        for path in paths:
            if path.is_dir():
                for f in find_audio_files(path, recursive=True):
                    new_pairs.append((f, path))
            elif path.is_file():
                new_pairs.append((path, None))

        # Skip files that are already normalized versions (*_N)
        new_pairs = [
            (f, root) for (f, root) in new_pairs
            if not f.stem.lower().endswith(SKIP_SUFFIX.lower())
        ]

        seen = set(fs for (fs, _) in self.pending_files)
        for f, root in new_pairs:
            resolved = f.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            self.pending_files.append((f, root))

        self.rebuild_list()
        self.update_start_button()

    def rebuild_list(self):
        """Rebuild the queue list, grouping samples by their source folder."""
        self.file_list.setUpdatesEnabled(False)
        self.file_list.clear()

        groups: dict[Path, list[tuple[Path, Optional[Path]]]] = {}
        order: list[Path] = []
        for f, root in self.pending_files:
            parent = f.parent
            if parent not in groups:
                groups[parent] = []
                order.append(parent)
            groups[parent].append((f, root))

        for parent in order:
            items = groups[parent]
            header = QListWidgetItem(parent.name)
            header.setForeground(QColor("#e8a33d"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # header not selectable
            header.setToolTip(f"{len(items)} samples in {parent}")
            self.file_list.addItem(header)

            for f, root in items:
                item = QListWidgetItem(f.name)
                item.setData(Qt.ItemDataRole.UserRole, (f, root))
                item.setToolTip(str(f))
                self.file_list.addItem(item)

        self.file_list.setUpdatesEnabled(True)
        self._update_drop_zone_height()

    def _update_drop_zone_height(self):
        if self.file_list.count() > 0:
            self.file_list.setMaximumHeight(16777215)
        else:
            self.file_list.setMaximumHeight(160)

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            pair = item.data(Qt.ItemDataRole.UserRole)
            if pair in self.pending_files:
                self.pending_files.remove(pair)
        self.rebuild_list()
        self.update_start_button()

    def clear_queue(self):
        self.pending_files.clear()
        self.rebuild_list()
        self.update_start_button()

    def browse_folder_manually(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Set source")
        if folder_path:
            folder = Path(folder_path)
            before = len(self.pending_files)
            self.add_files([folder])
            added = len(self.pending_files) - before
            if added:
                self.status_label.setText(f"Added {added} from {folder.name}")
            else:
                QMessageBox.information(
                    self,
                    "No files",
                    f"No unprocessed audio files were found in: {folder_path}"
                )

    def choose_output_dir(self):
        """Select the output folder where normalized files are saved."""
        dir_path = QFileDialog.getExistingDirectory(self, "Set output folder")
        if dir_path:
            self.output_dir = Path(dir_path)
            elided = self.output_label.fontMetrics().elidedText(
                str(self.output_dir), Qt.TextElideMode.ElideMiddle, 260
            )
            self.output_label.setText(elided)
            self.output_label.setToolTip(str(self.output_dir))

    def update_start_button(self):
        has_files = len(self.pending_files) > 0
        self.convert_btn.setEnabled(has_files)
        self.convert_btn.setText(
            f"START ({len(self.pending_files)})" if has_files else "START"
        )

    def start_normalization(self):
        if not self.pending_files:
            return

        mode = "replace" if self.replace_cb.isChecked() else "copy"
        target_db = self.target_spin.value()
        tolerance_db = self.tol_spin.value()

        if mode == "replace":
            reply = QMessageBox.question(
                self,
                "Replace originals",
                "The original files will be DELETED after normalization.\n"
                "(Replacement only applies when saving next to the source;\n"
                "using an output folder never touches the originals.)\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.convert_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.browse_folder_btn.setEnabled(False)
        self.target_spin.setEnabled(False)
        self.tol_spin.setEnabled(False)
        self.replace_cb.setEnabled(False)
        self.output_browse_btn.setEnabled(False)
        self.mirror_cb.setEnabled(False)
        self.file_list.setEnabled(False)

        self._counts = {"normalized": 0, "skipped_range": 0,
                        "skipped_suffix": 0, "failed": 0}

        self.overall_progress.setRange(0, len(self.pending_files))
        self.overall_progress.setValue(0)
        self.status_label.setText("Starting...")

        preserve = self.mirror_cb.isChecked()
        for i, (file_path, source_root) in enumerate(self.pending_files):
            worker = NormalizeWorker(
                file_path, mode, target_db, tolerance_db,
                self.output_dir, source_root, preserve,
                i + 1, len(self.pending_files),
            )
            worker.signals.finished.connect(self.on_file_finished)
            worker.signals.progress.connect(self.on_progress_update)
            self.thread_pool.start(worker)

    @Slot(NormalizeResult)
    def on_file_finished(self, result: NormalizeResult):
        name = result.input_path.name
        if result.success:
            if result.action == "skipped_range":
                self._counts["skipped_range"] += 1
                self.status_label.setText(f"{name} already in range (gain {result.gain_db:+.1f} dB)")
            elif result.action == "skipped_suffix":
                self._counts["skipped_suffix"] += 1
                self.status_label.setText(f"{name} already processed")
            else:
                self._counts["normalized"] += 1
                out_name = result.output_path.name if result.output_path else name
                self.status_label.setText(
                    f"{name} -> {out_name} ({result.gain_db:+.1f} dB)"
                )
        else:
            self._counts["failed"] += 1
            self.status_label.setText(f"{name}: {result.error}")

    @Slot(int, int)
    def on_progress_update(self, current: int, total: int):
        self.overall_progress.setValue(current)
        if current == total:
            self.normalization_complete()

    def normalization_complete(self):
        self.convert_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.browse_folder_btn.setEnabled(True)
        self.target_spin.setEnabled(True)
        self.tol_spin.setEnabled(True)
        self.replace_cb.setEnabled(True)
        self.output_browse_btn.setEnabled(True)
        self.mirror_cb.setEnabled(True)
        self.file_list.setEnabled(True)

        c = self._counts
        summary = (
            f"{c['normalized']} normalized | "
            f"{c['skipped_range']} already in range | "
            f"{c['skipped_suffix']} already processed | "
            f"{c['failed']} failed"
        )
        self.status_label.setText("Normalization complete!")
        QMessageBox.information(self, "Complete", f"Done.\n\n{summary}")


def is_elevated() -> bool:
    """Check if the current process runs with administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def load_app_icon() -> Optional[QIcon]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon_path = base / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Simple Peak Normalizer")
    app.setApplicationVersion("1.0.0")

    app_icon = load_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()

    if is_elevated():
        QMessageBox.warning(
            window,
            "Running as administrator",
            "The application is running with administrator privileges.\n\n"
            "Windows may block drag and drop files from Explorer to "
            "(the prohibited cursor is shown).\n\n"
            "Close this instance and run it WITHOUT administrator privileges. "
            "(You can still use 'Add folder'.)"
        )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()