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
META_ROLE = Qt.ItemDataRole.UserRole + 3

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
                variant_sets = [
                    vs_id
                    for vs_id, variant_set in document.variant_sets.items()
                    if instance_id in variant_set.get("members", [])
                ]
                rig_intent = document.rig_intent or {}
                scope = rig_intent.get("deformation_scopes", {}).get(instance_id)
                region_ids = [
                    region_id
                    for region_id, region in rig_intent.get("regions", {}).items()
                    if region.get("target") == instance_id
                ]
                linked = bool(instance.transform_link)
                derived = source == "derived" or (asset and asset.provenance.get("operation") == "bake")
                donor = bool(asset and asset.provenance.get("operation") == "donor_import")
                unresolved = asset is None or (not derived and asset.source_binding is None)
                hierarchy = _hierarchy_path(document, instance_id)
                badges = []
                if variant_sets:
                    badges.append("[VAR:" + ",".join(variant_sets) + "]")
                if linked:
                    badges.append("[LINK]")
                if scope or region_ids:
                    badges.append("[RIG]")
                if derived:
                    badges.append("[DERIVED]")
                if donor:
                    badges.append("[DONOR]")
                if unresolved:
                    badges.append("[UNRESOLVED]")
                badges.append(warning_badge.strip()) if warning_badge else None
                label = f"{hierarchy}{instance_id}  [{instance.slot}]  {source}"
                if badges:
                    label += "  " + " ".join(badges)
                item = QStandardItem(f"{visibility}  {label}")
                item.setData(instance_id, INSTANCE_ROLE)
                item.setData(warning_count, WARNING_ROLE)
                item.setData(
                    {
                        "semantic": semantic,
                        "source": source,
                        "variant_sets": variant_sets,
                        "rig": bool(scope or region_ids),
                        "derived": derived,
                        "hidden": not instance.visible,
                        "unresolved": unresolved,
                    },
                    META_ROLE,
                )
                item.setToolTip(
                    f"{semantic} · source {source} · draw order {instance.draw_order}"
                    + (f" · VariantSets: {', '.join(variant_sets)}" if variant_sets else "")
                    + (f" · RigIntent: {scope or 'secondary region'}" if scope or region_ids else "")
                )
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
        self.mode = "All"
        self.selected_source: str | None = None

    def set_filter_mode(self, mode: str) -> None:
        self.mode = mode or "All"
        self._refresh_filter()

    def set_selected_source(self, source: str | None) -> None:
        self.selected_source = source
        self._refresh_filter()

    def _refresh_filter(self) -> None:
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if self.mode == "All":
            return True
        model = self.sourceModel()
        item = model.itemFromIndex(model.index(source_row, 0, source_parent))
        metadata = item.data(META_ROLE) or {}
        return {
            "Selected Source": (
                self.selected_source is not None
                and metadata.get("source") == self.selected_source
            ),
            "Variants": bool(metadata.get("variant_sets")),
            "Warnings": bool(item.data(WARNING_ROLE)),
            "Rig-enabled": bool(metadata.get("rig")),
            "Derived": bool(metadata.get("derived")),
            "Hidden": bool(metadata.get("hidden")),
            "Unresolved": bool(metadata.get("unresolved")),
        }.get(self.mode, True)


def _hierarchy_path(document, instance_id: str) -> str:
    """Render hierarchy grouping as a readable prefix without merging the
    independent slot/link/variant/rig relationships into one model."""
    hierarchy = document.hierarchy or {}
    nodes = hierarchy.get("nodes", {})
    by_ref = {node.get("ref"): node_id for node_id, node in nodes.items() if node.get("ref")}
    node_id = by_ref.get(instance_id)
    labels = []
    seen = set()
    while node_id and node_id not in seen:
        seen.add(node_id)
        node = nodes.get(node_id, {})
        parent = node.get("parent")
        if parent:
            parent_node = nodes.get(parent, {})
            labels.append(parent_node.get("label") or parent)
        node_id = parent
    return (" / ".join(reversed(labels)) + " / ") if labels else ""
