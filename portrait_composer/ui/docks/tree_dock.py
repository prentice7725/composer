"""Assembly Tree dock; filtering never changes the shared selection.

Rows separate visibility, editable user names, relationship details, and the
edit-lock control. Each mutation commits through MainWindow.run_command ->
ui/commands.py, never by touching the document from here.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QLineEdit,
    QMenu,
    QHeaderView,
    QShortcut,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..commands import (
    delete_instances,
    move_draw_order_selection,
    reorder_draw_order,
    set_instance_authoring,
    set_instance_visible,
)
from ..models.assembly_tree import (
    INSTANCE_MIME_TYPE,
    AssemblyTreeFilter,
    AssemblyTreeModel,
    INSTANCE_ROLE,
    META_ROLE,
    LOCK_ROLE,
    NAME_ROLE,
)


class _ReorderTreeView(QTreeView):
    """Tree view that keeps its own drag source while owning reorder drops."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def dropEvent(self, event) -> None:
        if (
            event.source() == self
            and event.mimeData().hasFormat(INSTANCE_MIME_TYPE)
            and self.owner._drop_reorder(event)
        ):
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
        self._syncing_selection = False
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search layers, slots, sources")
        self.search.setAccessibleName("Assembly tree search")
        self.search.setToolTip("Filtering keeps selected layers active. Clear the filter to see the full selection.")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.filter_selector = QComboBox()
        self.filter_selector.addItems(
            ["All", "Selected Source", "Variants", "Warnings", "Rig-enabled", "Derived", "Hidden", "Unresolved"]
        )
        self.filter_selector.setAccessibleName("Assembly tree status filter")
        self.filter_selector.setToolTip("Filter layers by source, authoring relation, or validation state")
        self.filter_selector.currentTextChanged.connect(self.proxy.set_filter_mode)
        self.tree = _ReorderTreeView(self)
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 56)
        self.tree.header().resizeSection(2, 300)
        self.tree.header().resizeSection(3, 60)
        self.tree.setEditTriggers(
            QTreeView.EditTrigger.DoubleClicked | QTreeView.EditTrigger.EditKeyPressed
        )
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # The same tree remains a drag source for VariantSet membership, while
        # internal drops reorder the flat composition draw_order.
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setDropIndicatorShown(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.selectionModel().selectionChanged.connect(self._tree_selection_changed)
        self._rename_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F2), self.tree)
        self._rename_shortcut.activated.connect(self._edit_current_name)
        self.tree.setAccessibleName("Assembly tree")
        self.tree.setToolTip(
            "Double-click a layer name or press F2 to rename; Enter saves and Esc cancels. "
            "Use Show and Locked as separate controls. Rows at the end of draw order render in front; "
            "drag rows or use [ and ] to reorder."
        )
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
        self._syncing_selection = True
        try:
            self.model.load_document(document, diagnostics)
        finally:
            self._syncing_selection = False
        self._refresh_selection(self.selection_model.instance_ids)

    def _visible_instance_ids(self) -> set[str]:
        instance_ids = set()
        for row in range(self.proxy.rowCount()):
            proxy_index = self.proxy.index(row, 1)
            source_index = self.proxy.mapToSource(proxy_index)
            item = self.model.itemFromIndex(source_index)
            if item is not None and item.data(INSTANCE_ROLE):
                instance_ids.add(str(item.data(INSTANCE_ROLE)))
        return instance_ids

    def _tree_selection_changed(self, *_args) -> None:
        """Mirror keyboard and mouse selection without losing filtered rows."""
        if self._syncing_selection:
            return
        visible_ids = self._visible_instance_ids()
        selected_ids = []
        for index in self.tree.selectionModel().selectedRows(1):
            source_index = self.proxy.mapToSource(index)
            item = self.model.itemFromIndex(source_index)
            instance_id = item.data(INSTANCE_ROLE) if item is not None else None
            if instance_id:
                selected_ids.append(str(instance_id))
        hidden_selection = [
            instance_id for instance_id in self.selection_model.instance_ids
            if instance_id not in visible_ids
        ]
        self.selection_model.set_instances(hidden_selection + selected_ids)

    def _refresh_selection(self, selected_ids: list[str]) -> None:
        selected_sources = set()
        for row in range(self.model.rowCount()):
            item = self.model.item(row, 1)
            if item.data(INSTANCE_ROLE) in selected_ids:
                source = (item.data(META_ROLE) or {}).get("source")
                if source:
                    selected_sources.add(source)
        self._syncing_selection = True
        try:
            self.proxy.set_selected_source(next(iter(selected_sources)) if len(selected_sources) == 1 else None)
            self.tree.clearSelection()
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 1)
                source = self.proxy.mapToSource(index)
                instance_id = self.model.itemFromIndex(source).data(INSTANCE_ROLE)
                if instance_id in selected_ids:
                    left = self.proxy.index(row, 0)
                    right = self.proxy.index(row, 3)
                    self.tree.selectionModel().select(
                        QItemSelection(left, right), QItemSelectionModel.SelectionFlag.Select
                    )
        finally:
            self._syncing_selection = False

    def reveal_instances(self, instance_ids: list[str]) -> None:
        """Reveal and scroll to targets while restoring the user's filter."""
        filter_text = self.search.text()
        if filter_text:
            self.proxy.setFilterFixedString("")
        self._refresh_selection(instance_ids)
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 1)
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
        selected_set = set(self.selection_model.instance_ids)
        selected = [instance_id for instance_id in order if instance_id in selected_set]
        if not selected:
            source_index = self.tree.currentIndex()
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
        document = getattr(window, "document", None)
        instance = document.instances.get(instance_id) if document is not None else None
        if instance is None:
            return
        if item.column() == 0:
            visible = item.checkState() == Qt.CheckState.Checked
            if visible == instance.visible:
                return
            committed = window.run_command(
                lambda document, image_sources: set_instance_visible(document, image_sources, instance_id, visible)
            )
            if not committed:
                self._restore_check(item, instance.visible)
        elif item.column() == 1:
            old_name = item.data(NAME_ROLE) or instance_id
            new_name = item.text().strip()
            if not new_name or new_name == old_name:
                QTimer.singleShot(
                    0,
                    lambda: self.load_document(document, getattr(window, "diagnostics", None))
                    if getattr(window, "document", None) is document else None,
                )
                return
            QTimer.singleShot(
                0,
                lambda: self._commit_display_name(
                    window, document, instance_id, new_name
                ),
            )
        elif item.column() == 3:
            locked = item.checkState() == Qt.CheckState.Checked
            old_locked = bool(item.data(LOCK_ROLE))
            if locked == old_locked:
                return
            committed = window.run_command(
                lambda document, image_sources: set_instance_authoring(
                    document, image_sources, instance_id, locked=locked
                )
            )
            if not committed:
                self._restore_check(item, old_locked)

    def _restore_check(self, item, checked: bool) -> None:
        self.model.blockSignals(True)
        try:
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.model.blockSignals(False)

    def _edit_current_name(self) -> None:
        index = self.tree.currentIndex()
        if index.isValid():
            self.tree.edit(index.siblingAtColumn(1))

    def _commit_display_name(self, window, expected_document, instance_id: str, display_name: str) -> None:
        document = getattr(window, "document", None)
        if document is not expected_document or instance_id not in document.instances:
            return
        window.run_command(
            lambda document, image_sources: set_instance_authoring(
                document, image_sources, instance_id, display_name=display_name
            )
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
        menu.addSeparator()
        delete_layers = menu.addAction("Delete Selected Layers")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(point))

        selected = list(self.selection_model.instance_ids)
        if instance_id not in selected:
            selected = [instance_id]

        def run(**kwargs):
            window.run_command(
                lambda document, image_sources: move_draw_order_selection(document, selected, **kwargs)
            )

        if chosen is bring_forward:
            run(direction=1)
        elif chosen is send_backward:
            run(direction=-1)
        elif chosen is bring_front:
            run(to_extreme=1)
        elif chosen is send_back:
            run(to_extreme=-1)
        elif chosen is delete_layers:
            window.run_command(lambda document, image_sources: delete_instances(document, image_sources, selected))
