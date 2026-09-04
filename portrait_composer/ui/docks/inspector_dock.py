"""Contextual Inspector -- read-only identity/provenance plus editable
Transform, Visibility and Opacity for the current single selection (C5-B).

Every edit commits through MainWindow.run_command, the same public core API
entry point the canvas gizmo uses (directive #19); the Inspector never
mutates the document directly. Numeric fields commit on editingFinished
(focus-out/Enter), not on every keystroke, so one field edit is one undo
step, matching the canvas gizmo's one-drag-one-transaction contract.
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDockWidget, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..commands import set_instance_opacity, set_instance_transform, set_instance_visible


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
        self._instance_id: str | None = None
        selection_model.subscribe(self.refresh)

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)

    def _main_window(self):
        window = self.parent()
        return window if hasattr(window, "run_command") else None

    def refresh(self, selected_ids: list[str]) -> None:
        self._clear()
        document = getattr(self.parent(), "document", None)
        if document is None or not selected_ids:
            self._instance_id = None
            self.form.addRow(QLabel("Selection"), QLabel("Nothing selected"))
            return
        if len(selected_ids) > 1:
            self._instance_id = None
            self.form.addRow(QLabel("Selection"), QLabel(f"{len(selected_ids)} instances"))
            return
        instance_id = selected_ids[0]
        instance = document.instances.get(instance_id)
        if instance is None:
            self._instance_id = None
            return
        self._instance_id = instance_id
        asset = document.assets.get(instance.asset_ref)
        self.form.addRow(QLabel("Identity"), QLabel(instance_id))
        self.form.addRow(QLabel("Asset"), QLabel(instance.asset_ref))
        self.form.addRow(QLabel("Semantic"), QLabel(asset.semantic if asset else "—"))
        self.form.addRow(QLabel("Slot"), QLabel(instance.slot))
        self.form.addRow(QLabel("Plane"), QLabel(instance.plane or "—"))
        self.form.addRow(QLabel("Draw order"), QLabel(str(instance.draw_order)))

        visible_box = QCheckBox()
        visible_box.setAccessibleName("Instance visible")
        visible_box.setChecked(instance.visible)
        visible_box.toggled.connect(self._commit_visible)
        self.form.addRow(QLabel("Visible"), visible_box)

        opacity_box = self._spin(0.0, 1.0, 0.05, instance.opacity)
        opacity_box.setAccessibleName("Instance opacity")
        opacity_box.editingFinished.connect(lambda spin=opacity_box: self._commit_opacity(spin.value()))
        self.form.addRow(QLabel("Opacity"), opacity_box)

        transform = instance.transform
        for name, value, minimum, maximum in (
            ("x", transform.x, -100000.0, 100000.0),
            ("y", transform.y, -100000.0, 100000.0),
            ("scale_x", transform.scale_x, 0.01, 100.0),
            ("scale_y", transform.scale_y, 0.01, 100.0),
            ("rotation", transform.rotation, -3600.0, 3600.0),
        ):
            box = self._spin(minimum, maximum, 0.1 if "scale" in name else 1.0, value)
            box.setAccessibleName(f"Transform {name}")
            box.editingFinished.connect(lambda field_name=name, spin=box: self._commit_transform_field(field_name, spin.value()))
            self.form.addRow(QLabel(name), box)

    @staticmethod
    def _spin(minimum: float, maximum: float, step: float, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setDecimals(3)
        box.setKeyboardTracking(False)
        box.setValue(value)
        return box

    def _commit_visible(self, checked: bool) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        window.run_command(
            lambda document, image_sources: set_instance_visible(document, image_sources, instance_id, checked)
        )

    def _commit_opacity(self, value: float) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        window.run_command(
            lambda document, image_sources: set_instance_opacity(document, image_sources, instance_id, value)
        )

    def _commit_transform_field(self, field_name: str, value: float) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        window.run_command(
            lambda document, image_sources: set_instance_transform(
                document, image_sources, instance_id, **{field_name: value}
            )
        )
