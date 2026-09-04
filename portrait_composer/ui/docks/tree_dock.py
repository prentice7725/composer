"""Assembly Tree dock; filtering never changes the shared selection.

C5-B adds a per-row visibility checkbox and a draw-order context menu, both
committing through MainWindow.run_command -> ui/commands.py, never by
touching the document from here.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QLineEdit,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..commands import nudge_draw_order, set_instance_visible
from ..models.assembly_tree import AssemblyTreeFilter, AssemblyTreeModel, INSTANCE_ROLE


class TreeDock(QDockWidget):
    def __init__(self, selection_model, parent=None):
        super().__init__("Assembly Tree", parent)
        self.selection_model = selection_model
        self.model = AssemblyTreeModel(self)
        self.model.itemChanged.connect(self._item_changed)
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
        # Drag SOURCE only -- dropping onto the tree itself (reordering) is
        # out of scope for now; VariantSet workbench rows are drop targets.
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
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

    def _main_window(self):
        window = self.parent()
        return window if hasattr(window, "run_command") else None

    def _item_changed(self, item) -> None:
        instance_id = item.data(INSTANCE_ROLE)
        window = self._main_window()
        if not instance_id or window is None:
            return
        visible = item.checkState() == Qt.CheckState.Checked
        window.run_command(
            lambda document, image_sources: set_instance_visible(document, image_sources, instance_id, visible)
        )

    def _context_menu(self, point) -> None:
        proxy_index = self.tree.indexAt(point)
        if not proxy_index.isValid():
            return
        source_index = self.proxy.mapToSource(proxy_index)
        instance_id = self.model.itemFromIndex(source_index).data(INSTANCE_ROLE)
        window = self._main_window()
        if not instance_id or window is None:
            return

        menu = QMenu(self.tree)
        bring_forward = menu.addAction("Bring Forward\t]")
        send_backward = menu.addAction("Send Backward\t[")
        menu.addSeparator()
        bring_front = menu.addAction("Bring to Front\tShift+]")
        send_back = menu.addAction("Send to Back\tShift+[")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(point))

        def run(**kwargs):
            window.run_command(lambda document, image_sources: nudge_draw_order(document, instance_id, **kwargs))

        if chosen is bring_forward:
            run(direction=1)
        elif chosen is send_backward:
            run(direction=-1)
        elif chosen is bring_front:
            run(to_extreme=1)
        elif chosen is send_back:
            run(to_extreme=-1)
