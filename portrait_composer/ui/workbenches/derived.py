"""Producer Derivatives workbench.

Candidate images stay transient until an explicit Adopt or Reactivate action.
Adopted pixels live in the Assembly, so a saved derivative pair remains
available for preview, revert, and reactivation after the producer bundle
moves or the Assembly is reopened.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...derived import DerivedCandidate
from ..commands import adopt_derived_split, revert_derived_split


class _DerivedRow(QFrame):
    def __init__(
        self,
        workbench,
        source_bundle: str,
        semantic: str,
        candidates: list[DerivedCandidate],
        canonical_ids: list[str],
        preferred_canonical: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.workbench = workbench
        self.source_bundle = source_bundle
        self.semantic = semantic
        self.candidates = {candidate.member: candidate for candidate in candidates}
        self.preview_buttons: list[QPushButton] = []
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        controls = QHBoxLayout()
        title = QLabel(f"DERIVED · {semantic} · {source_bundle}")
        title.setToolTip(f"Producer source: {source_bundle}")
        header.addWidget(title)
        header.addStretch(1)
        for member in ("left", "right"):
            candidate = self.candidates.get(member)
            thumb = QLabel()
            thumb.setFixedSize(64, 64)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(str(candidate.path)) if candidate is not None else QPixmap()
            if not pixmap.isNull():
                thumb.setPixmap(
                    pixmap.scaled(
                        64,
                        64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            thumb.setToolTip(f"Geometric canvas {member} · {semantic}")
            controls.addWidget(thumb)
            button = QPushButton(member.upper())
            button.setAccessibleName(f"Preview {semantic} {member} derivative from {source_bundle}")
            button.setEnabled(candidate is not None and Path(candidate.path).is_file())
            button.clicked.connect(
                lambda _checked=False, c=candidate: workbench.preview(c, self.selected_canonical()) if c else None
            )
            self.preview_buttons.append(button)
            controls.addWidget(button)
        self.pair_preview_button = QPushButton("Preview Pair")
        self.pair_preview_button.setAccessibleName(f"Preview {semantic} left and right derivatives from {source_bundle}")
        self.pair_preview_button.clicked.connect(
            lambda: workbench.preview_pair(self.semantic, self.candidates, self.selected_canonical())
        )
        controls.addWidget(self.pair_preview_button)

        self.canonical_combo = QComboBox()
        self.canonical_combo.setAccessibleName(f"Canonical target for {semantic} from {source_bundle}")
        self.canonical_combo.addItem("Choose canonical layer…", "")
        for instance_id in canonical_ids:
            self.canonical_combo.addItem(workbench._canonical_label(instance_id), instance_id)
        if preferred_canonical and preferred_canonical in canonical_ids:
            self.canonical_combo.setCurrentIndex(self.canonical_combo.findData(preferred_canonical))
        elif len(canonical_ids) == 1:
            self.canonical_combo.setCurrentIndex(self.canonical_combo.findData(canonical_ids[0]))
        self.canonical_combo.currentIndexChanged.connect(self._update_state)
        controls.addWidget(self.canonical_combo, 1)

        self.state = QLabel("")
        self.state.setMinimumWidth(130)
        header.addWidget(self.state)
        self.adopt_button = QPushButton("Adopt Split")
        self.adopt_button.setAccessibleName(f"Adopt {semantic} derivative pair from {source_bundle}")
        self.adopt_button.clicked.connect(self._adopt)
        controls.addWidget(self.adopt_button)
        self.revert_button = QPushButton("Revert to Canonical")
        self.revert_button.setAccessibleName(f"Revert {semantic} derivative pair to canonical")
        self.revert_button.clicked.connect(self._revert)
        controls.addWidget(self.revert_button)
        layout.addLayout(header)
        layout.addLayout(controls)
        self._update_state()

    def selected_canonical(self) -> str | None:
        value = self.canonical_combo.currentData()
        return str(value) if value else None

    def _update_state(self, *_args) -> None:
        canonical_id = self.selected_canonical()
        pair_paths_available = set(self.candidates) == {"left", "right"} and all(
            Path(candidate.path).is_file() for candidate in self.candidates.values()
        )
        for member, button in zip(("left", "right"), self.preview_buttons):
            candidate = self.candidates.get(member)
            button.setEnabled(
                canonical_id is not None
                and candidate is not None
                and Path(candidate.path).is_file()
            )
        self.pair_preview_button.setEnabled(canonical_id is not None and pair_paths_available)
        if canonical_id is None:
            self.state.setText("Choose a canonical layer")
            self.adopt_button.setEnabled(False)
            self.revert_button.setEnabled(False)
            return
        pair = self.workbench._pair_for(self.source_bundle, self.semantic, canonical_id)
        paths_available = pair_paths_available
        if pair:
            if set(pair) != {"left", "right"}:
                self.state.setText("Saved pair incomplete")
                self.adopt_button.setEnabled(False)
                self.revert_button.setEnabled(False)
                return
            active = all(instance.visible for instance in pair.values())
            canonical = self.workbench.main_window.document.instances.get(canonical_id)
            active = active and canonical is not None and not canonical.visible
            if active:
                self.state.setText("In use")
                self.adopt_button.setText("Split Active")
                self.adopt_button.setEnabled(False)
                self.revert_button.setEnabled(True)
            else:
                self.state.setText("Saved · original restored")
                self.adopt_button.setText("Reactivate Split")
                self.adopt_button.setEnabled(paths_available)
                self.revert_button.setEnabled(False)
            return
        if paths_available:
            self.state.setText("Not adopted")
            self.adopt_button.setText("Adopt Split")
            self.adopt_button.setEnabled(True)
        else:
            self.state.setText("Source candidate unavailable")
            self.adopt_button.setText("Adopt Split")
            self.adopt_button.setEnabled(False)
        self.revert_button.setEnabled(False)

    def _adopt(self) -> None:
        canonical_id = self.selected_canonical()
        if canonical_id is not None:
            self.workbench.adopt(
                self.semantic,
                list(self.candidates.values()),
                source_bundle=self.source_bundle,
                canonical_instance_id=canonical_id,
            )

    def _revert(self) -> None:
        canonical_id = self.selected_canonical()
        if canonical_id is not None:
            self.workbench.revert(
                self.semantic,
                source_bundle=self.source_bundle,
                canonical_instance_id=canonical_id,
            )


class DerivedWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.rows: list[_DerivedRow] = []
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Producer Derivatives"))
        hint = QLabel(
            "Optional producer candidates · left/right means geometric canvas sides. "
            "Preview is transient; Adopt explicitly replaces the selected canonical layer."
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

    def _canonical_ids(self, semantic: str) -> list[str]:
        document = self.main_window.document
        if document is None:
            return []
        return [
            instance_id
            for instance_id, instance in document.instances.items()
            if (asset := document.assets.get(instance.asset_ref)) is not None
            and asset.semantic == semantic
            and asset.provenance.get("operation") != "adopt_producer_derivative"
        ]

    def _canonical_label(self, instance_id: str) -> str:
        document = self.main_window.document
        instance = document.instances.get(instance_id) if document else None
        asset = document.assets.get(instance.asset_ref) if document and instance else None
        source_id = asset.source_binding.source_id if asset and asset.source_binding else "derived"
        return f"{instance_id} · {source_id} · {instance.slot if instance else ''}"

    def _pair_for(self, source_bundle: str, semantic: str, canonical_instance_id: str) -> dict:
        document = self.main_window.document
        if document is None:
            return {}
        pair = {}
        for instance in document.instances.values():
            asset = document.assets.get(instance.asset_ref)
            provenance = asset.provenance if asset is not None else {}
            if (
                provenance.get("operation") == "adopt_producer_derivative"
                and provenance.get("source_bundle") == source_bundle
                and provenance.get("source_semantic") == semantic
                and provenance.get("canonical_instance") == canonical_instance_id
            ):
                member = provenance.get("member")
                if member in {"left", "right"}:
                    pair[member] = instance
        return pair

    def _candidate_groups(self) -> dict[tuple[str, str], dict[str, DerivedCandidate]]:
        groups: dict[tuple[str, str], dict[str, DerivedCandidate]] = defaultdict(dict)
        for bundle in self._bundles():
            for candidate in bundle.derived_candidates("left_right"):
                groups[(candidate.source_bundle, candidate.source_semantic)][candidate.member] = candidate

        # The source manifest metadata is saved with the Assembly. It lets the
        # workbench recover candidate paths when the original bundle is still
        # available, and show an unavailable row when the source has moved.
        document = self.main_window.document
        if document is not None:
            for source_id, source in document.sources.items():
                metadata = source.metadata if isinstance(source.metadata, dict) else {}
                derived = (metadata.get("derived") or {}).get("left_right", {})
                if not isinstance(derived, dict):
                    continue
                if derived.get("status") != "computed":
                    continue
                root = Path(source.path).resolve() if source.path else None
                paths = derived.get("paths")
                if not isinstance(paths, dict):
                    continue
                for semantic, entries in paths.items():
                    for member in ("left", "right"):
                        relative = entries.get(member) if isinstance(entries, dict) else None
                        if not isinstance(relative, str) or Path(relative).is_absolute():
                            continue
                        rel_path = Path(relative)
                        if any(part in {"", ".", ".."} for part in rel_path.parts):
                            continue
                        if root is None:
                            path = Path("__unavailable_source__") / rel_path
                        else:
                            path = (root / rel_path).resolve()
                            try:
                                path.relative_to(root)
                            except ValueError:
                                path = Path("__unavailable_source__") / rel_path
                        groups[(source_id, semantic)].setdefault(
                            member,
                            DerivedCandidate(semantic, "left_right", member, path, source_id),
                        )
        return groups

    def refresh(self) -> None:
        while self.body_layout.count() > 1:
            item = self.body_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = []
        candidates_by_source = self._candidate_groups()
        adopted_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
        document = self.main_window.document
        if document is not None:
            for instance in document.instances.values():
                asset = document.assets.get(instance.asset_ref)
                provenance = asset.provenance if asset is not None else {}
                if provenance.get("operation") != "adopt_producer_derivative":
                    continue
                key = (provenance.get("source_bundle", ""), provenance.get("source_semantic", ""))
                canonical_id = provenance.get("canonical_instance")
                if key[0] and key[1] and canonical_id:
                    adopted_groups[key].add(canonical_id)

        group_keys = sorted(set(candidates_by_source) | set(adopted_groups))
        for source_bundle, semantic in group_keys:
            key = (source_bundle, semantic)
            group_candidates = candidates_by_source.get(key, {})
            for canonical_id in sorted(adopted_groups.get(key, set())):
                pair = self._pair_for(source_bundle, semantic, canonical_id)
                saved_candidates = [
                    DerivedCandidate(
                        semantic,
                        "left_right",
                        member,
                        Path(self.main_window.image_sources.get(instance.id, "")),
                        source_bundle,
                    )
                    for member, instance in pair.items()
                ]
                row_candidates = saved_candidates if len(saved_candidates) == 2 else list(group_candidates.values())
                row = _DerivedRow(
                    self,
                    source_bundle,
                    semantic,
                    row_candidates,
                    [canonical_id] if canonical_id in self._canonical_ids(semantic) else [],
                    canonical_id,
                    self.body,
                )
                self.body_layout.insertWidget(self.body_layout.count() - 1, row)
                self.rows.append(row)

            # A producer candidate without an existing pair remains available
            # for explicit targeting, including when the Assembly contains
            # several same-semantic canonical instances.
            if not adopted_groups.get(key):
                row = _DerivedRow(
                    self,
                    source_bundle,
                    semantic,
                    list(group_candidates.values()),
                    self._canonical_ids(semantic),
                    None,
                    self.body,
                )
                self.body_layout.insertWidget(self.body_layout.count() - 1, row)
                self.rows.append(row)

        self.status.setText(
            f"{len(self.rows)} source/target option(s) · Adopt and Revert each change one undo step"
            if self.rows else "No producer left/right derivatives available."
        )

    def preview(self, candidate: DerivedCandidate, canonical_instance_id: str | None = None) -> None:
        if self.main_window.document is None:
            return
        self.main_window.canvas.scene_model.preview_harvest_candidate(
            candidate.source_semantic,
            candidate.path,
            "overlay",
            canonical_instance_id=canonical_instance_id,
        )

    def preview_pair(
        self,
        semantic: str,
        candidates: dict,
        canonical_instance_id: str | None = None,
    ) -> None:
        if self.main_window.document is None or set(candidates) != {"left", "right"}:
            return
        self.main_window.canvas.scene_model.preview_derived_pair(
            semantic,
            candidates["left"].path,
            candidates["right"].path,
            canonical_instance_id=canonical_instance_id,
        )

    def adopt(
        self,
        semantic: str,
        candidates: list,
        *,
        source_bundle: str,
        canonical_instance_id: str,
    ) -> None:
        if self.main_window.document is None:
            self.status.setText("Import a Portrait Bundle before adopting a derivative.")
            return
        if self.main_window.run_command(
            lambda document, image_sources: adopt_derived_split(
                document,
                image_sources,
                candidates,
                canonical_instance_id=canonical_instance_id,
            )
        ):
            self.status.setText(f"Adopted {semantic} from {source_bundle} for {canonical_instance_id}.")
            self.refresh()
        else:
            self.status.setText("Adoption failed. Review Diagnostics for the exact source or reference issue.")

    def revert(self, semantic: str, *, source_bundle: str, canonical_instance_id: str) -> None:
        if self.main_window.document is None:
            return
        if self.main_window.run_command(
            lambda document, image_sources: revert_derived_split(
                document,
                image_sources,
                semantic,
                source_bundle=source_bundle,
                canonical_instance_id=canonical_instance_id,
            )
        ):
            self.status.setText(f"Restored {canonical_instance_id}; derivative edits are preserved for reactivation.")
            self.refresh()
        else:
            self.status.setText("Revert was blocked. Review Diagnostics for the reference that must be resolved.")
