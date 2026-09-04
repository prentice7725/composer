"""Contextual Inspector -- read-only identity/provenance plus editable
Transform, Visibility and Opacity for the current single selection (C5-B).

Every edit commits through MainWindow.run_command, the same public core API
entry point the canvas gizmo uses (directive #19); the Inspector never
mutates the document directly. Numeric fields commit on editingFinished
(focus-out/Enter), not on every keystroke, so one field edit is one undo
step, matching the canvas gizmo's one-drag-one-transaction contract.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...slots import SLOT_VOCABULARY
from ..commands import (
    set_instance_opacity,
    set_instance_plane,
    set_instance_slot,
    set_instance_transform,
    set_instance_visible,
)
from ..diagnostics import provenance_text


class InspectorDock(QDockWidget):
    def __init__(self, selection_model, parent=None):
        super().__init__("Inspector", parent)
        self.setObjectName("inspectorDock")
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
        slot_box = QComboBox()
        slot_box.setEditable(True)
        slot_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        slot_box.addItems(SLOT_VOCABULARY)
        slot_box.setCurrentText(instance.slot)
        slot_box.setAccessibleName("Instance slot")
        slot_box.activated.connect(lambda _index, combo=slot_box: self._commit_slot(combo.currentText()))
        slot_box.lineEdit().editingFinished.connect(lambda combo=slot_box: self._commit_slot(combo.currentText()))
        self.form.addRow(QLabel("Slot"), slot_box)

        plane_box = QComboBox()
        plane_box.addItem("(default)", None)
        for plane in asset.planes if asset else []:
            plane_box.addItem(plane, plane)
        plane_index = plane_box.findData(instance.plane)
        plane_box.setCurrentIndex(plane_index if plane_index >= 0 else 0)
        plane_box.setAccessibleName("Instance plane")
        plane_box.activated.connect(
            lambda index, combo=plane_box: self._commit_plane(combo.itemData(index))
        )
        self.form.addRow(QLabel("Plane"), plane_box)
        self.form.addRow(QLabel("Draw order"), QLabel(str(instance.draw_order)))

        variant_sets = [
            vs_id
            for vs_id, variant_set in document.variant_sets.items()
            if instance_id in variant_set.get("members", [])
        ]
        if variant_sets:
            self._add_context_link("VariantSet", ", ".join(variant_sets), "VARIANTS")

        rig_intent = document.rig_intent or {}
        scope = rig_intent.get("deformation_scopes", {}).get(instance_id)
        attachments = [
            attachment_id
            for attachment_id, attachment in rig_intent.get("attachments", {}).items()
            if instance_id in {attachment.get("child"), attachment.get("target")}
        ]
        regions = [
            region_id
            for region_id, region in rig_intent.get("regions", {}).items()
            if region.get("target") == instance_id
        ]
        if scope or attachments:
            summary = scope or "attachment"
            if attachments:
                summary += f" · {', '.join(attachments)}"
            self._add_context_link("RigIntent", summary, "RIG INTENT")
        if regions:
            self._add_context_link("Secondary Region", ", ".join(regions), "RIG INTENT")

        provenance_data = asset.provenance if asset else {}
        if provenance_data.get("operation") == "donor_import":
            self._add_context_link("Donor", str(provenance_data.get("source_donor", "imported")), "DONOR")
        if provenance_data.get("operation") == "bake" or not asset or not asset.source_binding:
            self._add_context_link("Bake / Derived", "Derived layer" if provenance_data else "Unresolved source", "BAKE")

        window = self._main_window()
        diagnostics = (
            [
                diagnostic
                for diagnostic in getattr(window, "diagnostics", [])
                if diagnostic.target_id in {instance_id, instance.asset_ref}
            ]
            if window is not None
            else []
        )
        if diagnostics:
            warnings = QTextEdit()
            warnings.setReadOnly(True)
            warnings.setAccessibleName("Instance diagnostics")
            warnings.setPlainText("\n".join(f"[{item.severity}] {item.message}" for item in diagnostics))
            warnings.setMaximumHeight(110)
            self.form.addRow(QLabel("Warnings"), warnings)

        provenance = QTextEdit()
        provenance.setReadOnly(True)
        provenance.setAccessibleName("Instance provenance")
        provenance.setPlainText(provenance_text(document, instance_id))
        provenance.setMaximumHeight(150)
        self.form.addRow(QLabel("Provenance"), provenance)

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

    def _add_context_link(self, label: str, value: str, context: str) -> None:
        """Show a compact conditional section and route it to its workbench."""
        window = self._main_window()
        button = QPushButton(f"{value}  ·  Open {context.title()}")
        button.setAccessibleName(f"{label} details")
        button.setToolTip(f"Open the {context} workspace for this layer")
        if window is None:
            button.setEnabled(False)
        else:
            button.clicked.connect(lambda checked=False, target=context: window.set_context(target))
        self.form.addRow(QLabel(label), button)

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

    def _commit_slot(self, slot: str) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None or not slot:
            return
        document = getattr(window, "document", None)
        if document is not None and document.instances.get(instance_id, None) is not None:
            if document.instances[instance_id].slot == slot:
                return
        window.run_command(
            lambda document, image_sources: set_instance_slot(document, image_sources, instance_id, slot)
        )

    def _commit_plane(self, plane: str | None) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        document = getattr(window, "document", None)
        if document is not None and document.instances.get(instance_id, None) is not None:
            if document.instances[instance_id].plane == plane:
                return
        window.run_command(
            lambda document, image_sources: set_instance_plane(document, image_sources, instance_id, plane)
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

        # editingFinished can be emitted while QDoubleSpinBox is still
        # processing the Enter/focus event.  run_command refreshes the
        # Inspector synchronously, which destroys that editor underneath Qt
        # and can cause an access violation (especially for linked layers,
        # where the refresh also rebuilds multiple canvas bounds).  Commit on
        # the next event-loop turn so the editor's native event has returned.
        def commit() -> None:
            document = getattr(window, "document", None)
            if document is None or instance_id not in document.instances:
                return
            window.run_command(
                lambda document, image_sources: set_instance_transform(
                    document, image_sources, instance_id, **{field_name: value}
                )
            )

        QTimer.singleShot(0, commit)
