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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...bake import BLOCK, CAN_BAKE, WARN, analyze_bake
from ...instances import Transform
from ...profiles import BakeCandidate, FULL_MOTION, PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile

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
    semantics = {_label_for(document, instance_id) for instance_id in instance_ids}
    if not {"body_remainder", "handwear", "topwear"}.issubset(semantics):
        return list(instance_ids)
    priority = {"body_remainder": 0, "handwear": 1, "topwear": 2}
    original_position = {instance_id: index for index, instance_id in enumerate(instance_ids)}

    def key(instance_id: str) -> tuple[int, int]:
        return priority.get(_label_for(document, instance_id), 1000), original_position[instance_id]

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
        outer.addLayout(top)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.cards_body = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.cards_body, 1)
        self.main_window.selection_model.subscribe(lambda _ids: self._selection_changed())
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

    def _zoom_100(self) -> None:
        self.main_window.canvas.resetTransform()
        self.main_window.session.canvas_zoom = 1.0
