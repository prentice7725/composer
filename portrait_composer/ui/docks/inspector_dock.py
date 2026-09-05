"""Contextual Inspector -- read-only identity/provenance plus editable
Transform, Visibility and Opacity for the current single selection (C5-B).

Every edit commits through MainWindow.run_command, the same public core API
entry point the canvas gizmo uses (directive #19); the Inspector never
mutates the document directly. Numeric fields commit on editingFinished
(focus-out/Enter), not on every keystroke, so one field edit is one undo
step, matching the canvas gizmo's one-drag-one-transaction contract.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QToolButton,
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
    add_instance_mask,
    add_instance_quad_warp,
    add_instance_color,
    update_instance_visual_op,
    paint_instance_mask,
    align_instance_to_target,
    fit_instance_to_target,
    reset_instance_masks,
    update_instance_mask,
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
        self._visual_ops: dict[str, dict] = {}
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

        self._add_visual_ops_controls(instance)

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

    def _add_visual_ops_controls(self, instance) -> None:
        """Compact non-destructive VisualOps controls."""
        self._quad_spins = []
        ops = list(instance.visual_ops)
        self._visual_ops = {str(op.get("id")): op for op in ops}
        op_list = QListWidget()
        op_list.setAccessibleName("Mask VisualOps")
        for op in ops:
            item = QListWidgetItem(f"{op.get('id')}  ·  {op.get('type')}")
            item.setData(32, op.get("id"))
            op_list.addItem(item)
        if ops:
            op_list.setCurrentRow(0)
        op_list.setMaximumHeight(88)
        self.form.addRow(QLabel("VisualOps stack"), op_list)

        add_button = QPushButton("Add Mask…")
        add_button.setAccessibleName("Add mask visual operation")
        add_button.clicked.connect(self._add_mask)
        quad_button = QPushButton("Add Quad Warp")
        quad_button.setAccessibleName("Add quad warp visual operation")
        quad_button.clicked.connect(lambda: self._add_quad_warp(instance))
        color_button = QPushButton("Add Color")
        color_button.setAccessibleName("Add color visual operation")
        color_button.clicked.connect(self._add_color)
        invert_button = QPushButton("Invert Selected Mask")
        invert_button.setAccessibleName("Invert selected mask")
        invert_button.clicked.connect(lambda: self._mask_action(op_list, "invert"))
        reset_button = QPushButton("Reset VisualOps")
        reset_button.setAccessibleName("Reset visual operations")
        reset_button.clicked.connect(self._reset_masks)
        self.form.addRow(add_button, quad_button)
        self.form.addRow(QLabel("Color"), color_button)
        self.form.addRow(QLabel("Mask actions"), invert_button)
        self.form.addRow(QLabel(""), reset_button)

        mask_ops = [op for op in ops if op.get("type") == "mask"]
        if mask_ops:
            brush_box = QWidget()
            brush_layout = QGridLayout(brush_box)
            mask_selector = QComboBox()
            for mask_op in mask_ops:
                mask_selector.addItem(str(mask_op.get("id")), str(mask_op.get("id")))
            mask_selector.setAccessibleName("Mask brush operation")
            brush_layout.addWidget(QLabel("Operation"), 0, 0)
            brush_layout.addWidget(mask_selector, 0, 1)
            mode_selector = QComboBox()
            mode_selector.addItem("Erase", "erase")
            mode_selector.addItem("Restore", "restore")
            mode_selector.setAccessibleName("Mask brush mode")
            brush_layout.addWidget(QLabel("Mode"), 1, 0)
            brush_layout.addWidget(mode_selector, 1, 1)
            radius = self._spin(1.0, 200.0, 1.0, 20.0)
            radius.setAccessibleName("Mask brush radius")
            brush_layout.addWidget(QLabel("Radius"), 2, 0)
            brush_layout.addWidget(radius, 2, 1)
            brush_button = QPushButton("Paint on Canvas")
            brush_button.setAccessibleName("Enable mask brush")
            brush_button.clicked.connect(
                lambda checked=False, selector=mask_selector, mode=mode_selector, spin=radius:
                self._enable_mask_brush(selector.currentData(), mode.currentData(), spin.value())
            )
            self.form.addRow(QLabel("Mask Brush"), brush_box)
            self.form.addRow(QLabel(""), brush_button)

        selected_op = ops[0] if ops else None
        feather = self._spin(0.0, 200.0, 0.5, float(selected_op.get("params", {}).get("feather", 0.0)) if selected_op and selected_op.get("type") == "mask" else 0.0)
        feather.setAccessibleName("Mask feather radius")
        feather.setEnabled(bool(selected_op and selected_op.get("type") == "mask"))
        feather.editingFinished.connect(lambda spin=feather, box=op_list: self._set_feather(box, spin.value()))
        self.form.addRow(QLabel("Feather"), feather)

        color_op = next((op for op in ops if op.get("type") == "color"), None)
        self._color_spins = []
        if color_op is not None:
            color_params = color_op.get("params", {})
            color_grid = QWidget()
            color_layout = QGridLayout(color_grid)
            for index, name in enumerate(("saturation", "brightness", "contrast")):
                spin = self._spin(0.0, 4.0, 0.05, float(color_params.get(name, 1.0)))
                spin.setAccessibleName(f"Color {name}")
                color_layout.addWidget(QLabel(name.title()), index, 0)
                color_layout.addWidget(spin, index, 1)
                self._color_spins.append(spin)
            update_color = QPushButton("Update Color")
            update_color.setAccessibleName("Update color visual operation")
            update_color.clicked.connect(lambda box=op_list: self._update_color(box))
            self.form.addRow(QLabel("Color VisualOp"), color_grid)
            self.form.addRow(QLabel(""), update_color)

        fit_box = QWidget()
        fit_layout = QHBoxLayout(fit_box)
        fit_layout.setContentsMargins(0, 0, 0, 0)
        for mode, label in (("width", "Fit Width"), ("height", "Fit Height"), ("bbox", "Fit Box")):
            fit_button = QPushButton(label)
            fit_button.setAccessibleName(label)
            fit_button.clicked.connect(lambda checked=False, value=mode: self._fit_instance(value))
            fit_layout.addWidget(fit_button)
        self.form.addRow(QLabel("Fit"), fit_box)

        anchor_button = QToolButton()
        anchor_button.setText("Align to Canvas")
        anchor_button.setAccessibleName("Alignment anchor menu")
        anchor_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        from PySide6.QtWidgets import QMenu

        anchor_menu = QMenu(anchor_button)
        for anchor_name in ("center", "top_left", "top", "top_right", "left", "right", "bottom_left", "bottom", "bottom_right"):
            action = anchor_menu.addAction(anchor_name.replace("_", " ").title())
            action.triggered.connect(lambda checked=False, value=anchor_name: self._align_instance(value))
        anchor_button.setMenu(anchor_menu)
        self.form.addRow(QLabel("Anchor"), anchor_button)

        quad_op = next((op for op in ops if op.get("type") == "quad_warp"), None)
        if quad_op is not None:
            quad_values = list(quad_op.get("params", {}).get("quad", []))
            grid = QWidget()
            grid_layout = QGridLayout(grid)
            self._quad_spins = []
            labels = ("TL x", "TL y", "TR x", "TR y", "BR x", "BR y", "BL x", "BL y")
            for index, label in enumerate(labels):
                spin = self._spin(-100000.0, 100000.0, 1.0, float(quad_values[index]))
                spin.setAccessibleName(f"Quad warp {label}")
                grid_layout.addWidget(QLabel(label), index // 2, (index % 2) * 2)
                grid_layout.addWidget(spin, index // 2, (index % 2) * 2 + 1)
                self._quad_spins.append(spin)
            update_quad = QPushButton("Update Quad Warp")
            update_quad.setAccessibleName("Update quad warp")
            update_quad.clicked.connect(lambda box=op_list: self._update_quad_warp(box))
            self.form.addRow(QLabel("Quad Warp"), grid)
            self.form.addRow(QLabel(""), update_quad)

    def _add_mask(self) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose Mask PNG", "", "Mask PNG (*.png);;All files (*)")
        if not path:
            return
        base = Path(path).stem or "mask"
        op_id = base
        index = 2
        document = getattr(window, "document", None)
        existing = {op.get("id") for op in document.instances[instance_id].visual_ops} if document else set()
        while op_id in existing:
            op_id = f"{base}_{index}"
            index += 1
        window.run_command(lambda document, image_sources: add_instance_mask(document, image_sources, instance_id, op_id=op_id, path=path))

    def _enable_mask_brush(self, op_id: str, mode: str, radius: float) -> None:
        window = self._main_window()
        if window is None or self._instance_id is None:
            return
        window.canvas.enable_mask_brush(self._instance_id, op_id, radius=radius, mode=mode)

    def _add_quad_warp(self, instance) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        image_w, image_h = window.canvas.scene_model.image_size(instance_id)
        quad = [0.0, 0.0, float(image_w), 0.0, float(image_w), float(image_h), 0.0, float(image_h)]
        existing = {op.get("id") for op in instance.visual_ops}
        op_id = "quad_warp"
        index = 2
        while op_id in existing:
            op_id = f"quad_warp_{index}"
            index += 1
        window.run_command(lambda document, image_sources: add_instance_quad_warp(document, image_sources, instance_id, op_id=op_id, quad=quad))

    def _add_color(self) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        document = getattr(window, "document", None)
        existing = {op.get("id") for op in document.instances[instance_id].visual_ops}
        op_id = "color"
        index = 2
        while op_id in existing:
            op_id = f"color_{index}"
            index += 1
        window.run_command(
            lambda document, image_sources: add_instance_color(
                document, image_sources, instance_id, op_id=op_id,
                saturation=1.0, brightness=1.0, contrast=1.0,
            )
        )

    def _fit_instance(self, mode: str) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        image_size = tuple(round(value) for value in window.canvas.scene_model.image_size(instance_id))
        window.run_command(lambda document, image_sources: fit_instance_to_target(document, image_sources, instance_id, mode=mode, image_size=image_size))

    def _align_instance(self, anchor: str) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None:
            return
        image_size = tuple(round(value) for value in window.canvas.scene_model.image_size(instance_id))
        window.run_command(lambda document, image_sources: align_instance_to_target(document, image_sources, instance_id, anchor=anchor, image_size=image_size))

    def _update_quad_warp(self, op_list) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None or not getattr(self, "_quad_spins", None):
            return
        op = next((item for item in self._visual_ops.values() if item.get("type") == "quad_warp"), None)
        if op is None:
            return
        op_id = op.get("id")
        quad = [spin.value() for spin in self._quad_spins]
        window.run_command(
            lambda document, image_sources: update_instance_visual_op(
                document, image_sources, instance_id, op_id=op_id, params={"quad": quad}
            )
        )

    def _update_color(self, op_list) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is None or instance_id is None or not getattr(self, "_color_spins", None):
            return
        op = next((item for item in self._visual_ops.values() if item.get("type") == "color"), None)
        if op is None:
            return
        params = {
            name: spin.value()
            for name, spin in zip(("saturation", "brightness", "contrast"), self._color_spins)
        }
        window.run_command(
            lambda document, image_sources: update_instance_visual_op(
                document, image_sources, instance_id, op_id=op.get("id"), params=params
            )
        )

    def _selected_mask_id(self, op_list) -> str | None:
        item = op_list.currentItem()
        return str(item.data(32)) if item is not None and item.data(32) else None

    def _mask_action(self, op_list, action: str) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        op_id = self._selected_mask_id(op_list)
        if window is None or instance_id is None or op_id is None:
            return
        document = getattr(window, "document", None)
        op = next((item for item in document.instances[instance_id].visual_ops if item.get("id") == op_id), None)
        if op is None or op.get("type") != "mask":
            return
        params = dict(op.get("params", {}))
        params["invert"] = not bool(params.get("invert", False))
        window.run_command(lambda document, image_sources: update_instance_mask(document, image_sources, instance_id, op_id=op_id, **params))

    def _set_feather(self, op_list, value: float) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        op_id = self._selected_mask_id(op_list)
        if window is None or instance_id is None or op_id is None:
            return
        document = getattr(window, "document", None)
        op = next((item for item in document.instances[instance_id].visual_ops if item.get("id") == op_id), None)
        if op is None:
            return
        params = dict(op.get("params", {}))
        params["feather"] = float(value)
        window.run_command(lambda document, image_sources: update_instance_mask(document, image_sources, instance_id, op_id=op_id, **params))

    def _reset_masks(self) -> None:
        window = self._main_window()
        instance_id = self._instance_id
        if window is not None and instance_id is not None:
            window.run_command(lambda document, image_sources: reset_instance_masks(document, image_sources, instance_id))

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
