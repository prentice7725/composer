"""C5-E Donor Align Workbench (directive #10, #29).

Alignment is always a direct canvas drag (move/scale/rotate the ghost via
CanvasScene.donor_ghost, see canvas/donor_align.py) -- this panel never
asks for typed coordinates. Metrics are read straight from
donors.check_drift()'s own reasons/metrics, refreshed on a short timer
while a ghost is loaded (drag updates live inside the canvas view, which
this panel doesn't get a signal for) -- no separate "AI alignment score"
is invented here, only what check_drift already reports.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...donors import check_drift, expression_donor_kind

MODES = ("composite", "target_only", "donor_only", "flicker", "difference")


def _target_info(main_window):
    document = main_window.document
    selected = main_window.selection_model.instance_ids
    if document is None or len(selected) != 1:
        return None
    instance_id = selected[0]
    instance = document.instances.get(instance_id)
    if instance is None:
        return None
    asset = document.assets.get(instance.asset_ref)
    scene = main_window.canvas.scene_model
    image_w, image_h = scene.image_size(instance_id)
    scaled_w = image_w * instance.transform.scale_x
    scaled_h = image_h * instance.transform.scale_y
    canvas = document.composition.get("canvas") or {}
    canvas_size = (
        canvas.get("width", scaled_w),
        canvas.get("height", scaled_h),
    )
    target_box = {"x": instance.transform.x, "y": instance.transform.y, "width": scaled_w, "height": scaled_h}
    return {
        "instance_id": instance_id,
        "semantic": asset.semantic if asset else instance.asset_ref,
        "roi": target_box,
        "canvas_size": canvas_size,
        "rotation": instance.transform.rotation,
        "transform": instance.transform.to_dict(),
        "slot": instance.slot,
        "anchor": (target_box["x"] + target_box["width"] / 2.0, target_box["y"] + target_box["height"] / 2.0),
    }


class DonorWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._donor_path: Path | None = None
        self._donor_image: Image.Image | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.import_button = QPushButton("Import Donor Image…")
        self.import_button.setAccessibleName("Import donor image")
        self.import_button.clicked.connect(self._pick_donor)
        top.addWidget(self.import_button)
        self.target_label = QLabel("Target: none selected")
        top.addWidget(self.target_label, 1)
        outer.addLayout(top)

        form = QFormLayout()
        self.semantic_field = QLineEdit()
        self.semantic_field.setAccessibleName("Donor semantic")
        self.semantic_field.textChanged.connect(self._semantic_changed)
        form.addRow("Semantic", self.semantic_field)
        self.import_mode = QComboBox()
        self.import_mode.addItem("Variant Member", "variant_member")
        self.import_mode.addItem("Replacement", "replacement")
        self.import_mode.addItem("Independent Layer", "independent_layer")
        self.import_mode.setCurrentIndex(self.import_mode.findData("independent_layer"))
        self.import_mode.setAccessibleName("Donor import mode")
        self.import_mode.setToolTip(
            "Expression-like donors default to a VariantSet member; choose Replacement or Independent Layer explicitly."
        )
        self.import_mode.activated.connect(lambda _index: setattr(self, "_import_mode_locked", True))
        self._import_mode_locked = False
        form.addRow("Import as", self.import_mode)
        outer.addLayout(form)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Preview"))
        self.mode_group = QButtonGroup(self)
        for mode in MODES:
            button = QRadioButton(mode.replace("_", " ").title())
            button.setProperty("mode", mode)
            button.setAccessibleName(f"Donor preview mode {mode}")
            if mode == "composite":
                button.setChecked(True)
            button.toggled.connect(self._mode_changed)
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        outer.addLayout(mode_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Ghost opacity"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(55)
        self.opacity_slider.setAccessibleName("Donor ghost opacity")
        self.opacity_slider.valueChanged.connect(self._opacity_changed)
        opacity_row.addWidget(self.opacity_slider, 1)
        outer.addLayout(opacity_row)

        self.metrics_label = QLabel("")
        self.metrics_label.setStyleSheet("font-family: monospace;")
        outer.addWidget(self.metrics_label)

        bottom = QHBoxLayout()
        self.allow_drift_box = QCheckBox("Allow drift override")
        self.allow_drift_box.setAccessibleName("Allow donor drift override")
        bottom.addWidget(self.allow_drift_box)
        bottom.addStretch(1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setAccessibleName("Clear donor ghost")
        self.clear_button.clicked.connect(self.clear_ghost)
        self.apply_button = QPushButton("Import")
        self.apply_button.setAccessibleName("Import donor")
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.clear_button)
        bottom.addWidget(self.apply_button)
        outer.addLayout(bottom)

        self._set_controls_enabled(False)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(120)
        self._metrics_timer.timeout.connect(self._refresh_metrics)

    def _semantic_changed(self, semantic: str) -> None:
        if not self._import_mode_locked and expression_donor_kind(semantic):
            self.import_mode.setCurrentIndex(self.import_mode.findData("variant_member"))

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.semantic_field, self.opacity_slider, self.allow_drift_box, self.apply_button, self.clear_button):
            widget.setEnabled(enabled)
        for button in self.mode_group.buttons():
            button.setEnabled(enabled)

    def refresh(self) -> None:
        info = _target_info(self.main_window)
        if info is None:
            self.target_label.setText("Target: select exactly one Tree layer")
        else:
            self.target_label.setText(f"Target: {info['semantic']} ({info['instance_id']})")
            if not self.semantic_field.text():
                self.semantic_field.setText(info["semantic"])
            self._semantic_changed(self.semantic_field.text())

    # -- import / clear ---------------------------------------------------
    def _pick_donor(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose donor image", "", "Images (*.png *.jpg *.jpeg *.webp);;All files (*)"
        )
        if not path:
            return
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            self.main_window.statusBar().showMessage(f"Could not open donor image: {exc}", 6000)
            return
        self._donor_path = Path(path)
        self._donor_image = image.convert("RGBA")

        info = _target_info(self.main_window)
        donor_w, donor_h = self._donor_image.size
        if info is not None and expression_donor_kind(self.semantic_field.text() or info["semantic"]):
            initial = dict(info["transform"])
        elif info is not None:
            target_box = info["roi"]
            center_x = target_box["x"] + target_box["width"] / 2.0
            center_y = target_box["y"] + target_box["height"] / 2.0
            initial = {
                "x": center_x - donor_w / 2.0,
                "y": center_y - donor_h / 2.0,
                "scale_x": 1.0,
                "scale_y": 1.0,
                "rotation": 0.0,
            }
        else:
            initial = {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}

        opacity = self.opacity_slider.value() / 100.0
        self.main_window.canvas.scene_model.donor_ghost.show(
            self._donor_image,
            transform=initial,
            opacity=opacity,
            target_roi=info["roi"] if info else None,
            target_rotation=info["rotation"] if info else 0.0,
        )
        self._set_controls_enabled(True)
        self._metrics_timer.start()
        self._refresh_metrics()

    def clear_ghost(self) -> None:
        self._donor_path = None
        self._donor_image = None
        self.main_window.canvas.scene_model.clear_donor_ghost()
        self._metrics_timer.stop()
        self._set_controls_enabled(False)
        self.metrics_label.setText("")

    # -- live controls ------------------------------------------------------
    def _opacity_changed(self, value: int) -> None:
        self.main_window.canvas.scene_model.donor_ghost.set_opacity(value / 100.0)

    def _mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        button = self.sender()
        mode = button.property("mode")
        self.main_window.canvas.scene_model.set_donor_preview_mode(mode)

    def _refresh_metrics(self) -> None:
        ghost = self.main_window.canvas.scene_model.donor_ghost
        if not ghost.active or self._donor_image is None:
            return
        info = _target_info(self.main_window)
        donor_w, donor_h = self._donor_image.size
        drift = check_drift(
            (donor_w, donor_h),
            {"x": 0, "y": 0, "width": donor_w, "height": donor_h},
            alignment=ghost.transform,
            target_roi=info["roi"] if info else None,
            target_size=info["canvas_size"] if info else None,
            target_rotation=info["rotation"] if info else 0.0,
        )
        self.metrics_label.setText(self._format_metrics(drift))

    @staticmethod
    def _format_metrics(drift) -> str:
        metrics = drift.metrics
        reasons = drift.reasons

        def mark(keyword: str) -> str:
            return "✗" if any(keyword in reason for reason in reasons) else "✓"

        lines = []
        if "center_delta_norm" in metrics:
            lines.append(f"Center drift   {metrics['center_delta_norm']:.3f}   {mark('center drift')}")
        if "scale_ratio" in metrics:
            sx, sy = metrics["scale_ratio"]
            mark_scale = mark("scale drift")
            lines.append(f"Scale X        {sx:.2f}    {mark_scale}")
            lines.append(f"Scale Y        {sy:.2f}    {mark_scale}")
        if "roi_overlap" in metrics:
            lines.append(f"ROI overlap    {metrics['roi_overlap']:.2f}")
        if "rotation_delta" in metrics:
            lines.append(f"Rotation       {metrics['rotation_delta']:.1f}°   {mark('rotation drift')}")
        if not lines:
            lines.append("Select a target layer to compute alignment metrics.")
        return "\n".join(lines)

    # -- commit -----------------------------------------------------------
    def _apply(self) -> None:
        if self._donor_path is None or self._donor_image is None:
            return
        semantic = self.semantic_field.text().strip()
        if not semantic:
            self.main_window.statusBar().showMessage("Donor semantic is required.", 5000)
            return
        info = _target_info(self.main_window)
        ghost = self.main_window.canvas.scene_model.donor_ghost
        alignment = dict(ghost.transform)
        donor_size = self._donor_image.size
        allow_drift = self.allow_drift_box.isChecked()
        target_roi = info["roi"] if info else None
        target_size = info["canvas_size"] if info else None
        target_rotation = info["rotation"] if info else 0.0
        donor_path = self._donor_path
        import_mode = self.import_mode.currentData() or "independent_layer"
        target_instance_id = info["instance_id"] if info and import_mode in {"variant_member", "replacement"} else None
        target_anchor = info["anchor"] if target_instance_id else None

        result_holder: dict = {}

        def commit(document, image_sources):
            from ..commands import import_donor_asset

            result_holder["result"] = import_donor_asset(
                document,
                image_sources,
                donor_path,
                semantic=semantic,
                donor_size=donor_size,
                alignment=alignment,
                target_roi=target_roi,
                target_size=target_size,
                target_rotation=target_rotation,
                allow_drift=allow_drift,
                import_mode=import_mode,
                target_instance_id=target_instance_id,
                target_anchor=target_anchor,
            )

        if self.main_window.run_command(commit):
            result = result_holder.get("result")
            self.clear_ghost()
            if result is not None:
                self.main_window.selection_model.select(result.instance_id)
                self.main_window.set_context("VARIANTS" if result.variant_set_id else "ASSEMBLE")
