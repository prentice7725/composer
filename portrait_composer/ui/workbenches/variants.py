"""C5-D VariantSet / Expression Workbench (directive #9, #28).

A VariantSet member click commits immediately (one click = one set_active
transaction) -- the directive only describes a pending/Apply step for
Harvest candidates and Expression picks, matching the Adobe Character
Animator Swap Set "trigger tag" model it's explicitly modeled on (#38).
Only the Expression Preset's per-VariantSet picks get a Preview/Apply
split, since those are genuinely provisional until Applied.

Every mutation goes through MainWindow.run_command -> ui/commands.py;
MainWindow._refresh_after_document_change() refreshes whichever workbench
is currently visible, so a plain undo/redo also keeps this in sync without
each handler here needing its own refresh call.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models.assembly_tree import INSTANCE_MIME_TYPE

THUMBNAIL_SIZE = 64


def _label_for(document, instance_id: str) -> str:
    instance = document.instances.get(instance_id) if document else None
    asset = document.assets.get(instance.asset_ref) if document and instance is not None else None
    return asset.semantic if asset is not None else instance_id


class _MemberTile(QFrame):
    picked = Signal(str)  # member_id
    remove_requested = Signal(str)  # member_id

    def __init__(self, member_id: str, label: str, image_path, *, is_default: bool, is_active: bool, parent=None):
        super().__init__(parent)
        self.member_id = member_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Variant member {member_id}")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        thumb = QLabel()
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                THUMBNAIL_SIZE, THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        thumb.setPixmap(pixmap)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb)
        layout.addWidget(QLabel(label))
        tags = " · ".join(t for t, on in (("DEFAULT", is_default), ("ACTIVE", is_active)) if on)
        tag_label = QLabel(tags)
        tag_label.setStyleSheet("color: #ffd166; font-weight: bold;" if is_active else "color: #7a8296;")
        layout.addWidget(tag_label)
        border = "2px solid #ffd166" if is_active else "1px solid #3a3f4b"
        self.setStyleSheet(f"QFrame {{ border: {border}; }}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.member_id)
        super().mousePressEvent(event)

    def _context_menu(self, point) -> None:
        menu = QMenu(self)
        remove_action = menu.addAction("Remove from Variant Set")
        chosen = menu.exec(self.mapToGlobal(point))
        if chosen is remove_action:
            self.remove_requested.emit(self.member_id)


class _VariantSetRow(QFrame):
    """One VariantSet's exclusive selector strip; also a drag-drop target
    for adding a Tree instance as a new member (directive #9.2)."""

    def __init__(self, main_window, vs_id: str, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.vs_id = vs_id
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        header = QLabel(vs_id.upper())
        header.setStyleSheet("font-weight: bold;")
        outer.addWidget(header)
        self.strip = QHBoxLayout()
        self.strip.addStretch(1)
        outer.addLayout(self.strip)
        hint = QLabel("Drop a Tree layer here to add a member")
        hint.setStyleSheet("color: #7a8296; font-style: italic;")
        outer.addWidget(hint)
        self.refresh()

    def refresh(self) -> None:
        while self.strip.count() > 1:
            item = self.strip.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        document = self.main_window.document
        vs = document.variant_sets.get(self.vs_id) if document is not None else None
        if vs is None:
            return
        for member_id in vs["members"]:
            image_path = self.main_window.canvas.scene_model._resolve_image_path(member_id)
            tile = _MemberTile(
                member_id,
                _label_for(document, member_id),
                image_path,
                is_default=(member_id == vs.get("default")),
                is_active=(member_id == vs.get("active")),
            )
            tile.picked.connect(self._pick)
            tile.remove_requested.connect(self._remove)
            self.strip.insertWidget(self.strip.count() - 1, tile)

    def _pick(self, member_id: str) -> None:
        from ..commands import set_variant_active

        self.main_window.run_command(
            lambda document, image_sources: set_variant_active(document, image_sources, self.vs_id, member_id)
        )

    def _remove(self, member_id: str) -> None:
        from ..commands import remove_variant_member

        self.main_window.run_command(
            lambda document, image_sources: remove_variant_member(document, image_sources, self.vs_id, member_id)
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(INSTANCE_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        raw = bytes(event.mimeData().data(INSTANCE_MIME_TYPE)).decode("utf-8")
        instance_id = raw.splitlines()[0] if raw else None
        if instance_id:
            from ..commands import add_variant_member

            self.main_window.run_command(
                lambda document, image_sources: add_variant_member(document, image_sources, self.vs_id, instance_id)
            )
        event.acceptProposedAction()


class _ExpressionEditor(QWidget):
    """Per-VariantSet member picks for one named ExpressionPreset, with a
    non-destructive Preview and a committing Apply (directive #9.3)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._preset_id: str | None = None
        self._dropdowns: dict[str, QComboBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("Expression"))
        self.preset_selector = QComboBox()
        self.preset_selector.setAccessibleName("Expression preset selector")
        self.preset_selector.currentTextChanged.connect(self._select_preset)
        top.addWidget(self.preset_selector, 1)
        new_button = QPushButton("New Preset…")
        new_button.setAccessibleName("New expression preset")
        new_button.clicked.connect(self._new_preset)
        top.addWidget(new_button)
        outer.addLayout(top)

        self.rows_body = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_body)
        self.rows_layout.setContentsMargins(0, 4, 0, 4)
        outer.addWidget(self.rows_body)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        bottom.addWidget(self.status_label, 1)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setAccessibleName("Preview expression")
        self.preview_button.clicked.connect(self._preview)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setAccessibleName("Apply expression")
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.preview_button)
        bottom.addWidget(self.apply_button)
        outer.addLayout(bottom)

    def refresh(self) -> None:
        document = self.main_window.document
        presets = sorted(document.expressions) if document is not None else []
        self.preset_selector.blockSignals(True)
        previous = self.preset_selector.currentText()
        self.preset_selector.clear()
        self.preset_selector.addItems(presets)
        if previous in presets:
            self.preset_selector.setCurrentText(previous)
        self.preset_selector.blockSignals(False)
        self._select_preset(self.preset_selector.currentText())

    def _select_preset(self, preset_id: str) -> None:
        self._preset_id = preset_id or None
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._dropdowns = {}
        document = self.main_window.document
        if document is None:
            self.status_label.setText("No document open.")
            self.preview_button.setEnabled(False)
            self.apply_button.setEnabled(False)
            return
        preset = document.expressions.get(self._preset_id) if self._preset_id else None
        selections = dict(preset["variants"]) if preset else {}
        for vs_id, vs in document.variant_sets.items():
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(vs_id))
            combo = QComboBox()
            combo.setAccessibleName(f"Expression state {vs_id}")
            for member_id in vs["members"]:
                combo.addItem(_label_for(document, member_id), member_id)
            wanted = selections.get(vs_id, vs.get("active"))
            index = combo.findData(wanted)
            if index >= 0:
                combo.setCurrentIndex(index)
            row.addWidget(combo, 1)
            self.rows_layout.addWidget(row_widget)
            self._dropdowns[vs_id] = combo
        enabled = self._preset_id is not None and bool(self._dropdowns)
        self.preview_button.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        if not document.variant_sets:
            self.status_label.setText("No VariantSets yet -- add one above first.")
        else:
            self.status_label.setText(f"Editing: {self._preset_id}" if self._preset_id else "New Preset… to start one.")

    def _current_variants(self) -> dict[str, str]:
        return {vs_id: combo.currentData() for vs_id, combo in self._dropdowns.items()}

    def _new_preset(self) -> None:
        document = self.main_window.document
        if document is None or not document.variant_sets:
            self.status_label.setText("Add at least one VariantSet member before creating an expression.")
            return
        name, ok = QInputDialog.getText(self, "New Expression Preset", "Name:")
        if not ok or not name:
            return
        from ..commands import save_expression

        variants = {vs_id: vs.get("active") for vs_id, vs in document.variant_sets.items()}
        if self.main_window.run_command(lambda doc, srcs: save_expression(doc, srcs, name, variants)):
            self.preset_selector.setCurrentText(name)

    def _preview(self) -> None:
        if self._dropdowns:
            self.main_window.canvas.scene_model.preview_variant_selection(self._current_variants())

    def _apply(self) -> None:
        if self._preset_id is None or not self._dropdowns:
            return
        from ..commands import save_and_apply_expression

        preset_id = self._preset_id
        variants = self._current_variants()
        self.main_window.run_command(lambda doc, srcs: save_and_apply_expression(doc, srcs, preset_id, variants))


class VariantWorkbench(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._rows: dict[str, _VariantSetRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Variant Sets"))
        header.addStretch(1)
        new_set_button = QPushButton("+ New Variant Set (from selection)")
        new_set_button.setAccessibleName("New variant set from selection")
        new_set_button.clicked.connect(self._new_variant_set)
        header.addWidget(new_set_button)
        outer.addLayout(header)

        self.sets_area = QScrollArea()
        self.sets_area.setWidgetResizable(True)
        self.sets_area.setFixedHeight(170)
        self.sets_body = QWidget()
        self.sets_layout = QVBoxLayout(self.sets_body)
        self.sets_layout.addStretch(1)
        self.sets_area.setWidget(self.sets_body)
        outer.addWidget(self.sets_area)

        outer.addWidget(QLabel("Expression Presets"))
        self.expression_editor = _ExpressionEditor(main_window)
        outer.addWidget(self.expression_editor)

    def refresh(self) -> None:
        document = self.main_window.document
        vs_ids = sorted(document.variant_sets) if document is not None else []
        for vs_id in list(self._rows):
            if vs_id not in vs_ids:
                row = self._rows.pop(vs_id)
                self.sets_layout.removeWidget(row)
                row.deleteLater()
        for vs_id in vs_ids:
            if vs_id not in self._rows:
                row = _VariantSetRow(self.main_window, vs_id)
                self.sets_layout.insertWidget(self.sets_layout.count() - 1, row)
                self._rows[vs_id] = row
            else:
                self._rows[vs_id].refresh()
        self.expression_editor.refresh()

    def _new_variant_set(self) -> None:
        selected = self.main_window.selection_model.instance_ids
        if len(selected) != 1:
            self.main_window.statusBar().showMessage(
                "Select exactly one Tree layer to start a Variant Set from.", 5000
            )
            return
        name, ok = QInputDialog.getText(self, "New Variant Set", "Name:")
        if not ok or not name:
            return
        if self.main_window.document is not None and name in self.main_window.document.variant_sets:
            self.main_window.statusBar().showMessage(f"Variant Set {name!r} already exists.", 5000)
            return
        from ..commands import add_variant_member

        instance_id = selected[0]
        self.main_window.run_command(
            lambda document, image_sources: add_variant_member(
                document, image_sources, name, instance_id, default=True
            )
        )
