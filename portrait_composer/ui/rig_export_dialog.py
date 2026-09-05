"""AutoRig export acceptance review dialog (C6-I)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

from ..rig_bundle import validate_rig_export


class RigExportReviewDialog(QDialog):
    """Show the final Composer-owned export contract before writing files."""

    def __init__(self, document, image_sources: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review AutoRig Export")
        self.resize(620, 420)
        self.errors = validate_rig_export(document, image_sources)

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
        checks = [
            f"Visible canonical layers: {len(visible_ids)}",
            f"Baked plans: {sum(plan.get('status') == 'BAKED' for plan in plans.values())}/{len(plans)}",
            f"Donor assets: {len(donors)}",
            f"Secondary regions: {len(intent.get('regions', {}))}",
            f"Attachments: {len(intent.get('attachments', {}))}",
        ]
        title = QLabel("Export blocked" if self.errors else "Export ready")
        title.setAccessibleName("AutoRig export status")
        title.setStyleSheet("font-weight: 700;")
        detail = QLabel(
            "Resolve the following issues before export."
            if self.errors
            else "Composer will write only canonical visible layers and rig-facing metadata."
        )
        detail.setWordWrap(True)

        self.list = QListWidget()
        self.list.setAccessibleName("AutoRig export preflight")
        for check in checks:
            self.list.addItem(f"[INFO] {check}")
        for error in self.errors:
            self.list.addItem(f"[BLOCK] {error}")

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
        layout.addWidget(buttons)

