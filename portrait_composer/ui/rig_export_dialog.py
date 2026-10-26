"""AutoRig export acceptance review dialog (C6-I)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from ..rig_bundle import validate_rig_export


class RigExportReviewDialog(QDialog):
    """Show the final Composer-owned export contract before writing files."""

    def __init__(self, document, image_sources: dict, parent=None, *, on_issue=None):
        super().__init__(parent)
        self.setWindowTitle("Review AutoRig Export")
        self.resize(620, 420)
        self.errors = validate_rig_export(document, image_sources)
        self._on_issue = on_issue

        visible_ids = [
            instance_id
            for instance_id in document.composition.get("draw_order", [])
            if instance_id in document.instances and document.instances[instance_id].visible
        ]
        plans = getattr(document, "bake_plans", {})
        donors = [
            asset_id
            for asset_id, asset in document.assets.items()
            if asset.provenance.get("operation") in {"donor_import", "donor_replace"}
        ]
        intent = document.rig_intent or {}
        self.warnings = []
        for source_id, source in document.sources.items():
            metadata = source.metadata or {}
            self.warnings.extend(
                f"Source {source_id}: {warning}"
                for warning in metadata.get("warnings", [])
                if isinstance(warning, str) and warning
            )
            validation = metadata.get("validation", {})
            if isinstance(validation, dict):
                self.warnings.extend(
                    f"Source {source_id}: producer validation {name} = {status}"
                    for name, status in validation.items()
                    if str(status).lower() not in {"pass", "ready", "ok"}
                )
            left_right = (metadata.get("derived", {}) or {}).get("left_right", {})
            if isinstance(left_right, dict) and left_right.get("status") == "computed":
                self.warnings.append(
                    f"Source {source_id}: left/right candidates use image-space geometry. "
                    "Adopted candidates become independent canonical layers; side is not anatomical identity"
                )
        self.warnings.append(
            "AutoRig exports separate layer meshes; full-body joints, IK, and walking/gait generation "
            "are outside this contract"
        )
        self.warnings = list(dict.fromkeys(self.warnings))
        checks = [
            f"Visible canonical layers: {len(visible_ids)}",
            f"Baked plans: {sum(plan.get('status') == 'BAKED' for plan in plans.values())}/{len(plans)}",
            f"Donor assets: {len(donors)}",
            f"Secondary regions: {len(intent.get('regions', {}))}",
            f"Attachments: {len(intent.get('attachments', {}))}",
            f"Warnings and limits: {len(self.warnings)}",
        ]
        title_text = "Export blocked" if self.errors else "Export ready with warnings" if self.warnings else "Export ready"
        title = QLabel(title_text)
        self.status_label = title
        title.setAccessibleName("AutoRig export status")
        title.setStyleSheet("font-weight: 700;")
        detail = QLabel(
            "Resolve the following issues before export."
            if self.errors
            else "Review source warnings and capability limits before export. Composer validates the bundle; "
            "AutoRig performs the separate runtime preflight."
        )
        detail.setWordWrap(True)

        self.list = QListWidget()
        self.list.setAccessibleName("AutoRig export preflight")
        for check in checks:
            self.list.addItem(f"[INFO] {check}")
        for error in self.errors:
            self.list.addItem(f"[BLOCK] {error}")
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, error)
        for warning in self.warnings:
            self.list.addItem(f"[WARN] {warning}")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        if not self.errors:
            export_button = buttons.addButton("Export Rig Bundle", QDialogButtonBox.ButtonRole.AcceptRole)
            export_button.setAccessibleName("Confirm AutoRig export")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addWidget(self.list)
        if self._on_issue is not None:
            self.go_to_issue_button = QPushButton("Go to selected issue")
            self.go_to_issue_button.setAccessibleName("Open the selected export issue in its editor")
            self.go_to_issue_button.setEnabled(False)
            self.list.currentItemChanged.connect(
                lambda current, _previous: self.go_to_issue_button.setEnabled(
                    current is not None and current.data(Qt.ItemDataRole.UserRole) is not None
                )
            )
            self.go_to_issue_button.clicked.connect(self._go_to_issue)
            layout.addWidget(self.go_to_issue_button)
        layout.addWidget(buttons)

    def _go_to_issue(self) -> None:
        item = self.list.currentItem()
        issue = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if issue is None or self._on_issue is None:
            return
        self.reject()
        self._on_issue(str(issue))

