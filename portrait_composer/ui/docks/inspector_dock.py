"""Contextual read-only Inspector for C5-A."""
from __future__ import annotations

from PySide6.QtWidgets import QDockWidget, QFormLayout, QLabel, QVBoxLayout, QWidget


class InspectorDock(QDockWidget):
    def __init__(self, selection_model, parent=None):
        super().__init__("Inspector", parent)
        self.selection_model = selection_model
        self.body = QWidget()
        self.layout = QVBoxLayout(self.body)
        self.form = QFormLayout()
        self.layout.addLayout(self.form)
        self.layout.addStretch(1)
        self.setWidget(self.body)
        selection_model.subscribe(self.refresh)

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)

    def refresh(self, selected_ids: list[str]) -> None:
        self._clear()
        document = getattr(self.parent(), "document", None)
        if document is None or not selected_ids:
            self.form.addRow(QLabel("Selection"), QLabel("Nothing selected"))
            return
        if len(selected_ids) > 1:
            self.form.addRow(QLabel("Selection"), QLabel(f"{len(selected_ids)} instances"))
            return
        instance_id = selected_ids[0]
        instance = document.instances.get(instance_id)
        if instance is None:
            return
        asset = document.assets.get(instance.asset_ref)
        self.form.addRow(QLabel("Identity"), QLabel(instance_id))
        self.form.addRow(QLabel("Asset"), QLabel(instance.asset_ref))
        self.form.addRow(QLabel("Semantic"), QLabel(asset.semantic if asset else "—"))
        self.form.addRow(QLabel("Slot"), QLabel(instance.slot))
        self.form.addRow(QLabel("Plane"), QLabel(instance.plane or "—"))
        self.form.addRow(QLabel("Draw order"), QLabel(str(instance.draw_order)))
        self.form.addRow(QLabel("Visible"), QLabel("Yes" if instance.visible else "No"))
        self.form.addRow(QLabel("Opacity"), QLabel(f"{instance.opacity:.2f}"))
        self.form.addRow(QLabel("Transform"), QLabel(str(instance.transform.to_dict())))
