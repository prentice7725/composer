"""C5-F RigIntent / Secondary Region Workbench (directive #11, #12, #30).

Motion Permission and Attachment mode are plain-language authoring
controls (directive #11: no mesh/weight/solver vocabulary in this UI,
only tooltips describing what each scope/mode *means*). The
upper_torso_secondary region's qualitative Response/Strength/Locks are
edited here; its two_lobe *geometry* is edited directly on Canvas via
CanvasScene.region_edit (canvas/region_edit.py) -- this panel only shows
the region's Preflight status faithfully from core.

No stiffness/damping/spring-mass/solver-iteration field appears anywhere
in this module (directive #12.2's explicit prohibition) -- only
response_profile (qualitative) and author_strength (0..1).
"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...rig_intent import ATTACHMENT_MODES, DEFORMATION_SCOPES
from ...secondary_regions import PREFLIGHT_DEGRADED, PREFLIGHT_DISABLED, PREFLIGHT_READY, RESPONSE_PROFILES, UPPER_TORSO_SECONDARY, visual_preflight

SCOPE_TOOLTIPS = {
    "baked": "Rendered into a static baked layer; cannot move independently at runtime.",
    "rigid": "Moves as one rigid unit with its parent; no internal deformation.",
    "local": "May deform locally, within its own bounds only.",
    "independent": "Moves independently of every other layer.",
    "secondary": "Eligible for authored secondary (follow-through) motion.",
}
MODE_TOOLTIPS = {
    "weld": "Rigidly fused to its target; moves exactly with it.",
    "hinge": "Pivots around its target at a fixed point.",
    "free": "Follows its target loosely, with no fixed pivot.",
    "follow": "Trails its target's motion with a delay.",
}
PREFLIGHT_ICON = {PREFLIGHT_READY: "✓", PREFLIGHT_DEGRADED: "!", PREFLIGHT_DISABLED: "✗"}


def _label_for(document, instance_id: str) -> str:
    instance = document.instances.get(instance_id) if document else None
    asset = document.assets.get(instance.asset_ref) if document and instance is not None else None
    return asset.semantic if asset is not None else instance_id


def _starter_two_lobe_geometry(main_window, target_id: str) -> dict | None:
    """Return a deterministic starter pair positioned near existing topwear.

    The reference is chosen from visible topwear and uses its alpha bounds,
    so a baked/hidden source cannot collapse the calculation to CanvasScene's
    unknown-size fallback.  This is placement convenience for the editor,
    not an image/body-shape detector; AutoRig remains responsible for
    pixel-level deformation checks.
    """
    document = main_window.document
    scene = main_window.canvas.scene_model
    target = document.instances.get(target_id) if document is not None else None
    if target is None:
        return None

    def bounds(instance_id: str, *, visual_only: bool = False):
        instance = document.instances.get(instance_id)
        if instance is None:
            return None
        image_path = scene._resolve_image_path(instance_id)
        alpha_box = None
        if image_path is not None and image_path.exists():
            try:
                with Image.open(image_path) as image:
                    image_width, image_height = image.size
                    alpha_box = image.convert("RGBA").getchannel("A").getbbox()
            except (OSError, ValueError):
                image_width, image_height = scene.image_size(instance_id)
        else:
            image_width, image_height = scene.image_size(instance_id)
        if visual_only:
            if alpha_box is None:
                return None
        else:
            # The normalized region coordinate frame is always the complete
            # target image; only the reference garment uses alpha bounds.
            alpha_box = (0, 0, image_width, image_height)
        left, top, right, bottom = alpha_box
        width = (right - left) * instance.transform.scale_x
        height = (bottom - top) * instance.transform.scale_y
        if width <= 0 or height <= 0:
            return None
        return (
            instance.transform.x + left * instance.transform.scale_x,
            instance.transform.y + top * instance.transform.scale_y,
            width,
            height,
        )

    target_bounds = bounds(target_id)
    if target_bounds is None:
        return None

    topwear_id = None
    topwear_candidates = []
    for instance_id, instance in document.instances.items():
        if not instance.visible or instance.opacity <= 0:
            continue
        asset = document.assets.get(instance.asset_ref)
        semantic = asset.semantic.casefold() if asset is not None and isinstance(asset.semantic, str) else ""
        if semantic in {"topwear", "upper_torso", "topwear_with_arms"} or instance.slot in {
            "torso_back", "torso", "torso_front"
        }:
            topwear_candidates.append((instance_id, semantic))

    target_asset = document.assets.get(target.asset_ref)
    target_semantic = target_asset.semantic.casefold() if target_asset is not None and isinstance(target_asset.semantic, str) else ""
    if target.visible and target.opacity > 0 and target_semantic in {
        "topwear", "upper_torso", "topwear_with_arms"
    }:
        topwear_id = target_id
    else:
        priority = {"topwear_with_arms": 0, "topwear": 1, "upper_torso": 2}
        topwear_candidates.sort(key=lambda item: (priority.get(item[1], 3), item[0]))
        topwear_id = topwear_candidates[0][0] if topwear_candidates else None

    reference_bounds = bounds(topwear_id, visual_only=True) if topwear_id is not None else None
    if reference_bounds is None:
        reference_bounds = bounds(target_id, visual_only=True)
    if reference_bounds is None:
        reference_bounds = target_bounds
    target_x, target_y, target_width, target_height = target_bounds
    reference_x, reference_y, reference_width, reference_height = reference_bounds

    def normal_x(value: float) -> float:
        return max(0.02, min(0.98, (value - target_x) / target_width))

    def normal_y(value: float) -> float:
        return max(0.02, min(0.98, (value - target_y) / target_height))

    radius_x = max(0.04, min(0.24, reference_width * 0.18 / target_width))
    radius_y = max(0.04, min(0.20, reference_height * 0.16 / target_height))
    center_y = normal_y(reference_y + reference_height * 0.42)
    return {
        "kind": "two_lobe",
        "left": {
            "center": [normal_x(reference_x + reference_width * 0.38), center_y],
            "radius": [radius_x, radius_y],
        },
        "right": {
            "center": [normal_x(reference_x + reference_width * 0.62), center_y],
            "radius": [radius_x, radius_y],
        },
    }


class RigIntentWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self.target_label = QLabel("Select exactly one Tree layer to author RigIntent for it.")
        outer.addWidget(self.target_label)

        outer.addWidget(self._section_label("Motion Permission"))
        scope_row = QHBoxLayout()
        self.scope_group = QButtonGroup(self)
        self.scope_group.setExclusive(True)
        for scope in DEFORMATION_SCOPES:
            button = QRadioButton(scope.replace("_", " ").title())
            button.setProperty("scope", scope)
            button.setToolTip(SCOPE_TOOLTIPS[scope])
            button.setAccessibleName(f"Motion permission {scope}")
            button.toggled.connect(self._scope_toggled)
            self.scope_group.addButton(button)
            scope_row.addWidget(button)
        outer.addLayout(scope_row)

        outer.addWidget(self._section_label("Attachment"))
        form = QFormLayout()
        self.mode_selector = QComboBox()
        self.mode_selector.setAccessibleName("Attachment mode")
        for mode in ATTACHMENT_MODES:
            self.mode_selector.addItem(mode.title(), mode)
            self.mode_selector.setItemData(self.mode_selector.count() - 1, MODE_TOOLTIPS[mode], Qt.ItemDataRole.ToolTipRole)
        form.addRow("Mode", self.mode_selector)
        self.target_selector = QComboBox()
        self.target_selector.setAccessibleName("Attachment target")
        form.addRow("Target", self.target_selector)
        outer.addLayout(form)
        attach_row = QHBoxLayout()
        self.set_attachment_button = QPushButton("Set Attachment")
        self.set_attachment_button.setAccessibleName("Set attachment")
        self.set_attachment_button.clicked.connect(self._set_attachment)
        attach_row.addWidget(self.set_attachment_button)
        attach_row.addStretch(1)
        outer.addLayout(attach_row)
        self.attachment_list = QListWidget()
        self.attachment_list.setAccessibleName("Existing attachments")
        self.attachment_list.setMaximumHeight(70)
        outer.addWidget(self.attachment_list)
        remove_attachment_button = QPushButton("Remove Selected Attachment")
        remove_attachment_button.clicked.connect(self._remove_selected_attachment)
        outer.addWidget(remove_attachment_button)

        outer.addWidget(self._section_label("Upper Torso Secondary"))
        region_top = QHBoxLayout()
        self.add_region_button = QPushButton("Add Region (from selection)")
        self.add_region_button.setAccessibleName("Add upper torso secondary region")
        self.add_region_button.clicked.connect(self._add_region)
        self.remove_region_button = QPushButton("Remove Region")
        self.remove_region_button.setAccessibleName("Remove upper torso secondary region")
        self.remove_region_button.clicked.connect(self._remove_region)
        region_top.addWidget(self.add_region_button)
        region_top.addWidget(self.remove_region_button)
        outer.addLayout(region_top)
        self.region_hint = QLabel("L/R lobe size is linked; drag centers independently.")
        self.region_hint.setStyleSheet("color: #7a8296;")
        outer.addWidget(self.region_hint)

        self.preflight_label = QLabel("")
        outer.addWidget(self.preflight_label)

        response_row = QHBoxLayout()
        response_row.addWidget(QLabel("Response"))
        self.response_group = QButtonGroup(self)
        for profile in RESPONSE_PROFILES:
            button = QRadioButton(profile.replace("_", " ").title())
            button.setProperty("profile", profile)
            button.setAccessibleName(f"Response profile {profile}")
            button.toggled.connect(self._response_toggled)
            self.response_group.addButton(button)
            response_row.addWidget(button)
        outer.addLayout(response_row)

        region_form = QFormLayout()
        self.strength_spin = self._unit_spin(self._strength_changed)
        region_form.addRow("Strength", self.strength_spin)
        self.lock_spins: dict[str, QDoubleSpinBox] = {}
        for lock_name in ("center", "neckline", "shoulder"):
            spin = self._unit_spin(lambda value, name=lock_name: self._lock_changed(name, value))
            self.lock_spins[lock_name] = spin
            region_form.addRow(f"{lock_name.title()} lock", spin)
        outer.addLayout(region_form)
        outer.addStretch(1)

        self._region_exists = False

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        return label

    def _unit_spin(self, on_change) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setKeyboardTracking(False)
        spin.editingFinished.connect(lambda s=spin: on_change(s.value()))
        return spin

    # -- selection / target -------------------------------------------------
    def _selected_instance(self):
        selected = self.main_window.selection_model.instance_ids
        if len(selected) != 1 or self.main_window.document is None:
            return None
        return selected[0]

    def refresh(self) -> None:
        document = self.main_window.document
        instance_id = self._selected_instance()
        self._refresh_motion_permission(document, instance_id)
        self._refresh_attachment_controls(document, instance_id)
        self._refresh_region_section(document)

    def _refresh_motion_permission(self, document, instance_id) -> None:
        if instance_id is None:
            self.target_label.setText("Select exactly one Tree layer to author RigIntent for it.")
            for button in self.scope_group.buttons():
                button.setEnabled(False)
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            return
        self.target_label.setText(f"Target: {_label_for(document, instance_id)} ({instance_id})")
        current_scope = (document.rig_intent.get("deformation_scopes", {}) or {}).get(instance_id)
        for button in self.scope_group.buttons():
            button.setEnabled(True)
            button.blockSignals(True)
            button.setChecked(button.property("scope") == current_scope)
            button.blockSignals(False)

    def _refresh_attachment_controls(self, document, instance_id) -> None:
        self.target_selector.blockSignals(True)
        self.target_selector.clear()
        if document is not None:
            for other_id in document.instances:
                if other_id != instance_id:
                    self.target_selector.addItem(_label_for(document, other_id), other_id)
        self.target_selector.blockSignals(False)
        enabled = instance_id is not None and self.target_selector.count() > 0
        self.mode_selector.setEnabled(enabled)
        self.target_selector.setEnabled(enabled)
        self.set_attachment_button.setEnabled(enabled)

        self.attachment_list.clear()
        if document is None or instance_id is None:
            return
        attachments = (document.rig_intent or {}).get("attachments", {})
        for attachment_id, attachment in attachments.items():
            if instance_id in (attachment.get("child"), attachment.get("target")):
                child_label = _label_for(document, attachment["child"])
                target_label = _label_for(document, attachment["target"])
                item_text = f"{attachment_id}: {child_label} --{attachment['mode']}--> {target_label}"
                self.attachment_list.addItem(item_text)
                self.attachment_list.item(self.attachment_list.count() - 1).setData(Qt.ItemDataRole.UserRole, attachment_id)

    def _refresh_region_section(self, document) -> None:
        region = (document.rig_intent or {}).get("regions", {}).get(UPPER_TORSO_SECONDARY) if document else None
        self._region_exists = region is not None
        self.add_region_button.setEnabled(document is not None and not self._region_exists and self._selected_instance() is not None)
        self.remove_region_button.setEnabled(self._region_exists)
        for widget in (self.strength_spin, *self.lock_spins.values()):
            widget.setEnabled(self._region_exists)
        for button in self.response_group.buttons():
            button.setEnabled(self._region_exists)

        if not self._region_exists:
            self.preflight_label.setText("No upper_torso_secondary region authored yet.")
            self.main_window.canvas.scene_model.region_edit.clear()
            return

        report = visual_preflight(document, UPPER_TORSO_SECONDARY)
        icon = PREFLIGHT_ICON.get(report.status, "?")
        reason_text = "".join(f"\n  - {reason}" for reason in report.reasons)
        self.preflight_label.setText(f"{report.status} {icon}{reason_text}")

        self.strength_spin.blockSignals(True)
        self.strength_spin.setValue(region.get("author_strength", 0.9))
        self.strength_spin.blockSignals(False)
        for name, spin in self.lock_spins.items():
            spin.blockSignals(True)
            spin.setValue(region.get("locks", {}).get(name, 0.0))
            spin.blockSignals(False)
        current_profile = region.get("response_profile")
        for button in self.response_group.buttons():
            button.blockSignals(True)
            button.setChecked(button.property("profile") == current_profile)
            button.blockSignals(False)

        target = region.get("target")
        target_instance_id = target if target in document.instances else None
        if target_instance_id is not None:
            self.main_window.canvas.scene_model.region_edit.show(
                UPPER_TORSO_SECONDARY, target_instance_id, region["geometry"]
            )
        else:
            self.main_window.canvas.scene_model.region_edit.clear()

    # -- commands -----------------------------------------------------------
    def _scope_toggled(self, checked: bool) -> None:
        if not checked:
            return
        instance_id = self._selected_instance()
        button = self.sender()
        if instance_id is None:
            return
        from ..commands import set_deformation_scope

        scope = button.property("scope")
        self.main_window.run_command(
            lambda document, image_sources: set_deformation_scope(document, image_sources, instance_id, scope)
        )

    def _set_attachment(self) -> None:
        instance_id = self._selected_instance()
        target_id = self.target_selector.currentData()
        mode = self.mode_selector.currentData()
        if instance_id is None or target_id is None or mode is None:
            return
        from ..commands import set_rig_attachment

        attachment_id = f"{instance_id}__to__{target_id}"
        self.main_window.run_command(
            lambda document, image_sources: set_rig_attachment(
                document, image_sources, attachment_id, child=instance_id, target=target_id, mode=mode
            )
        )

    def _remove_selected_attachment(self) -> None:
        item = self.attachment_list.currentItem()
        if item is None:
            return
        attachment_id = item.data(Qt.ItemDataRole.UserRole)
        from ..commands import remove_rig_attachment

        self.main_window.run_command(
            lambda document, image_sources: remove_rig_attachment(document, image_sources, attachment_id)
        )

    def _add_region(self) -> None:
        instance_id = self._selected_instance()
        if instance_id is None:
            return
        from ..commands import add_secondary_region

        geometry = _starter_two_lobe_geometry(self.main_window, instance_id)
        self.main_window.run_command(
            lambda document, image_sources: add_secondary_region(
                document,
                image_sources,
                UPPER_TORSO_SECONDARY,
                target=instance_id,
                geometry=geometry,
            )
        )

    def _remove_region(self) -> None:
        from ..commands import remove_secondary_region

        self.main_window.run_command(
            lambda document, image_sources: remove_secondary_region(document, image_sources, UPPER_TORSO_SECONDARY)
        )

    def _response_toggled(self, checked: bool) -> None:
        if not checked or not self._region_exists:
            return
        button = self.sender()
        from ..commands import update_secondary_region

        profile = button.property("profile")
        self.main_window.run_command(
            lambda document, image_sources: update_secondary_region(
                document, image_sources, UPPER_TORSO_SECONDARY, response_profile=profile
            )
        )

    def _strength_changed(self, value: float) -> None:
        if not self._region_exists:
            return
        from ..commands import update_secondary_region

        self.main_window.run_command(
            lambda document, image_sources: update_secondary_region(
                document, image_sources, UPPER_TORSO_SECONDARY, author_strength=value
            )
        )

    def _lock_changed(self, name: str, value: float) -> None:
        if not self._region_exists:
            return
        from ..commands import update_secondary_region

        document = self.main_window.document
        region = (document.rig_intent or {}).get("regions", {}).get(UPPER_TORSO_SECONDARY) if document else None
        locks = dict(region.get("locks", {})) if region else {}
        locks[name] = value
        self.main_window.run_command(
            lambda document, image_sources: update_secondary_region(
                document, image_sources, UPPER_TORSO_SECONDARY, locks=locks
            )
        )
