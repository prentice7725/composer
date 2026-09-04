"""Diagnostics list and lightweight Assembly Status checklist for C5-H."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..diagnostics import Diagnostic


DIAGNOSTIC_ROLE = Qt.ItemDataRole.UserRole + 20
CHECKLIST_ROLE = Qt.ItemDataRole.UserRole + 21


class DiagnosticsDock(QDockWidget):
    def __init__(self, main_window, parent=None):
        super().__init__("Diagnostics / Assembly Status", parent)
        self.setObjectName("diagnosticsDock")
        self.main_window = main_window
        self.summary = QLabel("No Assembly Bundle open")
        self.summary.setAccessibleName("Diagnostics summary")
        self.checklist = QListWidget()
        self.checklist.setAccessibleName("Assembly status checklist")
        self.checklist.itemClicked.connect(self._checklist_clicked)
        self.list = QListWidget()
        self.list.setAccessibleName("Assembly diagnostics")
        self.list.itemClicked.connect(self._diagnostic_clicked)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel("ASSEMBLY STATUS"))
        layout.addWidget(self.checklist)
        layout.addWidget(QLabel("DIAGNOSTICS"))
        layout.addWidget(self.list)
        self.setWidget(body)

    def refresh(self, document, diagnostics: list[Diagnostic], session=None) -> None:
        self.checklist.clear()
        self.list.clear()
        if document is None:
            self.summary.setText("No Assembly Bundle open")
            return

        errors = sum(item.severity == "ERROR" for item in diagnostics)
        warnings = sum(item.severity == "WARN" for item in diagnostics)
        self.summary.setText(f"{errors} error(s) · {warnings} warning(s)")
        for label, state, context in self._checklist(document, diagnostics, session):
            prefix = "[OK]" if state == "ok" else "[WARN]" if state == "warn" else "[TODO]"
            item = QListWidgetItem(f"{prefix} {label}")
            item.setData(CHECKLIST_ROLE, context)
            self.checklist.addItem(item)

        if not diagnostics:
            self.list.addItem("[OK] No diagnostics")
        else:
            for diagnostic in diagnostics:
                item = QListWidgetItem(f"[{diagnostic.severity}] {diagnostic.label}: {diagnostic.message}")
                item.setData(DIAGNOSTIC_ROLE, diagnostic)
                self.list.addItem(item)

    @staticmethod
    def _checklist(document, diagnostics, session):
        errors = [item for item in diagnostics if item.severity == "ERROR"]
        variant_errors = [item for item in errors if "variant_set" in item.message or "expression" in item.message]
        rig_incomplete = not bool(document.rig_intent.get("deformation_scopes") or document.rig_intent.get("regions"))
        bake_analyzed = bool(getattr(session, "bake_analyzed", False))
        return (
            ("Sources imported", "ok" if document.sources else "todo", "ASSEMBLE"),
            ("Layers available", "ok" if document.instances else "todo", "ASSEMBLE"),
            ("Variants valid", "warn" if variant_errors else "ok", "VARIANTS"),
            ("RigIntent authored", "warn" if rig_incomplete else "ok", "RIG INTENT"),
            ("Bake analyzed", "ok" if bake_analyzed else "todo", "BAKE"),
            ("AutoRig compiled", "todo", "BAKE"),
        )

    def _diagnostic_clicked(self, item: QListWidgetItem) -> None:
        diagnostic = item.data(DIAGNOSTIC_ROLE)
        if isinstance(diagnostic, Diagnostic):
            self.main_window.focus_diagnostic(diagnostic)

    def _checklist_clicked(self, item: QListWidgetItem) -> None:
        context = item.data(CHECKLIST_ROLE)
        if context:
            self.main_window.set_context(context)
