"""C5-A QMainWindow shell."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..assembly import identity_assembly
from ..bundle import (
    assembly_layers_dir,
    read_assembly_bundle,
    read_portrait_bundle,
    write_assembly_bundle,
)
from ..document import AssemblyDocument
from ..render import render_reference
from .canvas.view import CanvasView
from .commands import harvest_semantic, nudge_draw_order
from .diagnostics import Diagnostic, collect_diagnostics
from .docks.diagnostics_dock import DiagnosticsDock
from .docks.inspector_dock import InspectorDock
from .docks.tree_dock import TreeDock
from .portrait_import import PortraitInputWorkspace
from .portrait_input_dialog import PortraitInputDialog
from .session import CONTEXTS, SelectionModel, UISessionState, sync_session_selection
from .workbenches.donor import DonorWorkbench
from .workbenches.harvest import HarvestWorkbench
from .workbenches.bake import BakeWorkbench
from .workbenches.rig_intent import RigIntentWorkbench
from .workbenches.variants import VariantWorkbench


class MainWindow(QMainWindow):
    SETTINGS_ORGANIZATION = "prentice7725"
    SETTINGS_APPLICATION = "PortraitComposer"
    MAX_RECENT_FILES = 10

    def __init__(self, parent=None, *, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Portrait Composer")
        self.resize(1440, 900)
        self.session = UISessionState()
        self.settings = settings or QSettings(self.SETTINGS_ORGANIZATION, self.SETTINGS_APPLICATION)
        self.recent_files: list[str] = self._read_recent_files()
        self._pending_view_state: tuple[float, tuple[float, float]] | None = None
        self.selection_model = SelectionModel()
        self.selection_model.subscribe(lambda _ids: sync_session_selection(self.session, self.selection_model))
        self.selection_model.subscribe(lambda _ids: self._on_selection_changed())
        self.document = None
        self.bundle_path: Path | None = None
        self.image_sources: dict[str, Path] = {}
        self._canvas_layers_dir = Path(".")
        self._canvas_image_sources: dict[str, Path] | None = None
        self._portrait_workspace = PortraitInputWorkspace()
        self.import_warnings: list[str] = []
        self.harvest_source_pool = {}
        self.diagnostics: list[Diagnostic] = []

        self.canvas = CanvasView(self.selection_model, self.session, self)
        self.setCentralWidget(self.canvas)
        self.tree_dock = TreeDock(self.selection_model, self)
        self.tree_dock.search.textChanged.connect(self._set_tree_filter)
        self.inspector_dock = InspectorDock(self.selection_model, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.workbench_placeholder = QLabel("Context Workbench · choose a context to continue")
        self.workbench_placeholder.setMinimumHeight(90)
        self.workbench_placeholder.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.workbench_placeholder.setMargin(12)
        self.harvest_workbench = HarvestWorkbench(self)
        self.variant_workbench = VariantWorkbench(self)
        self.donor_workbench = DonorWorkbench(self)
        self.rig_intent_workbench = RigIntentWorkbench(self)
        self.bake_workbench = BakeWorkbench(self)
        self.workbench = QStackedWidget()
        self.workbench.addWidget(self.workbench_placeholder)
        self.workbench.addWidget(self.harvest_workbench)
        self.workbench.addWidget(self.variant_workbench)
        self.workbench.addWidget(self.donor_workbench)
        self.workbench.addWidget(self.rig_intent_workbench)
        self.workbench.addWidget(self.bake_workbench)
        self.workbench_dock = self._workbench_dock()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.workbench_dock)
        self.diagnostics_dock = DiagnosticsDock(self, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock)
        self.tabifyDockWidget(self.workbench_dock, self.diagnostics_dock)
        self.workbench_dock.raise_()
        self._build_context_bar()
        self._build_menus()
        self._restore_workspace_settings()
        self._update_status()

    def _workbench_dock(self):
        from PySide6.QtWidgets import QDockWidget

        dock = QDockWidget("Context Workbench", self)
        dock.setObjectName("contextWorkbenchDock")
        dock.setWidget(self.workbench)
        return dock

    def _set_workbench_message(self, text: str) -> None:
        self.workbench_placeholder.setText(text)
        self.workbench.setCurrentWidget(self.workbench_placeholder)

    def _build_context_bar(self) -> None:
        toolbar = QToolBar("Contexts", self)
        toolbar.setObjectName("contextToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.context_buttons = {}
        for context in CONTEXTS:
            button = QToolButton()
            button.setText(context)
            button.setCheckable(True)
            button.setToolTip(f"Switch to {context} context")
            button.setAccessibleName(f"{context} context")
            button.clicked.connect(lambda checked, c=context: self.set_context(c))
            toolbar.addWidget(button)
            self.context_buttons[context] = button
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.set_context("ASSEMBLE")

    def _set_tree_filter(self, value: str) -> None:
        self.session.tree_filter = value

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        new_action = QAction("New Assembly", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_assembly)
        import_action = QAction("Import Portrait Bundle…", self)
        import_action.triggered.connect(self.import_portrait_bundle_dialog)
        import_runs_action = QAction("Import Portrait Runs…", self)
        import_runs_action.triggered.connect(self.import_portrait_runs_dialog)
        open_action = QAction("Open Assembly Bundle…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_bundle_dialog)
        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_bundle)
        save_as_action = QAction("Save As…", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self.save_bundle_as)
        file_menu.addAction(new_action)
        file_menu.addSeparator()
        file_menu.addAction(import_action)
        file_menu.addAction(import_runs_action)
        file_menu.addSeparator()
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)
        self.recent_menu = file_menu.addMenu("Recent Files")
        self.recent_menu.setAccessibleName("Recent files")
        self._update_recent_menu()

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
        edit_menu.addSeparator()
        bring_forward = QAction("Bring Forward", self)
        bring_forward.setShortcut(QKeySequence("]"))
        bring_forward.triggered.connect(lambda: self._nudge_draw_order(direction=1))
        send_backward = QAction("Send Backward", self)
        send_backward.setShortcut(QKeySequence("["))
        send_backward.triggered.connect(lambda: self._nudge_draw_order(direction=-1))
        bring_front = QAction("Bring to Front", self)
        bring_front.setShortcut(QKeySequence("Shift+]"))
        bring_front.triggered.connect(lambda: self._nudge_draw_order(to_extreme=1))
        send_back = QAction("Send to Back", self)
        send_back.setShortcut(QKeySequence("Shift+["))
        send_back.triggered.connect(lambda: self._nudge_draw_order(to_extreme=-1))
        edit_menu.addAction(bring_forward)
        edit_menu.addAction(send_backward)
        edit_menu.addAction(bring_front)
        edit_menu.addAction(send_back)

        view_menu = self.menuBar().addMenu("View")
        fit = QAction("Fit Canvas", self)
        fit.setShortcut(QKeySequence("Shift+F"))
        fit.triggered.connect(self.canvas.fit_canvas)
        fit_selection = QAction("Fit Selection", self)
        fit_selection.setShortcut(QKeySequence("F"))
        fit_selection.triggered.connect(self.canvas.fit_selection)
        view_menu.addAction(fit)
        view_menu.addAction(fit_selection)
        view_menu.addSeparator()
        search_action = QAction("Focus Tree Search", self)
        search_action.setShortcut(QKeySequence("Ctrl+F"))
        search_action.setToolTip("Focus the Assembly Tree search field")
        search_action.triggered.connect(self.focus_tree_search)
        view_menu.addAction(search_action)
        view_menu.addSeparator()
        context_shortcuts = (("Harvest", "H", "HARVEST"), ("Donor Align", "D", "DONOR"), ("Rig Intent", "I", "RIG INTENT"), ("Bake", "B", "BAKE"))
        for label, key, context in context_shortcuts:
            action = QAction(label, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda checked=False, c=context: self.set_context(c))
            view_menu.addAction(action)

    def _read_recent_files(self) -> list[str]:
        value = self.settings.value("recent_files", [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        return list(dict.fromkeys(str(path) for path in value if str(path)))[: self.MAX_RECENT_FILES]

    def _update_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        if not self.recent_files:
            empty = self.recent_menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for path in self.recent_files:
            action = self.recent_menu.addAction(path)
            action.setToolTip(f"Open {path}")
            action.triggered.connect(lambda checked=False, value=path: self._open_recent(value))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear Recent Files")
        clear.triggered.connect(self._clear_recent_files)

    def _remember_recent(self, path: Path) -> None:
        value = str(Path(path).resolve())
        self.recent_files = [value, *(item for item in self.recent_files if item != value)]
        self.recent_files = self.recent_files[: self.MAX_RECENT_FILES]
        self.settings.setValue("recent_files", self.recent_files)
        self._update_recent_menu()

    def _clear_recent_files(self) -> None:
        self.recent_files = []
        self.settings.remove("recent_files")
        self._update_recent_menu()

    def _open_recent(self, value: str) -> None:
        path = Path(value)
        try:
            self.open_path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Recent file failed", str(exc))

    def open_path(self, path: Path) -> None:
        """Open an Assembly Bundle or import a Portrait Bundle input path."""
        path = Path(path)
        if path.suffix.lower() == ".zip":
            self._import_portrait_bundle(path)
            return
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") == "portrait-bundle":
            self._import_portrait_bundle(path)
        else:
            self.load_bundle(path)

    def _restore_workspace_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None and not self.restoreGeometry(geometry):
            self.resize(1440, 900)
        state = self.settings.value("window_state")
        if state is not None:
            self.restoreState(state)
        context = self.settings.value("last_context", "ASSEMBLE")
        if context in CONTEXTS:
            self.set_context(str(context))
        tree_filter = self.settings.value("tree_filter", "")
        self.tree_dock.search.setText(str(tree_filter or ""))
        tree_filter_mode = str(self.settings.value("tree_filter_mode", "All") or "All")
        if self.tree_dock.filter_selector.findText(tree_filter_mode) >= 0:
            self.tree_dock.filter_selector.setCurrentText(tree_filter_mode)
        try:
            zoom = float(self.settings.value("canvas_zoom", 1.0))
            pan = (
                float(self.settings.value("canvas_pan_x", 0.0)),
                float(self.settings.value("canvas_pan_y", 0.0)),
            )
            self._pending_view_state = (zoom, pan)
        except (TypeError, ValueError):
            self._pending_view_state = None

    def _save_workspace_settings(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("last_context", self.session.active_context)
        self.settings.setValue("canvas_zoom", self.session.canvas_zoom)
        self.settings.setValue("canvas_pan_x", self.session.canvas_pan[0])
        self.settings.setValue("canvas_pan_y", self.session.canvas_pan[1])
        self.settings.setValue("tree_filter", self.tree_dock.search.text())
        self.settings.setValue("tree_filter_mode", self.tree_dock.filter_selector.currentText())
        self.settings.setValue("recent_files", self.recent_files)
        self.settings.sync()

    def set_context(self, context: str) -> None:
        previous = self.session.active_context
        self.session.active_context = context
        for name, button in self.context_buttons.items():
            button.setChecked(name == context)
        self.canvas.scene_model.set_context(context)
        if previous == "DONOR" and context != "DONOR":
            # An uncommitted donor ghost is local, transient state for this
            # one workspace (directive #18) -- it never leaked into the
            # document, so there's nothing to preserve across a switch away.
            self.donor_workbench.clear_ghost()
        if context == "HARVEST" and self.harvest_source_pool:
            self.harvest_workbench.refresh()
            self.workbench.setCurrentWidget(self.harvest_workbench)
        elif context == "VARIANTS" and self.document is not None:
            self.variant_workbench.refresh()
            self.workbench.setCurrentWidget(self.variant_workbench)
        elif context == "DONOR" and self.document is not None:
            self.donor_workbench.refresh()
            self.workbench.setCurrentWidget(self.donor_workbench)
        elif context == "RIG INTENT" and self.document is not None:
            self.rig_intent_workbench.refresh()
            self.workbench.setCurrentWidget(self.rig_intent_workbench)
        elif context == "BAKE" and self.document is not None:
            self.bake_workbench.refresh()
            self.workbench.setCurrentWidget(self.bake_workbench)
        else:
            self._set_workbench_message(f"{context} Workbench\nSelection remains active while context changes.")
        if previous == "RIG INTENT" and context != "RIG INTENT":
            # The two_lobe canvas overlay is this workspace's own transient
            # editing aid (directive #18); it isn't part of any other
            # context's canvas presentation.
            self.canvas.scene_model.region_edit.clear()
        if previous in {"BAKE", "VARIANTS"} and context not in {"BAKE", "VARIANTS"}:
            self.canvas.scene_model.clear_transient_preview()
        if hasattr(self, "diagnostics_dock"):
            self._refresh_diagnostics()

    def _on_selection_changed(self) -> None:
        if self.workbench.currentWidget() is self.donor_workbench:
            self.donor_workbench.refresh()
        elif self.workbench.currentWidget() is self.rig_intent_workbench:
            self.rig_intent_workbench.refresh()

    def new_assembly(self) -> None:
        document = AssemblyDocument()
        with document.transaction():
            document.composition["canvas"] = {
                "width": 1024,
                "height": 1024,
                "coordinate_system": "top-left-y-down",
                "color_space": "srgb",
                "alpha": "straight",
            }
        self.harvest_source_pool = {}
        self._display_document(document, {}, Path("."), source_map=False)
        self._set_workbench_message("ASSEMBLE Workbench\nNew Assembly is ready for input.")

    def load_bundle(self, bundle_path: Path) -> None:
        bundle_path = Path(bundle_path)
        document = read_assembly_bundle(bundle_path)
        layers_dir = assembly_layers_dir(bundle_path)
        image_sources = {
            instance_id: layers_dir / f"{instance_id}.png"
            for instance_id in document.instances
            if (layers_dir / f"{instance_id}.png").exists()
        }
        # Core renderer is the preview source of truth. Loading is read-only.
        render_reference(document, layers_dir)
        self._display_document(document, image_sources, layers_dir, source_map=False, bundle_path=bundle_path)
        self._remember_recent(bundle_path)

    def _display_document(
        self,
        document,
        image_sources: dict[str, Path],
        layers_dir: Path,
        *,
        source_map: bool,
        bundle_path: Path | None = None,
        import_warnings: list[str] | None = None,
    ) -> None:
        self.document = document
        self.bundle_path = bundle_path
        self.image_sources = dict(image_sources)
        self._canvas_layers_dir = Path(layers_dir)
        # Alias, don't copy: a command that adds/replaces an instance (e.g.
        # a later harvest re-pick) mutates self.image_sources in place, and
        # the canvas must see that same dict, not a snapshot from load time.
        self._canvas_image_sources = self.image_sources if source_map else None
        self.import_warnings = list(import_warnings or [])
        self.session.bake_analyzed = False
        self.selection_model.clear()
        self._refresh_diagnostics()
        self.tree_dock.load_document(document, self.diagnostics)
        self.canvas.load_document(document, self._canvas_layers_dir, self._canvas_image_sources)
        self.session.last_render_ms = self.canvas.scene_model.last_render_ms
        if self._pending_view_state is not None:
            zoom, pan = self._pending_view_state
            self.canvas.restore_view_state(zoom, pan)
            self._pending_view_state = None
        self.inspector_dock.refresh([])
        self._update_status()

    def import_portrait_bundle_dialog(self) -> None:
        dialog = PortraitInputDialog(multiple=False, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._import_portrait_bundle(dialog.paths[0])

    def _import_portrait_bundle(self, source_path: Path) -> None:
        try:
            prepared = self._portrait_workspace.read(source_path)
            document, image_sources, warnings = identity_assembly(prepared.bundle)
        except Exception as exc:
            QMessageBox.critical(self, "Portrait import failed", str(exc))
            return
        if not self._confirm_portrait_import(prepared.bundle, warnings):
            return
        self.harvest_source_pool = {}
        self._display_document(
            document,
            image_sources,
            prepared.root,
            source_map=True,
            import_warnings=warnings,
        )
        self.set_context("ASSEMBLE")
        self._set_workbench_message(
            "ASSEMBLE Workbench\n"
            f"Imported {prepared.label}; the Assembly is ready to edit and save."
        )
        self._remember_recent(source_path)

    def _refresh_diagnostics(self) -> None:
        self.diagnostics = collect_diagnostics(self.document, self.import_warnings)
        if hasattr(self, "diagnostics_dock"):
            self.diagnostics_dock.refresh(self.document, self.diagnostics, self.session)

    def diagnostics_for_target(self, target_id: str) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.target_id == target_id]

    def focus_diagnostic(self, diagnostic: Diagnostic) -> None:
        """Navigate to a diagnostic target without changing document state."""
        if diagnostic.context in self.context_buttons and diagnostic.context != self.session.active_context:
            self.set_context(diagnostic.context)
        target_id = diagnostic.target_id
        if target_id is None or self.document is None:
            self.statusBar().showMessage(f"{diagnostic.severity}: {diagnostic.message}", 6000)
            return
        if target_id in self.document.instances:
            instance_ids = [target_id]
            asset_id = self.document.instances[target_id].asset_ref
        elif target_id in self.document.assets:
            asset_id = target_id
            instance_ids = [
                instance_id
                for instance_id, instance in self.document.instances.items()
                if instance.asset_ref == target_id
            ]
        else:
            instance_ids = []
            asset_id = None
        if not instance_ids:
            self.statusBar().showMessage(f"{diagnostic.severity}: {diagnostic.message}", 6000)
            return
        self.selection_model.set_instances(instance_ids, asset_id=asset_id)
        self.tree_dock.reveal_instances(instance_ids)
        self.canvas.fit_selection()

    def _confirm_portrait_import(self, bundle, warnings: list[str]) -> bool:
        generation = bundle.generation
        validation = bundle.validation
        validation_lines = [f"  {name}: {value}" for name, value in validation.items()]
        summary = [
            f"Canonical layers   {len(bundle.layers)}",
            f"Seed mode          {generation.get('seed_mode', 'unknown')}",
            f"Seed               {generation.get('seed', 'unknown')}",
            "",
            "Validation",
            *(validation_lines or ["  no validation statuses"]),
            "",
            f"Warnings           {len(warnings)}",
        ]
        if warnings:
            summary.extend(f"  - {warning}" for warning in warnings)
        message = QMessageBox(self)
        message.setWindowTitle("Imported Portrait Bundle v1")
        message.setIcon(QMessageBox.Icon.Information)
        message.setText("Portrait Bundle imported")
        message.setInformativeText("\n".join(summary))
        start = message.addButton("Start Assembly", QMessageBox.ButtonRole.AcceptRole)
        message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()
        return message.clickedButton() is start

    def import_portrait_runs_dialog(self) -> None:
        dialog = PortraitInputDialog(multiple=True, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._import_portrait_runs(dialog.paths)

    def _import_portrait_runs(self, source_paths: list[Path]) -> None:
        prepared = []
        try:
            for source_path in source_paths:
                prepared.append(self._portrait_workspace.read(source_path))
        except Exception as exc:
            QMessageBox.critical(self, "Portrait runs import failed", str(exc))
            return

        pool = {}
        for item in prepared:
            label = item.label
            suffix = 2
            while label in pool:
                label = f"{item.label}_{suffix}"
                suffix += 1
            pool[label] = item.bundle
        self.harvest_source_pool = pool
        self.session.harvest_run_labels = list(pool)
        self.set_context("HARVEST")
        for source_path in source_paths:
            self._remember_recent(source_path)
        self.statusBar().showMessage(f"Portrait source pool ready: {len(pool)} runs")

    def apply_harvest_pick(self, target_tag: str, run_label: str) -> None:
        """Commits one Harvest Workbench candidate pick (directive #8.2).

        The very first pick in a session has no document yet -- unlike
        every other command, this one may need to create it (sized to the
        picked bundle's canvas) before it can run through the normal
        run_command/_refresh_after_document_change path.
        """
        if self.document is None:
            document = AssemblyDocument()
            image_sources: dict[str, Path] = {}
            try:
                harvest_semantic(document, image_sources, self.harvest_source_pool, target_tag, run_label)
            except Exception as exc:
                self.statusBar().showMessage(f"Harvest failed: {exc}", 6000)
                return
            self.document = document
            self.bundle_path = None
            self.image_sources = image_sources
            self._canvas_layers_dir = Path(".")
            # Harvested images live at their producer paths until Save, just
            # like a freshly imported Portrait Bundle -- alias, don't copy,
            # so later picks that mutate self.image_sources stay visible to
            # the canvas without a second, separately-drifting dict.
            self._canvas_image_sources = self.image_sources
            self.import_warnings = []
            self.selection_model.clear()
            self._refresh_after_document_change()
            return

        self.run_command(
            lambda document, image_sources: harvest_semantic(
                document, image_sources, self.harvest_source_pool, target_tag, run_label
            )
        )

    def closeEvent(self, event) -> None:
        self._save_workspace_settings()
        self._portrait_workspace.cleanup()
        super().closeEvent(event)

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
        if self.bundle_path is None:
            self.save_bundle_as()
            return
        self._write_bundle(self.bundle_path)

    def save_bundle_as(self) -> None:
        if self.document is None:
            return
        chosen = QFileDialog.getExistingDirectory(self, "Save Assembly Bundle As")
        if not chosen:
            return
        self._write_bundle(Path(chosen))

    def _write_bundle(self, target: Path) -> None:
        if self.document is None:
            return
        validation = self.document.validate()
        if not validation.ok:
            details = "\n".join(f"- {message}" for message in validation.errors)
            self.statusBar().showMessage(f"Save blocked: document validation failed. {details}", 10000)
            return False
        try:
            write_assembly_bundle(self.document, self.image_sources, target)
            self.bundle_path = target
            self.document.mark_saved()
            self._remember_recent(target)
            self._update_status()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False

    def commit_pending_operation(self) -> None:
        if self.session.active_context == "HARVEST":
            self.harvest_workbench.commit_pending()

    def cancel_pending_operation(self) -> None:
        if self.session.active_context == "HARVEST":
            self.harvest_workbench.cancel_pending()
        self.canvas.scene_model.clear_transient_preview()

    def focus_tree_search(self) -> None:
        self.tree_dock.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.tree_dock.search.selectAll()

    def set_canvas_tool(self, tool: str) -> None:
        self.session.canvas_tool = tool
        self.statusBar().showMessage(f"Canvas tool: {tool}", 2500)

    def set_preview_mode_shortcut(self, mode: str) -> None:
        self.session.preview_mode = mode
        if self.session.active_context == "HARVEST":
            harvest_mode = {"donor_only": "solo"}.get(mode, mode)
            for button in self.harvest_workbench.mode_group.buttons():
                if button.property("mode") == harvest_mode:
                    button.setChecked(True)
                    break
        elif self.session.active_context == "DONOR":
            for button in self.donor_workbench.mode_group.buttons():
                if button.property("mode") == mode:
                    button.setChecked(True)
                    break

    def undo(self) -> None:
        if self.document is not None and self.document.history.can_undo():
            self.document.undo()
            self._refresh_after_document_change()

    def redo(self) -> None:
        if self.document is not None and self.document.history.can_redo():
            self.document.redo()
            self._refresh_after_document_change()

    def run_command(self, mutate) -> bool:
        """Runs one GUI edit as exactly one authoring transaction against the
        current document (directive #19), then refreshes Tree/Canvas/
        Inspector/status while preserving selection (#1.3). A validation
        failure is already rolled back by AssemblyDocument.transaction()
        itself -- the document is byte-identical to before the call, so
        there's nothing to reload; a canvas reload here would also wipe any
        in-progress uncommitted overlay (e.g. the Donor Align ghost) as an
        unwanted side effect of a rejected edit. Just report it, non-modally
        (#22)."""
        if self.document is None:
            return False
        try:
            mutate(self.document, self.image_sources)
        except Exception as exc:
            self.statusBar().showMessage(f"Edit failed: {exc}", 6000)
            return False
        self._refresh_after_document_change()
        return True

    def _nudge_draw_order(self, *, direction: int = 0, to_extreme: int = 0) -> None:
        if len(self.selection_model.instance_ids) != 1:
            return
        instance_id = self.selection_model.instance_ids[0]
        self.run_command(
            lambda document, image_sources: nudge_draw_order(
                document, instance_id, direction=direction, to_extreme=to_extreme
            )
        )

    def _refresh_after_document_change(self) -> None:
        # Uses the same layers_dir/image_sources the document was displayed
        # with (set by _display_document), not a path recomputed from
        # bundle_path -- so this also works for a freshly imported or newly
        # created document that hasn't been saved yet.
        if self.document is None:
            return
        self._refresh_diagnostics()
        self.tree_dock.load_document(self.document, self.diagnostics)
        self.canvas.load_document(self.document, self._canvas_layers_dir, self._canvas_image_sources)
        self.session.last_render_ms = self.canvas.scene_model.last_render_ms
        self.inspector_dock.refresh(self.selection_model.instance_ids)
        # Keep whichever workbench is currently visible in sync too -- not
        # just the command that triggered this refresh, so a plain
        # undo/redo (which calls this directly, bypassing any one
        # workbench's own post-action refresh) stays correct as well.
        current = self.workbench.currentWidget()
        if current is self.harvest_workbench:
            self.harvest_workbench.refresh()
        elif current is self.variant_workbench:
            self.variant_workbench.refresh()
        elif current is self.donor_workbench:
            self.donor_workbench.refresh()
        elif current is self.rig_intent_workbench:
            self.rig_intent_workbench.refresh()
        elif current is self.bake_workbench:
            self.bake_workbench.refresh()
        self._update_status()

    def _update_status(self) -> None:
        if self.document is None:
            self.statusBar().showMessage("No Assembly Bundle open")
            return
        result = self.document.validate()
        state = "valid" if result.ok else f"{len(result.errors)} errors"
        warning_count = len(result.warnings) + len(self.import_warnings)
        self.statusBar().showMessage(
            f"{state.upper()}  |  {warning_count} warnings  |  "
            f"render: {self.session.last_render_ms:.1f} ms  |  "
            f"selected: {', '.join(self.selection_model.instance_ids) or 'none'}"
        )
