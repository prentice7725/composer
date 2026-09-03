"""Read-only AssemblyDocument instance model for the Tree dock."""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel


INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 1


class AssemblyTreeModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Assembly"])

    def load_document(self, document) -> None:
        self.removeRows(0, self.rowCount())
        for instance_id in document.composition.get("draw_order", []):
            instance = document.instances.get(instance_id)
            if instance is None:
                continue
            asset = document.assets.get(instance.asset_ref)
            source = asset.source_binding.source_id if asset and asset.source_binding else "derived"
            visibility = "V" if instance.visible else "H"
            semantic = asset.semantic if asset else instance.asset_ref
            item = QStandardItem(f"{visibility}  {instance_id}  [{instance.slot}]  {source}")
            item.setData(instance_id, INSTANCE_ROLE)
            item.setToolTip(f"{semantic} · source {source} · draw order {instance.draw_order}")
            item.setEditable(False)
            self.appendRow(item)


class AssemblyTreeFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(0)
