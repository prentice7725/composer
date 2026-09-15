"""Producer Derivatives workbench.

The workbench is intentionally an explicit gate: producer output is shown as
previewable candidate imagery and is never inserted into the Assembly until
the user presses Adopt Split.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...derived import adopt_derived_split, revert_derived_split


class _DerivedRow(QFrame):
    def __init__(self, workbench, semantic: str, candidates: list, parent=None):
        super().__init__(parent)
        self.workbench = workbench
        self.semantic = semantic
        self.candidates = {candidate.member: candidate for candidate in candidates}
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel(f"DERIVED · {semantic}"))
        for member in ("left", "right"):
            candidate = self.candidates[member]
            thumb = QLabel()
            pixmap = QPixmap(str(candidate.path))
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            thumb.setToolTip(f"DERIVED · {semantic}.{member}")
            layout.addWidget(thumb)
            button = QPushButton(member.upper())
            button.setAccessibleName(f"Preview {semantic} {member} derivative")
            button.clicked.connect(lambda _checked=False, c=candidate: workbench.preview(c))
            layout.addWidget(button)
        pair = QPushButton("PAIR")
        pair.setAccessibleName(f"Preview {semantic} derivative pair")
        pair.clicked.connect(lambda: workbench.preview_pair(self.semantic, self.candidates))
        layout.addWidget(pair)
        adopt = QPushButton("Adopt Split")
        adopt.setAccessibleName(f"Adopt {semantic} producer split")
        adopt.clicked.connect(lambda: workbench.adopt(self.semantic, list(self.candidates.values())))
        layout.addWidget(adopt)
        revert = QPushButton("Revert to Canonical")
        revert.setAccessibleName(f"Revert {semantic} to canonical")
        revert.clicked.connect(lambda: workbench.revert(self.semantic))
        layout.addWidget(revert)
        layout.addStretch(1)


class DerivedWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.rows: list[_DerivedRow] = []
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Producer Derivatives"))
        hint = QLabel(
            "Optional producer candidates · geometric canvas left/right. "
            "Canonical layers remain unchanged until Adopt Split."
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self.status = QLabel("")
        outer.addWidget(self.status)

    def _bundles(self) -> list:
        return list(getattr(self.main_window, "producer_bundle_pool", {}).values())

    def refresh(self) -> None:
        while self.body_layout.count() > 1:
            item = self.body_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = []
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for bundle in self._bundles():
            for candidate in bundle.derived_candidates("left_right"):
                groups[(candidate.source_bundle, candidate.source_semantic)].append(candidate)
        for (_source, semantic), candidates in sorted(groups.items()):
            by_member = {candidate.member: candidate for candidate in candidates}
            if set(by_member) != {"left", "right"}:
                continue
            row = _DerivedRow(self, semantic, [by_member["left"], by_member["right"]], self.body)
            self.body_layout.insertWidget(self.body_layout.count() - 1, row)
            self.rows.append(row)
        self.status.setText(
            f"{len(self.rows)} split candidate(s) · Adopt is explicit; no automatic mutation"
            if self.rows else "No producer left/right derivatives available."
        )

    def preview(self, candidate) -> None:
        if self.main_window.document is None:
            return
        self.main_window.canvas.scene_model.preview_harvest_candidate(
            candidate.source_semantic, candidate.path, "overlay"
        )

    def preview_pair(self, semantic: str, candidates: dict) -> None:
        if self.main_window.document is None:
            return
        self.main_window.canvas.scene_model.preview_derived_pair(
            semantic, candidates["left"].path, candidates["right"].path
        )

    def adopt(self, semantic: str, candidates: list) -> None:
        if self.main_window.document is None:
            self.status.setText("Import a Portrait Bundle before adopting a derivative.")
            return
        if self.main_window.run_command(
            lambda document, image_sources: adopt_derived_split(document, image_sources, candidates)
        ):
            self.status.setText(f"Adopted {semantic} geometric left/right split.")
            self.refresh()

    def revert(self, semantic: str) -> None:
        if self.main_window.document is None:
            return
        if self.main_window.run_command(
            lambda document, image_sources: revert_derived_split(document, image_sources, semantic)
        ):
            self.status.setText(f"Restored canonical {semantic}; derivative provenance retained.")
            self.refresh()
