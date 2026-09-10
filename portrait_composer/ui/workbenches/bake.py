"""C5-G Bake Analysis / Preview Workbench (directive #13, #31).

analyze_profile() is read-only (never mutates -- verified structurally by
this module never importing anything that could write to the document
except bake_candidate, called only from _apply()). Before/After/Wipe/
Flicker/Difference all render through CanvasScene.preview_bake_candidate,
which itself only ever calls render_subset (the same compositor
apply_bake_plan uses) -- so what you preview is exactly what committing
would produce, never a second guess at it.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...bake import BLOCK, CAN_BAKE, WARN, analyze_bake
from ...bake_plan import PLAN_STATUSES
from ...instances import Transform
from ...profiles import BakeCandidate, FULL_MOTION, PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile
from ...rig_bundle import validate_rig_export
from ...seam_repair import BAKE_MODES, BAKE_PROFILES, SEAM_CLEANUP_MODES, normalize_seam_policy, resolve_bake_mode
from ..commands import analyze_logical_bake_plan, apply_logical_plan, bake_candidate, create_logical_bake_plan

PROFILES = (PORTRAIT_STATIC, PORTRAIT_RIG, FULL_MOTION)
VERDICT_TEXT = {CAN_BAKE: "CAN_BAKE ✓", WARN: "WARN !", BLOCK: "BLOCK ✗"}
PREVIEW_MODES = ("before", "after", "wipe", "flicker", "difference")


def _label_for(document, instance_id: str) -> str:
    instance = document.instances.get(instance_id) if document else None
    asset = document.assets.get(instance.asset_ref) if document and instance is not None else None
    return asset.semantic if asset is not None else instance_id


def _default_staging_order(main_window, instance_ids: list[str]) -> list[str]:
    """Return the deterministic initial order for a transient bake recipe."""
    document = main_window.document
    semantics = {_label_for(document, instance_id).lower() for instance_id in instance_ids}
    if not {"handwear", "topwear"}.issubset(semantics):
        return list(instance_ids)
    # Production torso composition is garment-only.  Handwear is placed
    # under topwear so an arm overlay cannot leave its colour across the
    # garment chest; body_remainder is never a source in this path.
    priority = {"handwear": 0, "topwear": 1}
    original_position = {instance_id: index for index, instance_id in enumerate(instance_ids)}

    def key(instance_id: str) -> tuple[int, int]:
        return priority.get(_label_for(document, instance_id).lower(), 1000), original_position[instance_id]

    return sorted(instance_ids, key=key)


def _unique_output_name(document, base: str) -> str:
    """Pick a readable default that cannot collide with an existing bake."""
    if base not in document.assets and f"{base}__instance" not in document.instances:
        return base
    index = 2
    while (
        f"{base}_{index}" in document.assets
        or f"{base}_{index}__instance" in document.instances
    ):
        index += 1
    return f"{base}_{index}"


def _infer_quick_result(document, instance_ids: list[str]) -> str | None:
    """Infer only the small, deterministic v0.1 Quick Bake vocabulary."""
    semantics = {_label_for(document, instance_id).lower() for instance_id in instance_ids}
    if "topwear" in semantics and ("handwear" in semantics or "sleeve" in semantics or "arm" in semantics):
        return "topwear_with_arms"
    if any("coat" in value for value in semantics):
        return "coat_full"
    return None


def _auto_torso_sources(document) -> list[str]:
    """Find the unambiguous visible topwear + handwear production pair."""
    if document is None:
        return []
    matches = {"topwear": [], "handwear": []}
    for instance_id in document.composition.get("draw_order", []):
        instance = document.instances.get(instance_id)
        if instance is None or not instance.visible or instance.opacity <= 0:
            continue
        semantic = _label_for(document, instance_id).lower()
        if semantic in matches:
            matches[semantic].append(instance_id)
    if len(matches["topwear"]) == 1 and len(matches["handwear"]) == 1:
        return [matches["handwear"][0], matches["topwear"][0]]
    return []


def _torso_plan_sources(document, instance_ids: list[str]) -> list[str]:
    """The simple torso plan is deliberately only garment + handwear."""
    allowed = {"topwear", "handwear"}
    return [
        instance_id for instance_id in instance_ids
        if _label_for(document, instance_id).lower() in allowed
    ]


class _CandidateCard(QFrame):
    def __init__(self, main_window, candidate, profile: str | None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.candidate = candidate
        self.profile = profile
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._staged_order = _default_staging_order(main_window, list(candidate.instance_ids))
        self._staged_transforms = {
            instance_id: Transform.from_dict(main_window.document.instances[instance_id].transform.to_dict())
            for instance_id in self._staged_order
        }

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(f"Candidate: {candidate.label}"))
        verdict_label = QLabel(VERDICT_TEXT.get(candidate.analysis.verdict, candidate.analysis.verdict))
        verdict_label.setStyleSheet("font-weight: bold;")
        header.addWidget(verdict_label)
        header.addStretch(1)
        outer.addLayout(header)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output Layer Name"))
        self.output_name = QLineEdit(_unique_output_name(main_window.document, candidate.label))
        self.output_name.setAccessibleName(f"Output layer name for {candidate.label}")
        self.output_name.setPlaceholderText("letters, numbers, _, -, .")
        self.output_name.setToolTip("This name becomes the derived layer ID and is kept in provenance")
        self.output_name.textChanged.connect(lambda _text: self._update_apply_enabled())
        output_row.addWidget(self.output_name, 1)
        outer.addLayout(output_row)

        seam_row = QHBoxLayout()
        seam_row.addWidget(QLabel("Bake Mode"))
        self.bake_mode = QComboBox()
        for value in BAKE_MODES:
            self.bake_mode.addItem(value.replace("_", " ").title(), value)
        self.bake_mode.setCurrentIndex(
            self.bake_mode.findData(resolve_bake_mode(candidate.label))
        )
        self.bake_mode.setAccessibleName(f"Bake mode for {candidate.label}")
        self.bake_mode.currentIndexChanged.connect(self._seam_mode_changed)
        seam_row.addWidget(self.bake_mode)
        seam_row.addWidget(QLabel("Seam Cleanup"))
        self.seam_cleanup = QComboBox()
        for value in SEAM_CLEANUP_MODES:
            self.seam_cleanup.addItem(value.title(), value)
        self.seam_cleanup.setAccessibleName(f"Seam cleanup for {candidate.label}")
        seam_row.addWidget(self.seam_cleanup)
        seam_row.addWidget(QLabel("Expand Under"))
        self.expand_under = QSpinBox()
        self.expand_under.setRange(0, 4)
        self.expand_under.setSuffix(" px")
        self.expand_under.setValue(1)
        self.expand_under.setAccessibleName(f"Under-layer expansion for {candidate.label}")
        seam_row.addWidget(self.expand_under)
        self.remove_internal_lines = QCheckBox("Remove Internal Lines")
        self.remove_internal_lines.setChecked(True)
        self.remove_internal_lines.setAccessibleName(f"Remove internal seam lines for {candidate.label}")
        seam_row.addWidget(self.remove_internal_lines)
        seam_row.addStretch(1)
        outer.addLayout(seam_row)

        # Advanced seam controls are still part of the recipe, so changing
        # them must immediately re-render the transient preview.
        advanced_row = QHBoxLayout()
        advanced_row.addWidget(QLabel("Contact Band"))
        self.contact_band = QSpinBox()
        self.contact_band.setRange(1, 4)
        self.contact_band.setSuffix(" px")
        self.contact_band.setAccessibleName(f"Contact band for {candidate.label}")
        advanced_row.addWidget(self.contact_band)
        advanced_row.addWidget(QLabel("Tone Blend"))
        self.tone_blend_width = QSpinBox()
        self.tone_blend_width.setRange(0, 2)
        self.tone_blend_width.setSuffix(" px")
        self.tone_blend_width.setAccessibleName(f"Tone blend width for {candidate.label}")
        advanced_row.addWidget(self.tone_blend_width)
        advanced_row.addWidget(QLabel("Alpha Blend"))
        self.alpha_blend_width = QSpinBox()
        self.alpha_blend_width.setRange(0, 2)
        self.alpha_blend_width.setSuffix(" px")
        self.alpha_blend_width.setAccessibleName(f"Alpha blend width for {candidate.label}")
        advanced_row.addWidget(self.alpha_blend_width)
        advanced_row.addStretch(1)
        outer.addLayout(advanced_row)

        self.ownership_rule = QComboBox()
        self.ownership_rule.addItem("None", None)
        for profile_name in BAKE_PROFILES:
            self.ownership_rule.addItem(profile_name, profile_name)
        default_rule = candidate.label if candidate.label in BAKE_PROFILES else None
        self.ownership_rule.setCurrentIndex(self.ownership_rule.findData(default_rule))
        self.ownership_rule.setAccessibleName(f"Ownership rule for {candidate.label}")
        ownership_row = QHBoxLayout()
        ownership_row.addWidget(QLabel("Ownership Rule"))
        ownership_row.addWidget(self.ownership_rule)
        ownership_row.addStretch(1)
        outer.addLayout(ownership_row)
        defaults = normalize_seam_policy(
            None,
            result_semantic=candidate.label,
            # Keep the seam controls ready for the semantic-merge mode even
            # when a generic candidate initially opens in Flatten mode.
            mode="semantic_merge",
        )
        self.seam_cleanup.setCurrentIndex(self.seam_cleanup.findData(defaults["cleanup"]))
        self.expand_under.setValue(defaults["expand_under"])
        self.remove_internal_lines.setChecked(defaults["remove_internal_lines"])
        self.contact_band.setValue(defaults["contact_band_px"])
        self.tone_blend_width.setValue(defaults["tone_blend_width"])
        self.alpha_blend_width.setValue(defaults["alpha_blend_width"])
        for control, signal in (
            (self.seam_cleanup, self.seam_cleanup.currentIndexChanged),
            (self.expand_under, self.expand_under.valueChanged),
            (self.remove_internal_lines, self.remove_internal_lines.stateChanged),
            (self.ownership_rule, self.ownership_rule.currentIndexChanged),
            (self.contact_band, self.contact_band.valueChanged),
            (self.tone_blend_width, self.tone_blend_width.valueChanged),
            (self.alpha_blend_width, self.alpha_blend_width.valueChanged),
        ):
            signal.connect(lambda *_args: self._seam_controls_changed())
        self._seam_mode_changed()

        outer.addWidget(QLabel("Sources"))
        self.sources = QListWidget()
        self.sources.setAccessibleName(f"Bake sources for {candidate.label}")
        self.sources.setMinimumHeight(80)
        self.sources.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sources.currentRowChanged.connect(self._source_changed)
        outer.addWidget(self.sources)

        source_actions = QHBoxLayout()
        self.move_up_button = QPushButton("↑")
        self.move_up_button.setAccessibleName(f"Move bake source up for {candidate.label}")
        self.move_up_button.setToolTip("Move selected bake source earlier in the transient composite")
        self.move_up_button.clicked.connect(lambda: self._move_source(-1))
        source_actions.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("↓")
        self.move_down_button.setAccessibleName(f"Move bake source down for {candidate.label}")
        self.move_down_button.setToolTip("Move selected bake source later in the transient composite")
        self.move_down_button.clicked.connect(lambda: self._move_source(1))
        source_actions.addWidget(self.move_down_button)
        self.edit_source_button = QPushButton("Edit Source")
        self.edit_source_button.setAccessibleName(f"Edit bake source transform for {candidate.label}")
        self.edit_source_button.clicked.connect(self._toggle_source_editor)
        source_actions.addWidget(self.edit_source_button)
        self.reset_source_button = QPushButton("Reset")
        self.reset_source_button.setAccessibleName(f"Reset bake source staging for {candidate.label}")
        self.reset_source_button.clicked.connect(self._reset_staging)
        source_actions.addWidget(self.reset_source_button)
        source_actions.addStretch(1)
        outer.addLayout(source_actions)

        self.source_editor = QWidget()
        editor_layout = QFormLayout(self.source_editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.source_editor_label = QLabel("Select a source to edit")
        editor_layout.addRow(QLabel("Source"), self.source_editor_label)
        self.source_fields: dict[str, QDoubleSpinBox] = {}
        for name, minimum, maximum, step in (
            ("x", -100000.0, 100000.0, 1.0),
            ("y", -100000.0, 100000.0, 1.0),
            ("scale_x", 0.01, 100.0, 0.1),
            ("scale_y", 0.01, 100.0, 0.1),
            ("rotation", -3600.0, 3600.0, 1.0),
        ):
            field = QDoubleSpinBox()
            field.setRange(minimum, maximum)
            field.setSingleStep(step)
            field.setDecimals(3)
            field.setKeyboardTracking(False)
            field.setAccessibleName(f"Bake source {name}")
            field.editingFinished.connect(
                lambda field_name=name, spin=field: self._commit_staged_transform(field_name, spin.value())
            )
            self.source_fields[name] = field
            editor_layout.addRow(QLabel(name), field)
        self.source_editor.setVisible(False)
        outer.addWidget(self.source_editor)
        self._rebuild_source_list()

        if candidate.analysis.reasons:
            reasons_label = QLabel("\n".join(candidate.analysis.reasons))
            reasons_label.setWordWrap(True)
            reasons_label.setStyleSheet("color: #e0a030;")
            outer.addWidget(reasons_label)

        preview_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        for mode in PREVIEW_MODES:
            button = QRadioButton(mode.title())
            button.setProperty("mode", mode)
            button.setAccessibleName(f"Bake preview {mode} for {candidate.label}")
            if mode == "before":
                button.setChecked(True)
            button.toggled.connect(self._mode_changed)
            self.mode_group.addButton(button)
            preview_row.addWidget(button)
        outer.addLayout(preview_row)

        self.wipe_slider = QSlider(Qt.Orientation.Horizontal)
        self.wipe_slider.setRange(0, 100)
        self.wipe_slider.setValue(50)
        self.wipe_slider.setAccessibleName(f"Bake wipe position for {candidate.label}")
        self.wipe_slider.valueChanged.connect(self._wipe_changed)
        self.wipe_slider.setEnabled(False)
        outer.addWidget(self.wipe_slider)

        bottom = QHBoxLayout()
        self.acknowledge_box = None
        if candidate.analysis.verdict == WARN:
            self.acknowledge_box = QCheckBox("Acknowledge warnings")
            self.acknowledge_box.setAccessibleName(f"Acknowledge bake warnings for {candidate.label}")
            self.acknowledge_box.toggled.connect(self._acknowledge_toggled)
            bottom.addWidget(self.acknowledge_box)
        bottom.addStretch(1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setAccessibleName(f"Apply bake for {candidate.label}")
        self.apply_button.setEnabled(candidate.analysis.verdict == CAN_BAKE)
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.apply_button)
        outer.addLayout(bottom)
        self._update_apply_enabled()

    def _output_name(self) -> str | None:
        name = self.output_name.text().strip()
        return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name) else None

    def _update_apply_enabled(self) -> None:
        allowed = self._output_name() is not None and self.candidate.analysis.verdict == CAN_BAKE
        if self.candidate.analysis.verdict == WARN:
            allowed = self._output_name() is not None and bool(self.acknowledge_box and self.acknowledge_box.isChecked())
        self.apply_button.setEnabled(allowed)

    def _rebuild_source_list(self, selected_id: str | None = None) -> None:
        selected_id = selected_id or (self._staged_order[0] if self._staged_order else None)
        self.sources.blockSignals(True)
        self.sources.clear()
        document = self.main_window.document
        selected_row = -1
        for row, instance_id in enumerate(self._staged_order):
            item = QListWidgetItem(f"☑ {_label_for(document, instance_id)} ({instance_id})")
            item.setData(Qt.ItemDataRole.UserRole, instance_id)
            self.sources.addItem(item)
            if instance_id == selected_id:
                selected_row = row
        if selected_row >= 0:
            self.sources.setCurrentRow(selected_row)
        self.sources.blockSignals(False)
        self._source_changed(self.sources.currentRow())

    def _selected_source_id(self) -> str | None:
        row = self.sources.currentRow()
        return self._staged_order[row] if 0 <= row < len(self._staged_order) else None

    def _source_changed(self, row: int) -> None:
        source_id = self._staged_order[row] if 0 <= row < len(self._staged_order) else None
        enabled = source_id is not None
        self.move_up_button.setEnabled(enabled and row > 0)
        self.move_down_button.setEnabled(enabled and row < len(self._staged_order) - 1)
        self.edit_source_button.setEnabled(enabled)
        self.reset_source_button.setEnabled(bool(self._staged_order))
        self.source_editor_label.setText(
            _label_for(self.main_window.document, source_id) if source_id else "Select a source to edit"
        )
        transform = self._staged_transforms.get(source_id) if source_id else None
        for name, field in self.source_fields.items():
            field.blockSignals(True)
            field.setEnabled(transform is not None)
            if transform is not None:
                field.setValue(getattr(transform, name))
            field.blockSignals(False)

    def _move_source(self, delta: int) -> None:
        row = self.sources.currentRow()
        target = row + delta
        if not (0 <= row < len(self._staged_order) and 0 <= target < len(self._staged_order)):
            return
        self._staged_order[row], self._staged_order[target] = self._staged_order[target], self._staged_order[row]
        self._rebuild_source_list(self._staged_order[target])
        self._update_preview_from_staging()

    def _toggle_source_editor(self) -> None:
        visible = not self.source_editor.isVisible()
        self.source_editor.setVisible(visible)
        self.edit_source_button.setText("Close Source Editor" if visible else "Edit Source")

    def _commit_staged_transform(self, field_name: str, value: float) -> None:
        source_id = self._selected_source_id()
        transform = self._staged_transforms.get(source_id) if source_id else None
        if transform is None:
            return
        setattr(transform, field_name, float(value))
        self._update_preview_from_staging()

    def _reset_staging(self) -> None:
        self._staged_order = _default_staging_order(self.main_window, list(self.candidate.instance_ids))
        self._staged_transforms = {
            instance_id: Transform.from_dict(self.main_window.document.instances[instance_id].transform.to_dict())
            for instance_id in self._staged_order
        }
        self._rebuild_source_list()
        self._update_preview_from_staging()

    def _staging_kwargs(self) -> dict:
        return {
            "ordered_instance_ids": list(self._staged_order),
            "transform_overrides": dict(self._staged_transforms),
        }

    def _seam_policy(self) -> dict:
        return normalize_seam_policy(
            {
                "cleanup": self.seam_cleanup.currentData(),
                "expand_under": self.expand_under.value(),
                "remove_internal_lines": self.remove_internal_lines.isChecked(),
                "contact_band_px": self.contact_band.value(),
                "tone_blend_width": self.tone_blend_width.value(),
                "alpha_blend_width": self.alpha_blend_width.value(),
                "ownership_rule": self.ownership_rule.currentData(),
            },
            result_semantic=self._output_name() or self.candidate.label,
            mode=self.bake_mode.currentData(),
        )

    def _seam_mode_changed(self) -> None:
        semantic_merge = self.bake_mode.currentData() == "semantic_merge"
        self.seam_cleanup.setEnabled(semantic_merge)
        self.expand_under.setEnabled(semantic_merge)
        self.remove_internal_lines.setEnabled(semantic_merge)
        self.ownership_rule.setEnabled(semantic_merge)
        if hasattr(self, "mode_group"):
            self._update_preview_from_staging()

    def _seam_controls_changed(self) -> None:
        if hasattr(self, "mode_group"):
            self._update_preview_from_staging()

    def _update_preview_from_staging(self) -> None:
        checked = next((button for button in self.mode_group.buttons() if button.isChecked()), None)
        if checked is not None:
            self._update_preview(checked.property("mode"))

    def _mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        mode = self.sender().property("mode")
        self.wipe_slider.setEnabled(mode == "wipe")
        self._update_preview(mode)

    def _wipe_changed(self, value: int) -> None:
        self._update_preview("wipe")

    def _update_preview(self, mode: str) -> None:
        self.main_window.canvas.scene_model.preview_bake_candidate(
            self.candidate.instance_ids,
            mode,
            self.wipe_slider.value() / 100.0,
            **self._staging_kwargs(),
            bake_mode=self.bake_mode.currentData(),
            seam_policy=self._seam_policy(),
        )

    def _acknowledge_toggled(self, checked: bool) -> None:
        if self.candidate.analysis.verdict == WARN:
            self._update_apply_enabled()

    def _apply(self) -> None:
        import tempfile
        from pathlib import Path

        from ..commands import bake_candidate

        derived_id = self._output_name()
        if derived_id is None:
            self.main_window.statusBar().showMessage(
                "Layer name must start with a letter or number and use only letters, numbers, _, -, or .",
                6000,
            )
            return
        work_dir = Path(tempfile.mkdtemp(prefix="portrait-composer-bake-"))
        candidate = self.candidate
        profile = self.profile
        result_holder: dict = {}

        def commit(document, image_sources):
            result_holder["result"] = bake_candidate(
                document,
                image_sources,
                candidate,
                derived_id=derived_id,
                semantic=derived_id,
                work_dir=work_dir,
                profile=profile,
                mode=self.bake_mode.currentData(),
                seam_policy=self._seam_policy(),
                **self._staging_kwargs(),
            )

        if self.main_window.run_command(commit):
            derived_instance_id, warnings = result_holder["result"]
            self.main_window.selection_model.select(derived_instance_id)
            message = f"Baked {candidate.label!r} into {derived_instance_id} -- provenance recorded."
            if warnings:
                message += f" ({len(warnings)} warning(s) carried over)"
            self.main_window.statusBar().showMessage(message, 8000)


class BakeWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._cards: list[_CandidateCard] = []
        self._manual_candidate: BakeCandidate | None = None
        self._workflow_mode = "advanced"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile"))
        self.profile_group = QButtonGroup(self)
        for profile in PROFILES:
            button = QRadioButton(profile)
            button.setProperty("profile", profile)
            button.setAccessibleName(f"Bake profile {profile}")
            if profile == PORTRAIT_STATIC:
                button.setChecked(True)
            button.toggled.connect(self._profile_changed)
            self.profile_group.addButton(button)
            top.addWidget(button)
        top.addStretch(1)
        zoom_button = QPushButton("100% Zoom")
        zoom_button.setAccessibleName("Bake preview 100 percent zoom")
        zoom_button.clicked.connect(self._zoom_100)
        top.addWidget(zoom_button)
        self.bake_selected_button = QPushButton("Bake Selected")
        self.bake_selected_button.setAccessibleName("Analyze selected layers for bake")
        self.bake_selected_button.setToolTip("Analyze the currently selected Tree layers as one bake candidate")
        self.bake_selected_button.clicked.connect(self._analyze_selected)
        top.addWidget(self.bake_selected_button)
        self.advanced_button = QPushButton("Advanced Options")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setAccessibleName("Show advanced bake options")
        self.advanced_button.clicked.connect(self._toggle_advanced)
        top.addWidget(self.advanced_button)
        outer.addLayout(top)

        workflow_panel = QWidget()
        workflow_row = QHBoxLayout(workflow_panel)
        workflow_row.addWidget(QLabel("Bake Workflow"))
        self.workflow_mode = QComboBox()
        self.workflow_mode.addItem("Simple", "simple")
        self.workflow_mode.addItem("Advanced", "advanced")
        self.workflow_mode.setCurrentIndex(self.workflow_mode.findData("advanced"))
        self.workflow_mode.setAccessibleName("Bake workflow mode")
        self.workflow_mode.currentIndexChanged.connect(self._workflow_mode_changed)
        workflow_row.addWidget(self.workflow_mode)
        workflow_row.addStretch(1)
        outer.addWidget(workflow_panel)
        self.workflow_panel = workflow_panel

        self.simple_board = QFrame()
        self.simple_board.setFrameShape(QFrame.Shape.StyledPanel)
        simple_layout = QHBoxLayout(self.simple_board)
        simple_layout.addWidget(QLabel("Sources"))
        self.simple_sources_label = QLabel("Select at least two layers")
        self.simple_sources_label.setMinimumWidth(220)
        simple_layout.addWidget(self.simple_sources_label)
        simple_layout.addWidget(QLabel("Result"))
        self.simple_result_combo = QComboBox()
        self.simple_result_combo.setEditable(True)
        self.simple_result_combo.addItem("Choose result semantic…", "")
        for semantic in ("topwear_with_arms", "body_with_sleeves", "coat_full"):
            self.simple_result_combo.addItem(semantic, semantic)
        self.simple_result_combo.setAccessibleName("Quick bake result semantic")
        simple_layout.addWidget(self.simple_result_combo)
        simple_layout.addWidget(QLabel("Seam Cleanup"))
        self.simple_cleanup_combo = QComboBox()
        self.simple_cleanup_combo.addItem("Auto", "auto")
        self.simple_cleanup_combo.addItem("Strong", "aggressive")
        self.simple_cleanup_combo.addItem("Off", "off")
        self.simple_cleanup_combo.setAccessibleName("Quick bake seam cleanup")
        simple_layout.addWidget(self.simple_cleanup_combo)
        self.simple_before_button = QPushButton("Before")
        self.simple_after_button = QPushButton("After")
        self.simple_before_button.clicked.connect(lambda: self._quick_preview("before"))
        self.simple_after_button.clicked.connect(lambda: self._quick_preview("after"))
        simple_layout.addWidget(self.simple_before_button)
        simple_layout.addWidget(self.simple_after_button)
        self.quick_bake_button = QPushButton("Bake for Rig")
        self.quick_bake_button.setAccessibleName("Quick bake selected layers")
        self.quick_bake_button.clicked.connect(self._quick_bake)
        simple_layout.addWidget(self.quick_bake_button)
        self.export_rig_button = QPushButton("Export Rig Bundle…")
        self.export_rig_button.setAccessibleName("Export rig bundle from prepare rig")
        self.export_rig_button.setToolTip("Review readiness and export the visible canonical layers to AutoRig")
        self.export_rig_button.clicked.connect(self.main_window.export_rig_bundle_dialog)
        simple_layout.addWidget(self.export_rig_button)
        outer.addWidget(self.simple_board)

        self.readiness_box = QFrame()
        self.readiness_box.setFrameShape(QFrame.Shape.StyledPanel)
        readiness_layout = QHBoxLayout(self.readiness_box)
        readiness_layout.addWidget(QLabel("Readiness"))
        self.readiness_labels = {}
        for key, title in (("torso", "Torso"), ("expressions", "Expressions"), ("autorig", "AutoRig Preflight")):
            label = QLabel(f"{title}: NEEDS REVIEW")
            label.setAccessibleName(f"Prepare Rig {key} readiness")
            self.readiness_labels[key] = label
            readiness_layout.addWidget(label)
        readiness_layout.addStretch(1)
        outer.addWidget(self.readiness_box)

        self.plan_box = QFrame()
        self.plan_box.setFrameShape(QFrame.Shape.StyledPanel)
        plan_layout = QHBoxLayout(self.plan_box)
        plan_layout.addWidget(QLabel("Bake Plan"))
        self.plan_id_edit = QLineEdit("torso_plan")
        self.plan_id_edit.setAccessibleName("Bake plan id")
        self.plan_id_edit.setPlaceholderText("plan id")
        plan_layout.addWidget(self.plan_id_edit)
        self.plan_result_edit = QLineEdit("topwear_with_arms")
        self.plan_result_edit.setAccessibleName("Bake plan result semantic")
        plan_layout.addWidget(self.plan_result_edit)
        self.plan_slot_edit = QLineEdit("torso")
        self.plan_slot_edit.setAccessibleName("Bake plan result slot")
        plan_layout.addWidget(self.plan_slot_edit)
        self.create_plan_button = QPushButton("Create Plan")
        self.create_plan_button.setAccessibleName("Create bake plan")
        self.create_plan_button.clicked.connect(self._create_plan)
        plan_layout.addWidget(self.create_plan_button)
        self.analyze_plan_button = QPushButton("Analyze Plan")
        self.analyze_plan_button.setAccessibleName("Analyze selected bake plan")
        self.analyze_plan_button.clicked.connect(self._analyze_plan)
        plan_layout.addWidget(self.analyze_plan_button)
        self.apply_plan_button = QPushButton("Apply Plan")
        self.apply_plan_button.setAccessibleName("Apply selected bake plan")
        self.apply_plan_button.clicked.connect(self._apply_plan)
        plan_layout.addWidget(self.apply_plan_button)
        outer.addWidget(self.plan_box)

        self.plan_options_widget = QWidget()
        plan_options = QHBoxLayout(self.plan_options_widget)
        plan_options.addWidget(QLabel("Mode"))
        self.plan_mode_combo = QComboBox()
        for value in BAKE_MODES:
            self.plan_mode_combo.addItem(value.replace("_", " ").title(), value)
        self.plan_mode_combo.setCurrentIndex(self.plan_mode_combo.findData("semantic_merge"))
        self.plan_mode_combo.setAccessibleName("Bake plan mode")
        plan_options.addWidget(self.plan_mode_combo)
        plan_options.addWidget(QLabel("Seam Cleanup"))
        self.plan_cleanup_combo = QComboBox()
        for value in SEAM_CLEANUP_MODES:
            self.plan_cleanup_combo.addItem(value.title(), value)
        self.plan_cleanup_combo.setCurrentIndex(self.plan_cleanup_combo.findData("auto"))
        self.plan_cleanup_combo.setAccessibleName("Bake plan seam cleanup")
        plan_options.addWidget(self.plan_cleanup_combo)
        plan_options.addWidget(QLabel("Expand Under"))
        self.plan_expand_under = QSpinBox()
        self.plan_expand_under.setRange(0, 4)
        self.plan_expand_under.setValue(3)
        self.plan_expand_under.setSuffix(" px")
        self.plan_expand_under.setAccessibleName("Bake plan under-layer expansion")
        plan_options.addWidget(self.plan_expand_under)
        self.plan_remove_internal_lines = QCheckBox("Remove Internal Lines")
        self.plan_remove_internal_lines.setChecked(True)
        self.plan_remove_internal_lines.setAccessibleName("Bake plan remove internal seam lines")
        plan_options.addWidget(self.plan_remove_internal_lines)
        plan_options.addWidget(QLabel("Contact Band"))
        self.plan_contact_band = QSpinBox()
        self.plan_contact_band.setRange(1, 4)
        self.plan_contact_band.setValue(2)
        self.plan_contact_band.setSuffix(" px")
        self.plan_contact_band.setAccessibleName("Bake plan contact band")
        plan_options.addWidget(self.plan_contact_band)
        plan_options.addWidget(QLabel("Tone Blend"))
        self.plan_tone_blend_width = QSpinBox()
        self.plan_tone_blend_width.setRange(0, 2)
        self.plan_tone_blend_width.setValue(1)
        self.plan_tone_blend_width.setSuffix(" px")
        self.plan_tone_blend_width.setAccessibleName("Bake plan tone blend width")
        plan_options.addWidget(self.plan_tone_blend_width)
        plan_options.addWidget(QLabel("Alpha Blend"))
        self.plan_alpha_blend_width = QSpinBox()
        self.plan_alpha_blend_width.setRange(0, 2)
        self.plan_alpha_blend_width.setValue(1)
        self.plan_alpha_blend_width.setSuffix(" px")
        self.plan_alpha_blend_width.setAccessibleName("Bake plan alpha blend width")
        plan_options.addWidget(self.plan_alpha_blend_width)
        plan_options.addStretch(1)
        outer.addWidget(self.plan_options_widget)

        self.plan_row_widget = QWidget()
        plan_row = QHBoxLayout(self.plan_row_widget)
        plan_row.addWidget(QLabel("Saved plans"))
        self.plan_list = QListWidget()
        self.plan_list.setAccessibleName("Saved bake plans")
        self.plan_list.setMaximumHeight(60)
        self.plan_list.currentTextChanged.connect(self._plan_selected)
        plan_row.addWidget(self.plan_list, 1)
        self.plan_status_label = QLabel("No plan selected")
        plan_row.addWidget(self.plan_status_label)
        outer.addWidget(self.plan_row_widget)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.cards_body = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.cards_body, 1)
        self.main_window.selection_model.subscribe(lambda _ids: self._selection_changed())
        self._set_workflow_mode("advanced")
        self._selection_changed()

    def _current_profile(self) -> str:
        checked = self.profile_group.checkedButton()
        return checked.property("profile") if checked else PORTRAIT_STATIC

    def _profile_changed(self, checked: bool) -> None:
        if checked:
            self.refresh()

    def refresh(self) -> None:
        document = self.main_window.document
        self.main_window.session.bake_analyzed = document is not None
        self._clear_cards()
        self._manual_candidate = None
        self._refresh_plan_list()
        self.main_window.canvas.scene_model.clear_transient_preview()
        if document is None:
            self.status_label.setText("No document open.")
            self._selection_changed()
            return
        profile = self._current_profile()
        candidates = analyze_profile(document, profile)
        if not candidates:
            self.status_label.setText(f"{profile}: no bake candidates recommended.")
            self._selection_changed()
            return
        self.status_label.setText(f"{profile}: {len(candidates)} candidate(s)")
        self._add_cards(candidates, profile)
        self._selection_changed()

    def _set_workflow_mode(self, mode: str) -> None:
        self._workflow_mode = mode
        simple = mode == "simple"
        self.workflow_panel.setVisible(not simple)
        self.advanced_button.setChecked(not simple)
        self.bake_selected_button.setVisible(not simple)
        self.simple_board.setVisible(simple)
        self.readiness_box.setVisible(simple)
        self.plan_box.setVisible(not simple)
        self.plan_options_widget.setVisible(not simple)
        self.plan_row_widget.setVisible(not simple)
        # Candidate cards remain constructed in Simple mode for backwards
        # compatible API/tests, but the user sees the compact quick workflow.
        self.cards_body.setVisible(not simple)
        self._update_simple_board()

    def _toggle_advanced(self, checked: bool) -> None:
        self.workflow_mode.setCurrentIndex(
            self.workflow_mode.findData("advanced" if checked else "simple")
        )

    def _workflow_mode_changed(self, _index: int) -> None:
        self._set_workflow_mode(self.workflow_mode.currentData() or "advanced")

    def _update_simple_board(self) -> None:
        document = self.main_window.document
        selected = list(self.main_window.selection_model.instance_ids)
        if document is None:
            self.simple_sources_label.setText("No document")
            self.quick_bake_button.setEnabled(False)
            self._update_readiness(None)
            return
        auto_sources = _auto_torso_sources(document)
        if auto_sources:
            index = self.simple_result_combo.findData("topwear_with_arms")
            if index >= 0:
                self.simple_result_combo.setCurrentIndex(index)
        labels = [_label_for(document, instance_id) for instance_id in (auto_sources or selected)]
        if auto_sources:
            self.simple_sources_label.setText("Auto sources: " + " + ".join(labels))
            self.simple_result_combo.setEnabled(False)
        else:
            self.simple_sources_label.setText(
                f"{len(labels)} selected: " + ", ".join(labels[:3]) + ("…" if len(labels) > 3 else "")
                if labels else "Select topwear + handwear"
            )
            self.simple_result_combo.setEnabled(True)
        inferred = _infer_quick_result(document, auto_sources or selected) if len(auto_sources or selected) >= 2 else None
        if inferred:
            index = self.simple_result_combo.findData(inferred)
            if index >= 0:
                self.simple_result_combo.setCurrentIndex(index)
        effective = self._simple_sources()
        if inferred == "topwear_with_arms" and len(effective) != len(selected) and not auto_sources:
            effective_labels = [_label_for(document, instance_id) for instance_id in effective]
            self.simple_sources_label.setText(
                f"{len(effective_labels)} torso sources: " + ", ".join(effective_labels)
            )
        semantic = self.simple_result_combo.currentText().strip()
        self.quick_bake_button.setEnabled(len(effective) >= 2 and bool(semantic))
        self._update_readiness(document, torso_sources=auto_sources)

    def _update_readiness(self, document, *, torso_sources: list[str] | None = None) -> None:
        if document is None:
            return
        torso_sources = torso_sources if torso_sources is not None else _auto_torso_sources(document)
        baked_torso = any(
            _label_for(document, instance_id) == "topwear_with_arms" and instance.visible
            for instance_id, instance in document.instances.items()
        ) or any(
            plan.get("status") == "BAKED" and plan.get("result_semantic") == "topwear_with_arms"
            for plan in document.bake_plans.values()
        )
        torso_status = "READY" if baked_torso else "NEEDS REVIEW" if torso_sources else "BLOCKED"
        slots = document.donor_slots or {}
        eyes = slots.get("eyes", {})
        mouth = slots.get("mouth", {})
        expression_status = "READY" if eyes.get("open") and eyes.get("closed") and mouth.get("closed") else "NEEDS REVIEW"
        errors = validate_rig_export(document, self.main_window.image_sources)
        autorig_status = "BLOCKED" if errors else "READY"
        values = {"torso": torso_status, "expressions": expression_status, "autorig": autorig_status}
        for key, label in self.readiness_labels.items():
            title = {"torso": "Torso", "expressions": "Expressions", "autorig": "AutoRig Preflight"}[key]
            label.setText(f"{title}: {values[key]}")
            color = {"READY": "#7fffa0", "NEEDS REVIEW": "#ffd166", "BLOCKED": "#ff7b7b"}[values[key]]
            label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _refresh_plan_list(self) -> None:
        document = self.main_window.document
        current = self.plan_list.currentItem().text() if self.plan_list.currentItem() else None
        self.plan_list.blockSignals(True)
        self.plan_list.clear()
        if document is not None:
            self.plan_list.addItems(sorted(document.bake_plans))
            if current in document.bake_plans:
                self.plan_list.setCurrentRow(sorted(document.bake_plans).index(current))
        self.plan_list.blockSignals(False)
        self._plan_selected(self.plan_list.currentItem().text() if self.plan_list.currentItem() else "")

    def _selected_plan_id(self) -> str | None:
        item = self.plan_list.currentItem()
        return item.text() if item is not None else None

    def _plan_selected(self, plan_id: str) -> None:
        document = self.main_window.document
        plan = document.bake_plans.get(plan_id) if document is not None and plan_id else None
        if plan is None:
            self.plan_status_label.setText("No plan selected")
            self.analyze_plan_button.setEnabled(False)
            self.apply_plan_button.setEnabled(False)
            return
        mode = plan.get("mode")
        if mode is not None and self.plan_mode_combo.findData(mode) >= 0:
            self.plan_mode_combo.setCurrentIndex(self.plan_mode_combo.findData(mode))
        policy = plan.get("seam_policy") or {}
        if policy.get("cleanup") is not None and self.plan_cleanup_combo.findData(policy["cleanup"]) >= 0:
            self.plan_cleanup_combo.setCurrentIndex(self.plan_cleanup_combo.findData(policy["cleanup"]))
        if policy.get("expand_under") is not None:
            self.plan_expand_under.setValue(int(policy["expand_under"]))
        if policy.get("remove_internal_lines") is not None:
            self.plan_remove_internal_lines.setChecked(bool(policy["remove_internal_lines"]))
        if policy.get("contact_band_px") is not None:
            self.plan_contact_band.setValue(int(policy["contact_band_px"]))
        if policy.get("tone_blend_width") is not None:
            self.plan_tone_blend_width.setValue(int(policy["tone_blend_width"]))
        if policy.get("alpha_blend_width") is not None:
            self.plan_alpha_blend_width.setValue(int(policy["alpha_blend_width"]))
        self.plan_status_label.setText(f"{plan_id}: {plan.get('status', '—')}")
        self.analyze_plan_button.setEnabled(True)
        self.apply_plan_button.setEnabled(plan.get("status") not in {"BLOCK", "BAKED"})

    def _create_plan(self) -> None:
        document = self.main_window.document
        sources = list(self.main_window.selection_model.instance_ids)
        if document is None or len(sources) < 2:
            self.status_label.setText("Select at least two Tree layers before creating a Bake Plan.")
            return
        plan_id = self.plan_id_edit.text().strip()
        semantic = self.plan_result_edit.text().strip()
        slot = self.plan_slot_edit.text().strip()
        if not plan_id or not semantic or not slot:
            self.status_label.setText("Plan id, result semantic, and result slot are required.")
            return
        if plan_id == "torso_plan" and semantic == "topwear_with_arms":
            sources = _torso_plan_sources(document, sources)
            torso_semantics = {_label_for(document, instance_id).lower() for instance_id in sources}
            if not {"topwear", "handwear"}.issubset(torso_semantics):
                self.status_label.setText("torso_plan requires topwear and handwear sources.")
                return
        mode = self.plan_mode_combo.currentData()
        seam_policy = normalize_seam_policy(
            {
                "cleanup": self.plan_cleanup_combo.currentData(),
                "expand_under": self.plan_expand_under.value(),
                "remove_internal_lines": self.plan_remove_internal_lines.isChecked(),
                "contact_band_px": self.plan_contact_band.value(),
                "tone_blend_width": self.plan_tone_blend_width.value(),
                "alpha_blend_width": self.plan_alpha_blend_width.value(),
                "ownership_rule": semantic if semantic in BAKE_PROFILES else None,
            },
            result_semantic=semantic,
            mode=mode,
        )
        if self.main_window.run_command(
            lambda doc, image_sources: create_logical_bake_plan(
                doc,
                image_sources,
                plan_id,
                sources=sources,
                result_semantic=semantic,
                result_slot=slot,
                mode=mode,
                seam_policy=seam_policy,
            )
        ):
            matches = self.plan_list.findItems(plan_id, Qt.MatchFlag.MatchExactly)
            if matches:
                self.plan_list.setCurrentRow(self.plan_list.row(matches[0]))

    def _analyze_plan(self) -> None:
        plan_id = self._selected_plan_id()
        if plan_id is None:
            return
        self.main_window.run_command(lambda document, image_sources: analyze_logical_bake_plan(document, image_sources, plan_id))

    def _apply_plan(self) -> None:
        plan_id = self._selected_plan_id()
        document = self.main_window.document
        if plan_id is None or document is None:
            return
        plan = document.bake_plans.get(plan_id, {})
        if plan.get("status") in {"BLOCK", "BAKED"}:
            return
        work_dir = Path(tempfile.mkdtemp(prefix="portrait-composer-plan-"))
        result_holder = {}

        def commit(doc, image_sources):
            result_holder["result"] = apply_logical_plan(doc, image_sources, plan_id, work_dir=work_dir, profile=self._current_profile())

        if self.main_window.run_command(commit):
            derived_id, warnings = result_holder["result"]
            self.main_window.selection_model.select(derived_id)
            self.main_window.statusBar().showMessage(
                f"Bake Plan {plan_id!r} applied as {derived_id} ({len(warnings)} warning(s))", 8000
            )

    def _clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []

    def _add_cards(self, candidates: list, profile: str | None) -> None:
        for candidate in candidates:
            card = _CandidateCard(self.main_window, candidate, profile)
            self.cards_layout.addWidget(card, 1)
            self._cards.append(card)

    def _selection_changed(self) -> None:
        selected = self.main_window.selection_model.instance_ids
        self.bake_selected_button.setEnabled(self.main_window.document is not None and len(selected) >= 2)
        self._update_simple_board()
        if self._manual_candidate is not None and selected != self._manual_candidate.instance_ids:
            self.refresh()

    def _analyze_selected(self) -> None:
        document = self.main_window.document
        selected = list(self.main_window.selection_model.instance_ids)
        if document is None or len(selected) < 2:
            self.status_label.setText("Select at least two Tree layers to bake as one candidate.")
            return
        analysis = analyze_bake(document, selected)
        self._manual_candidate = BakeCandidate("selected_layers", selected, analysis)
        self._clear_cards()
        self.main_window.canvas.scene_model.clear_transient_preview()
        self._add_cards([self._manual_candidate], None)
        self.status_label.setText(f"Selected layers: {len(selected)} · {analysis.verdict}")

    def _simple_policy(self, semantic: str) -> dict:
        cleanup = self.simple_cleanup_combo.currentData() or "auto"
        return normalize_seam_policy(
            {
                "cleanup": cleanup,
                "expand_under": 4 if cleanup == "aggressive" else 3,
                "remove_internal_lines": cleanup != "off",
                "contact_band_px": 3 if cleanup == "aggressive" else 2,
                "tone_blend_width": 1,
                "alpha_blend_width": 1,
                "ownership_rule": semantic if semantic in BAKE_PROFILES else None,
            },
            result_semantic=semantic,
            mode="semantic_merge",
        )

    def _simple_sources(self) -> list[str]:
        selected = list(self.main_window.selection_model.instance_ids)
        semantic = self.simple_result_combo.currentText().strip()
        if semantic == "topwear_with_arms":
            torso_sources = _auto_torso_sources(self.main_window.document)
            if not torso_sources:
                torso_sources = _torso_plan_sources(self.main_window.document, selected)
            if torso_sources:
                selected = torso_sources
        return _default_staging_order(self.main_window, selected)

    def _quick_preview(self, mode: str) -> None:
        document = self.main_window.document
        sources = self._simple_sources()
        semantic = self.simple_result_combo.currentText().strip()
        if document is None or len(sources) < 2 or not semantic:
            self.status_label.setText("Select at least two layers and choose a result semantic.")
            return
        analysis = analyze_bake(document, sources, mode="semantic_merge", seam_policy=self._simple_policy(semantic), result_semantic=semantic)
        if analysis.verdict == BLOCK:
            self.status_label.setText("Quick Bake blocked: " + " | ".join(analysis.block_reasons))
            return
        self.main_window.canvas.scene_model.preview_bake_candidate(
            sources,
            mode,
            0.5,
            ordered_instance_ids=sources,
            transform_overrides={},
            bake_mode="semantic_merge",
            seam_policy=self._simple_policy(semantic),
        )
        self.status_label.setText(f"Quick Bake preview {mode}: {analysis.verdict}")

    def _quick_bake(self) -> None:
        document = self.main_window.document
        sources = self._simple_sources()
        semantic = self.simple_result_combo.currentText().strip()
        if document is None or len(sources) < 2 or not semantic:
            self.status_label.setText("Select at least two layers and choose a result semantic.")
            return
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", semantic):
            self.status_label.setText("Result semantic must use letters, numbers, _, -, or .")
            return
        policy = self._simple_policy(semantic)
        analysis = analyze_bake(document, sources, mode="semantic_merge", seam_policy=policy, result_semantic=semantic)
        if analysis.verdict == BLOCK:
            self.status_label.setText("Quick Bake blocked: " + " | ".join(analysis.block_reasons))
            return
        candidate = BakeCandidate("quick_selected_layers", sources, analysis)
        derived_id = _unique_output_name(document, semantic)
        result_holder: dict = {}
        work_dir = Path(tempfile.mkdtemp(prefix="portrait-composer-quick-bake-"))

        def commit(doc, image_sources):
            result_holder["result"] = bake_candidate(
                doc, image_sources, candidate,
                derived_id=derived_id,
                semantic=semantic,
                work_dir=work_dir,
                profile=None,
                ordered_instance_ids=sources,
                transform_overrides={},
                mode="semantic_merge",
                seam_policy=policy,
            )

        if self.main_window.run_command(commit):
            derived_instance_id, warnings = result_holder["result"]
            self.main_window.selection_model.select(derived_instance_id)
            self.status_label.setText(
                f"Quick Bake applied as {derived_id} · {analysis.verdict}"
                + (f" · {len(warnings)} warning(s)" if warnings else "")
            )

    def _zoom_100(self) -> None:
        self.main_window.canvas.resetTransform()
        self.main_window.session.canvas_zoom = 1.0
