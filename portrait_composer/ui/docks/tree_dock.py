"""Assembly Tree dock; filtering never changes the shared selection."""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QLineEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..models.assembly_tree import AssemblyTreeFilter, AssemblyTreeModel, INSTANCE_ROLE


class TreeDock(QDockWidget):
    def __init__(self, selection_model, parent=None):
        super().__init__("Assembly Tree", parent)
        self.selection_model = selection_model
        self.model = AssemblyTreeModel(self)
        self.proxy = AssemblyTreeFilter(self)
        self.proxy.setSourceModel(self.model)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search layers, slots, sources")
        self.search.setAccessibleName("Assembly tree search")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.clicked.connect(self._clicked)
        self.tree.setAccessibleName("Assembly tree")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.search)
        layout.addWidget(self.tree)
        self.setWidget(body)
        selection_model.subscribe(self._refresh_selection)

    def load_document(self, document) -> None:
        self.model.load_document(document)
        self._refresh_selection(self.selection_model.instance_ids)

    def _clicked(self, proxy_index) -> None:
        source_index = self.proxy.mapToSource(proxy_index)
        instance_id = self.model.itemFromIndex(source_index).data(INSTANCE_ROLE)
        if instance_id:
            self.selection_model.select(str(instance_id))

    def _refresh_selection(self, selected_ids: list[str]) -> None:
        self.tree.clearSelection()
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            source = self.proxy.mapToSource(index)
            instance_id = self.model.itemFromIndex(source).data(INSTANCE_ROLE)
            if instance_id in selected_ids:
                self.tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
