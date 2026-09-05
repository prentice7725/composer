"""Explicit source re-import/remap review dialog (C6-D)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..remap import AMBIGUOUS, EXACT_MATCH, ORPHANED, SEMANTIC_MATCH


class RemapReviewDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Source Remap")
        self.resize(760, 420)
        self.report = report
        self._choices: dict[str, QComboBox] = {}

        title = QLabel(
            "Exact and unique semantic matches are preselected. Choose a layer "
            "for ambiguous/orphaned assets; blank entries remain unchanged."
        )
        title.setWordWrap(True)
        self.table = QTableWidget(len(report.entries), 4)
        self.table.setHorizontalHeaderLabels(["Asset", "Status", "Candidates", "Manual choice"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Source remap review")

        for row, entry in enumerate(report.entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.asset_id))
            self.table.setItem(row, 1, QTableWidgetItem(entry.status))
            self.table.setItem(row, 2, QTableWidgetItem(", ".join(entry.candidates) or "—"))
            combo = QComboBox()
            combo.addItem("Leave unchanged", None)
            if entry.status in (EXACT_MATCH, SEMANTIC_MATCH):
                combo.addItem(entry.candidates[0], entry.candidates[0])
                combo.setCurrentIndex(1)
                combo.setEnabled(False)
            elif entry.status == AMBIGUOUS:
                for candidate in entry.candidates:
                    combo.addItem(candidate, candidate)
            elif entry.status == ORPHANED:
                combo.setEnabled(False)
            self.table.setCellWidget(row, 3, combo)
            self._choices[entry.asset_id] = combo

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Resolved")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    @property
    def manual_choices(self) -> dict[str, str]:
        return {
            asset_id: str(combo.currentData())
            for asset_id, combo in self._choices.items()
            if combo.currentData()
        }
