"""Assembly Tree dock; filtering never changes the shared selection.

C5-B adds a per-row visibility checkbox and a draw-order context menu, both
committing through MainWindow.run_command -> ui/commands.py, never by
touching the document from here.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QLineEdit,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..commands import nudge_draw_order, reorder_draw_order, set_instance_visible
from ..models.assembly_tree import AssemblyTreeFilter, AssemblyTreeModel, INSTANCE_ROLE


class _ReorderTreeView(QTreeView):
    """Tree view that keeps its own drag source while owning reorder drops."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def dropEvent(self, event) -> None:
        if self.owner._drop_reorder(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()


class TreeDock(QDockWidget):
    def __init__(self, selection_model, parent=None):
        super().__init__("Assembly Tree", parent)
        self.setObjectName("assemblyTreeDock")
        self.selection_model = selection_model
        self.model = AssemblyTreeModel(self)
        self.model.itemChanged.connect(self._item_changed)
        self.proxy = AssemblyTreeFilter(self)
        self.proxy.setSourceModel(self.model)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search layers, slots, sources")
        self.search.setAccessibleName("Assembly tree search")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.filter_selector = QComboBox()
        self.filter_selector.addItems(
            ["All", "Selected Source", "Variants", "Warnings", "Rig-enabled", "Derived", "Hidden", "Unresolved"]
        )
        self.filter_selector.setAccessibleName("Assembly tree status filter")
        self.filter_selector.setToolTip("Filter layers by source, authoring relation, or validation state")
        self.filter_selector.currentTextChanged.connect(self.proxy.set_filter_mode)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # The same tree remains a drag source for VariantSet membership, while
        # internal drops reorder the flat composition draw_order.
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setDropIndicatorShown(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.clicked.connect(self._clicked)
        self.tree.setAccessibleName("Assembly tree")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.search)
        layout.addWidget(self.filter_selector)
        layout.addWidget(self.tree)
        self.setWidget(body)
        selection_model.subscribe(self._refresh_selection)

    def load_document(self, document, diagnostics=None) -> None:
        self.model.load_document(document, diagnostics)
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

    def reveal_instances(self, instance_ids: list[str]) -> None:
        """Reveal and scroll to targets while restoring the user's filter."""
        filter_text = self.search.text()
        if filter_text:
            self.proxy.setFilterFixedString("")
        self._refresh_selection(instance_ids)
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            source = self.proxy.mapToSource(index)
            target = self.model.itemFromIndex(source).data(INSTANCE_ROLE)
            if target in instance_ids:
                self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                break
        if filter_text:
            self.proxy.setFilterFixedString(filter_text)
            self._refresh_selection(instance_ids)

    def _main_window(self):
        window = self.parent()
        return window if hasattr(window, "run_command") else None

    def _drop_reorder(self, event) -> bool:
        """Move the selected rows around the drop target in one transaction.

        The proxy index is translated back to the document's complete
        draw_order, so reordering remains well-defined while a filter is
        active. A drop onto a selected row or a no-op is rejected without
        creating history noise.
        """
        window = self._main_window()
        document = getattr(window, "document", None) if window is not None else None
        if document is None:
            return False

        order = list(document.composition.get("draw_order", []))
        selected = [instance_id for instance_id in self.selection_model.instance_ids if instance_id in order]
        if not selected:
            source_index = self.tree.indexAt(event.position().toPoint())
            if source_index.isValid():
                source = self.proxy.mapToSource(source_index)
                instance_id = self.model.itemFromIndex(source).data(INSTANCE_ROLE)
                if instance_id in order:
                    selected = [str(instance_id)]
        if not selected:
            return False

        target_index = self.tree.indexAt(event.position().toPoint())
        target_id = None
        insert_after = False
        if target_index.isValid():
            target_source = self.proxy.mapToSource(target_index)
            target_id = self.model.itemFromIndex(target_source).data(INSTANCE_ROLE)
            if target_id in selected:
                return False
            insert_after = event.position().y() >= self.tree.visualRect(target_index).center().y()

        remaining = [instance_id for instance_id in order if instance_id not in selected]
        if target_id is None:
            insert_at = len(remaining)
        else:
            insert_at = remaining.index(target_id) + (1 if insert_after else 0)
        new_order = remaining[:insert_at] + selected + remaining[insert_at:]
        if new_order == order:
            return False

        return bool(window.run_command(
            lambda document, image_sources: reorder_draw_order(document, new_order)
        ))

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
