"""AssemblyDocument instance model for the Tree dock.

Rows carry a checkable visibility box (C5-B); everything else about a row
is still pure display, matching directive #5.1 ("Tree는 관계 표시를 하나로
합치지 않는다, 시각적 요약일 뿐"). Mutation happens only through TreeDock's
command calls -- load_document() blocks itemChanged while it rebuilds rows
so restoring checkbox state from the document never re-triggers a command.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel


INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 1
WARNING_ROLE = Qt.ItemDataRole.UserRole + 2

# Cross-widget drag source format (Tree -> VariantSet workbench drop
# targets, directive #9.2). A plain '\n'-joined list of instance ids --
# deliberately not Qt's own internal model-index MIME encoding, so any
# widget can decode it without reaching back into this model/proxy.
INSTANCE_MIME_TYPE = "application/x-portrait-composer-instance"


class AssemblyTreeModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Assembly"])

    def mimeTypes(self) -> list[str]:
        return [INSTANCE_MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData:
        instance_ids = []
        for index in indexes:
            if index.column() != 0:
                continue
            instance_id = self.itemFromIndex(index).data(INSTANCE_ROLE)
            if instance_id and instance_id not in instance_ids:
                instance_ids.append(instance_id)
        mime = QMimeData()
        mime.setData(INSTANCE_MIME_TYPE, "\n".join(instance_ids).encode("utf-8"))
        return mime

    def load_document(self, document, diagnostics=None) -> None:
        warning_counts: dict[str, int] = {}
        for diagnostic in diagnostics or []:
            if diagnostic.target_id and diagnostic.severity in {"WARN", "ERROR"}:
                warning_counts[diagnostic.target_id] = warning_counts.get(diagnostic.target_id, 0) + 1
        self.blockSignals(True)
        try:
            self.removeRows(0, self.rowCount())
            for instance_id in document.composition.get("draw_order", []):
                instance = document.instances.get(instance_id)
                if instance is None:
                    continue
                asset = document.assets.get(instance.asset_ref)
                source = asset.source_binding.source_id if asset and asset.source_binding else "derived"
                visibility = "V" if instance.visible else "H"
                semantic = asset.semantic if asset else instance.asset_ref
                warning_count = warning_counts.get(instance_id, 0) + warning_counts.get(instance.asset_ref, 0)
                warning_badge = f"  [WARN:{warning_count}]" if warning_count else ""
                item = QStandardItem(f"{visibility}  {instance_id}  [{instance.slot}]  {source}{warning_badge}")
                item.setData(instance_id, INSTANCE_ROLE)
                item.setData(warning_count, WARNING_ROLE)
                item.setToolTip(f"{semantic} · source {source} · draw order {instance.draw_order}")
                item.setEditable(False)
                item.setCheckable(True)
                item.setCheckState(Qt.CheckState.Checked if instance.visible else Qt.CheckState.Unchecked)
                self.appendRow(item)
        finally:
            self.blockSignals(False)


class AssemblyTreeFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(0)
