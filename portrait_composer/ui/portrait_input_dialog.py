"""Small native dialog for selecting Portrait Bundle folders and ZIPs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QDialogButtonBox,
    QVBoxLayout,
)


class PortraitInputDialog(QDialog):
    def __init__(self, *, multiple: bool, parent=None):
        super().__init__(parent)
        self.multiple = multiple
        self.setWindowTitle("Import Portrait Runs" if multiple else "Import Portrait Bundle")
        self.resize(620, 360)

        title = QLabel("Choose a SeeThrough Portrait Bundle folder or ZIP archive.")
        title.setWordWrap(True)
        title.setAccessibleName("Portrait input instructions")
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Selected Portrait inputs")
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)

        add_folder = QPushButton("Add Portrait Folder…")
        add_folder.setAccessibleName("Add Portrait Bundle folder")
        add_folder.clicked.connect(self._add_folder)
        add_zip = QPushButton("Add ZIP…")
        add_zip.setAccessibleName("Add Portrait Bundle ZIP")
        add_zip.clicked.connect(self._add_zip)
        remove = QPushButton("Remove")
        remove.setAccessibleName("Remove selected Portrait input")
        remove.clicked.connect(self._remove_selected)
        actions = QHBoxLayout()
        actions.addWidget(add_folder)
        actions.addWidget(add_zip)
        actions.addStretch(1)
        actions.addWidget(remove)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Import Runs" if multiple else "Start Assembly"
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.list_widget)
        layout.addLayout(actions)
        layout.addWidget(self.buttons)
        self._update_buttons()

    @property
    def paths(self) -> list[Path]:
        return [Path(self.list_widget.item(i).data(0)) for i in range(self.list_widget.count())]

    def _add_path(self, path: str) -> None:
        if not path:
            return
        candidate = Path(path).resolve()
        if candidate in self.paths:
            return
        if not self.multiple:
            self.list_widget.clear()
        item = QListWidgetItem(str(candidate))
        item.setData(0, str(candidate))
        self.list_widget.addItem(item)
        self._update_buttons()

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Portrait Bundle folder")
        self._add_path(path)

    def _add_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Portrait Bundle ZIP",
            "",
            "Portrait Bundle archives (*.zip);;All files (*)",
        )
        self._add_path(path)

    def _remove_selected(self) -> None:
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._update_buttons()

    def _update_buttons(self) -> None:
        count = self.list_widget.count()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(count > 0)

    def _accept(self) -> None:
        if self.multiple and self.list_widget.count() < 2:
            QMessageBox.information(
                self,
                "Select more runs",
                "Import Portrait Runs needs at least two Portrait Bundle inputs.",
            )
            return
        self.accept()

