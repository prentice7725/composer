"""C5-C Multi-Source Harvest Workbench (directive #8, #27).

Hover previews a candidate transiently on the canvas (never mutates the
document, directive #18); a click sets a local pending selection; Apply
commits exactly one authoring transaction through
MainWindow.apply_harvest_pick -> ui/commands.harvest_semantic. Candidates
only ever come from a bundle's canonical ``layers/`` (PortraitBundle.layers)
-- ``raw_layers/`` is never iterated here, matching directive #8.4.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

THUMBNAIL_SIZE = 96
MODES = ("target_only", "solo", "overlay", "composite", "flicker", "difference")


class _CandidateCard(QFrame):
    hovered = Signal(str, object, str)  # run_label, image_path, mode
    unhovered = Signal()
    picked = Signal(str)  # run_label

    def __init__(self, run_label: str, image_path: Path, *, is_committed: bool, get_mode, parent=None):
        super().__init__(parent)
        self.run_label = run_label
        self.image_path = image_path
        self._get_mode = get_mode
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Harvest candidate {run_label}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        thumb = QLabel()
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                THUMBNAIL_SIZE,
                THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        thumb.setPixmap(pixmap)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb)
        layout.addWidget(QLabel(run_label + ("  (current)" if is_committed else "")))
        self.set_pending(False)

    def set_pending(self, pending: bool) -> None:
        color = "#ffd166" if pending else "#3a3f4b"
        width = 2 if pending else 1
        self.setStyleSheet(f"QFrame {{ border: {width}px solid {color}; }}")

    def enterEvent(self, event) -> None:
        self.hovered.emit(self.run_label, self.image_path, self._get_mode())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.unhovered.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.run_label)
        super().mousePressEvent(event)


class HarvestWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._tag: str | None = None
        self._pending_run_label: str | None = None
        self._cards: list[_CandidateCard] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Semantic"))
        self.tag_selector = QComboBox()
        self.tag_selector.setAccessibleName("Harvest semantic selector")
        self.tag_selector.currentTextChanged.connect(self._select_tag)
        top.addWidget(self.tag_selector, 1)
        self.mode_group = QButtonGroup(self)
        for mode in MODES:
            button = QRadioButton(mode.capitalize())
            button.setProperty("mode", mode)
            button.setAccessibleName(f"Harvest preview mode {mode}")
            if mode == "composite":
                button.setChecked(True)
            self.mode_group.addButton(button)
            top.addWidget(button)
        outer.addLayout(top)

        self.strip_area = QScrollArea()
        self.strip_area.setWidgetResizable(True)
        self.strip_area.setFixedHeight(150)
        self.strip_body = QWidget()
        self.strip_layout = QHBoxLayout(self.strip_body)
        self.strip_layout.setContentsMargins(4, 4, 4, 4)
        self.strip_layout.addStretch(1)
        self.strip_area.setWidget(self.strip_body)
        outer.addWidget(self.strip_area)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label, 1)
        self.apply_button = QPushButton("Apply Harvest")
        self.apply_button.setAccessibleName("Apply harvest candidate")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.apply_button)
        outer.addLayout(bottom)

    def _current_mode(self) -> str:
        checked = self.mode_group.checkedButton()
        return checked.property("mode") if checked else "overlay"

    def refresh(self) -> None:
        pool = self.main_window.harvest_source_pool
        tags = sorted({layer.tag for bundle in pool.values() for layer in bundle.layers})
        self.tag_selector.blockSignals(True)
        previous = self.tag_selector.currentText()
        self.tag_selector.clear()
        self.tag_selector.addItems(tags)
        if previous in tags:
            self.tag_selector.setCurrentText(previous)
        self.tag_selector.blockSignals(False)
        self._select_tag(self.tag_selector.currentText())

    def _select_tag(self, tag: str) -> None:
        self._tag = tag or None
        self._pending_run_label = None
        self.apply_button.setEnabled(False)
        while self.strip_layout.count() > 1:
            item = self.strip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
        if not tag:
            self.status_label.setText("No candidates loaded -- use File → Import Portrait Runs…")
            return

        document = self.main_window.document
        committed_run = None
        if document is not None:
            asset = document.assets.get(tag)
            if asset is not None and asset.source_binding is not None:
                committed_run = asset.source_binding.source_id

        for run_label, bundle in self.main_window.harvest_source_pool.items():
            # Only ever iterate a bundle's canonical layers/ -- raw_layers/
            # is never a harvesting candidate (directive #8.4).
            layer = next((l for l in bundle.layers if l.tag == tag), None)
            if layer is None:
                continue
            card = _CandidateCard(
                run_label,
                bundle.layer_path(layer),
                is_committed=(run_label == committed_run),
                get_mode=self._current_mode,
            )
            card.hovered.connect(self._hover_candidate)
            card.unhovered.connect(self._unhover_candidate)
            card.picked.connect(self._pick_candidate)
            self.strip_layout.insertWidget(self.strip_layout.count() - 1, card)
            self._cards.append(card)
        self.status_label.setText(f"{tag} · {len(self._cards)} candidate(s)")

    def _hover_candidate(self, run_label: str, image_path: Path, mode: str) -> None:
        if self._tag is None:
            return
        self.main_window.canvas.scene_model.preview_harvest_candidate(self._tag, image_path, mode)

    def _unhover_candidate(self) -> None:
        self.main_window.canvas.scene_model.clear_transient_preview()

    def _pick_candidate(self, run_label: str) -> None:
        self._pending_run_label = run_label
        for card in self._cards:
            card.set_pending(card.run_label == run_label)
        self.apply_button.setEnabled(True)
        self.status_label.setText(f"{self._tag} · pending: {run_label} (Apply to commit)")

    def _apply(self) -> None:
        self.commit_pending()

    def commit_pending(self) -> None:
        if self._tag is None or self._pending_run_label is None:
            return
        self.main_window.apply_harvest_pick(self._tag, self._pending_run_label)
        self._pending_run_label = None
        self.refresh()

    def cancel_pending(self) -> None:
        self._pending_run_label = None
        for card in self._cards:
            card.set_pending(False)
        self.apply_button.setEnabled(False)
        self.main_window.canvas.scene_model.clear_transient_preview()
        if self._tag:
            self.status_label.setText(f"{self._tag} · pending selection cleared")
