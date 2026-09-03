"""C5-A QMainWindow shell."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..bundle import assembly_layers_dir, read_assembly_bundle, write_assembly_bundle
from ..render import render_reference
from ..validation import ValidationResult
from .canvas.view import CanvasView
from .docks.inspector_dock import InspectorDock
from .docks.tree_dock import TreeDock
from .session import CONTEXTS, SelectionModel, UISessionState, sync_session_selection


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Portrait Composer")
        self.resize(1440, 900)
        self.session = UISessionState()
        self.selection_model = SelectionModel()
        self.selection_model.subscribe(lambda _ids: sync_session_selection(self.session, self.selection_model))
        self.document = None
        self.bundle_path: Path | None = None
        self.image_sources: dict[str, Path] = {}

        self.canvas = CanvasView(self.selection_model, self.session, self)
        self.setCentralWidget(self.canvas)
        self.tree_dock = TreeDock(self.selection_model, self)
        self.inspector_dock = InspectorDock(self.selection_model, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.workbench = QLabel("Context Workbench · choose a context to continue")
        self.workbench.setMinimumHeight(90)
        self.workbench.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.workbench.setMargin(12)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._workbench_dock())
        self._build_context_bar()
        self._build_menus()
        self._update_status()

    def _workbench_dock(self):
        from PySide6.QtWidgets import QDockWidget

        dock = QDockWidget("Context Workbench", self)
        dock.setWidget(self.workbench)
        return dock

    def _build_context_bar(self) -> None:
        toolbar = QToolBar("Contexts", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.context_buttons = {}
        for context in CONTEXTS:
            button = QToolButton()
            button.setText(context)
            button.setCheckable(True)
            button.setAccessibleName(f"{context} context")
            button.clicked.connect(lambda checked, c=context: self.set_context(c))
            toolbar.addWidget(button)
            self.context_buttons[context] = button
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.set_context("ASSEMBLE")

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open Assembly Bundle…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_bundle_dialog)
        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_bundle)
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)

        edit_menu = self.menuBar().addMenu("Edit")
        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo)
        redo_action = QAction("Redo", self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        redo_action.triggered.connect(self.redo)
        edit_menu.addAction(undo_action)
        edit_menu.addAction(redo_action)

        view_menu = self.menuBar().addMenu("View")
        fit = QAction("Fit Canvas", self)
        fit.setShortcut(QKeySequence("Shift+F"))
        fit.triggered.connect(self.canvas.fit_canvas)
        fit_selection = QAction("Fit Selection", self)
        fit_selection.setShortcut(QKeySequence("F"))
        fit_selection.triggered.connect(self.canvas.fit_selection)
        view_menu.addAction(fit)
        view_menu.addAction(fit_selection)

    def set_context(self, context: str) -> None:
        self.session.active_context = context
        for name, button in self.context_buttons.items():
            button.setChecked(name == context)
        self.canvas.scene_model.set_context(context)
        self.workbench.setText(f"{context} Workbench\nSelection remains active while context changes.")

    def load_bundle(self, bundle_path: Path) -> None:
        bundle_path = Path(bundle_path)
        document = read_assembly_bundle(bundle_path)
        layers_dir = assembly_layers_dir(bundle_path)
        # Core renderer is the preview source of truth.  Loading is read-only.
        render_reference(document, layers_dir)
        self.document = document
        self.bundle_path = bundle_path
        self.image_sources = {
            instance_id: layers_dir / f"{instance_id}.png"
            for instance_id in document.instances
            if (layers_dir / f"{instance_id}.png").exists()
        }
        self.selection_model.clear()
        self.tree_dock.load_document(document)
        self.canvas.load_document(document, layers_dir)
        self.inspector_dock.refresh([])
        self._update_status()

    def open_bundle_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Assembly Bundle")
        if path:
            try:
                self.load_bundle(Path(path))
            except Exception as exc:
                QMessageBox.critical(self, "Open failed", str(exc))

    def save_bundle(self) -> None:
        if self.document is None:
            return
        target = self.bundle_path
        if target is None:
            chosen = QFileDialog.getExistingDirectory(self, "Save Assembly Bundle")
            if not chosen:
                return
            target = Path(chosen)
        try:
            write_assembly_bundle(self.document, self.image_sources, target)
            self.bundle_path = target
            self.document.mark_saved()
            self._update_status()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def undo(self) -> None:
        if self.document is not None and self.document.history.can_undo():
            self.document.undo()
            self._refresh_after_document_change()

    def redo(self) -> None:
        if self.document is not None and self.document.history.can_redo():
            self.document.redo()
            self._refresh_after_document_change()

    def _refresh_after_document_change(self) -> None:
        if self.document is None or self.bundle_path is None:
            return
        self.tree_dock.load_document(self.document)
        self.canvas.load_document(self.document, assembly_layers_dir(self.bundle_path))
        self.inspector_dock.refresh(self.selection_model.instance_ids)
        self._update_status()

    def _update_status(self) -> None:
        if self.document is None:
            self.statusBar().showMessage("No Assembly Bundle open")
            return
        result = self.document.validate()
        state = "valid" if result.ok else f"{len(result.errors)} errors"
        self.statusBar().showMessage(
            f"{state.upper()}  |  {len(result.warnings)} warnings  |  "
            f"selected: {', '.join(self.selection_model.instance_ids) or 'none'}"
        )
