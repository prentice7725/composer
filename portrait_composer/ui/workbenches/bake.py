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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...bake import BLOCK, CAN_BAKE, WARN
from ...profiles import FULL_MOTION, PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile

PROFILES = (PORTRAIT_STATIC, PORTRAIT_RIG, FULL_MOTION)
VERDICT_TEXT = {CAN_BAKE: "CAN_BAKE ✓", WARN: "WARN !", BLOCK: "BLOCK ✗"}
PREVIEW_MODES = ("before", "after", "wipe", "flicker", "difference")


def _label_for(document, instance_id: str) -> str:
    instance = document.instances.get(instance_id) if document else None
    asset = document.assets.get(instance.asset_ref) if document and instance is not None else None
    return asset.semantic if asset is not None else instance_id


class _CandidateCard(QFrame):
    def __init__(self, main_window, candidate, profile: str, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.candidate = candidate
        self.profile = profile
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(f"Candidate: {candidate.label}"))
        verdict_label = QLabel(VERDICT_TEXT.get(candidate.analysis.verdict, candidate.analysis.verdict))
        verdict_label.setStyleSheet("font-weight: bold;")
        header.addWidget(verdict_label)
        header.addStretch(1)
        outer.addLayout(header)

        sources = QListWidget()
        sources.setAccessibleName(f"Bake sources for {candidate.label}")
        sources.setMaximumHeight(80)
        document = main_window.document
        for instance_id in candidate.instance_ids:
            item_text = f"☑ {_label_for(document, instance_id)} ({instance_id})"
            sources.addItem(item_text)
        outer.addWidget(sources)

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
            self.candidate.instance_ids, mode, self.wipe_slider.value() / 100.0
        )

    def _acknowledge_toggled(self, checked: bool) -> None:
        if self.candidate.analysis.verdict == WARN:
            self.apply_button.setEnabled(checked)

    def _apply(self) -> None:
        import tempfile
        from pathlib import Path

        from ..commands import bake_candidate

        derived_id = self.candidate.label
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
        outer.addLayout(top)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.cards_body = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_body)
        self.cards_layout.addStretch(1)
        outer.addWidget(self.cards_body)
        outer.addStretch(1)

    def _current_profile(self) -> str:
        checked = self.profile_group.checkedButton()
        return checked.property("profile") if checked else PORTRAIT_STATIC

    def _profile_changed(self, checked: bool) -> None:
        if checked:
            self.refresh()

    def refresh(self) -> None:
        document = self.main_window.document
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
        self.main_window.canvas.scene_model.clear_transient_preview()
        if document is None:
            self.status_label.setText("No document open.")
            return
        profile = self._current_profile()
        candidates = analyze_profile(document, profile)
        if not candidates:
            self.status_label.setText(f"{profile}: no bake candidates recommended.")
            return
        self.status_label.setText(f"{profile}: {len(candidates)} candidate(s)")
        for candidate in candidates:
            card = _CandidateCard(self.main_window, candidate, profile)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self._cards.append(card)

    def _zoom_100(self) -> None:
        self.main_window.canvas.resetTransform()
        self.main_window.session.canvas_zoom = 1.0
