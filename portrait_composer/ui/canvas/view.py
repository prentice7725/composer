"""Interactive pan/zoom view with a direct-manipulation transform gizmo (C5-B).

mousePress captures the committed transform (via the gizmo), mouseMove only
updates the transient Qt preview, and mouseRelease performs exactly one
authoring transaction through MainWindow.run_command -- see gizmos.py and
commands.py. Plain left-drag manipulates the canvas; Space held temporarily
switches to pan, matching the directive's Space=Pan contract.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGraphicsView

from .scene import CanvasScene, INSTANCE_ROLE


class CanvasView(QGraphicsView):
    def __init__(self, selection_model, session, parent=None):
        self.scene_model = CanvasScene(selection_model, parent)
        super().__init__(self.scene_model, parent)
        self.selection_model = selection_model
        self.session = session
        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Portrait composition canvas")
        self.setToolTip("Canvas: drag to transform a selected layer; hold Space to pan")
        self.setStyleSheet("QGraphicsView { border: 0; }")
        self._space_panning = False

    def load_document(self, document, layers_dir, image_sources=None) -> None:
        self.scene_model.load_document(document, layers_dir, image_sources)
        self.fit_canvas()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.session.canvas_pan = (
            float(self.horizontalScrollBar().value()),
            float(self.verticalScrollBar().value()),
        )

    # -- selection + gizmo/donor-ghost gestures --------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.scene_model.document is None:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            candidates = []
            for candidate in self.scene().items(scene_pos):
                instance_id = candidate.data(INSTANCE_ROLE)
                if instance_id and instance_id not in candidates:
                    candidates.append(str(instance_id))
            if candidates:
                current = self.selection_model.instance_ids[0] if len(self.selection_model.instance_ids) == 1 else None
                next_index = (candidates.index(current) + 1) % len(candidates) if current in candidates else 0
                self.selection_model.select(candidates[next_index])
                event.accept()
                return
        item = self.itemAt(pos)

        if self.scene_model.donor_ghost.active:
            # Donor Align owns the canvas while a ghost is loaded: any drag
            # moves the ghost (or its handle), never re-selects a Tree
            # instance underneath it.
            role = self.scene_model.donor_ghost.hit_role(item)
            self.scene_model.donor_ghost.begin_drag(role or ("move", None), scene_pos)
            event.accept()
            return

        if self.scene_model.region_edit.active:
            # Unlike the donor ghost, the region overlay only claims a
            # handle hit -- the target instance underneath stays normally
            # selectable/movable via the C5-B gizmo while Rig Intent is open.
            role = self.scene_model.region_edit.hit_role(item)
            if role is not None and self.scene_model.region_edit.begin_drag(role, scene_pos):
                event.accept()
                return

        role = self.scene_model.gizmo.hit_role(item)
        if role is not None and self.scene_model.gizmo.begin_drag(role, scene_pos):
            event.accept()
            return
        instance_id = item.data(INSTANCE_ROLE) if item is not None else None
        if instance_id:
            additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.selection_model.select(str(instance_id), additive=additive)
            if not additive and self.scene_model.gizmo.instance_id == instance_id:
                self.scene_model.gizmo.begin_drag(("move", None), scene_pos)
            event.accept()
            return
        self.selection_model.clear()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.scene_model.donor_ghost.drag is not None:
            self.scene_model.donor_ghost.update_drag(self.mapToScene(event.position().toPoint()), shift)
            event.accept()
            return
        if self.scene_model.region_edit.drag is not None:
            self.scene_model.region_edit.update_drag(self.mapToScene(event.position().toPoint()), shift)
            event.accept()
            return
        if self.scene_model.gizmo.drag is not None:
            self.scene_model.gizmo.update_drag(self.mapToScene(event.position().toPoint()), shift)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.scene_model.donor_ghost.drag is not None:
            self.scene_model.donor_ghost.end_drag()
            event.accept()
            return
        if self.scene_model.region_edit.drag is not None:
            geometry = self.scene_model.region_edit.end_drag()
            if geometry:
                self._commit_region_geometry(geometry)
            event.accept()
            return
        if self.scene_model.gizmo.drag is not None:
            fields = self.scene_model.gizmo.end_drag()
            if fields:
                self._commit_transform(fields)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _commit_region_geometry(self, geometry: dict) -> None:
        region_id = self.scene_model.region_edit.region_id
        window = self.window()
        run_command = getattr(window, "run_command", None)
        if region_id is None or run_command is None:
            return
        from ..commands import set_region_geometry

        run_command(
            lambda document, image_sources: set_region_geometry(document, image_sources, region_id, geometry)
        )

    def _commit_transform(self, fields: dict) -> None:
        instance_id = self.scene_model.gizmo.instance_id
        window = self.window()
        run_command = getattr(window, "run_command", None)
        if instance_id is None or run_command is None:
            return
        from ..commands import set_instance_transform

        run_command(
            lambda document, image_sources: set_instance_transform(
                document, image_sources, instance_id, **fields
            )
        )

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.session.canvas_zoom = max(0.05, min(32.0, self.session.canvas_zoom * factor))
        event.accept()

    def fit_canvas(self) -> None:
        if not self.scene_model.sceneRect().isEmpty():
            self.fitInView(self.scene_model.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.session.canvas_zoom = 1.0
            self.session.canvas_pan = (0.0, 0.0)

    def restore_view_state(self, zoom: float, pan: tuple[float, float]) -> None:
        """Restore ephemeral view state after a document has been loaded."""
        self.fit_canvas()
        zoom = max(0.05, min(32.0, float(zoom)))
        if zoom != 1.0:
            self.scale(zoom, zoom)
        self.session.canvas_zoom = zoom
        self.horizontalScrollBar().setValue(round(float(pan[0])))
        self.verticalScrollBar().setValue(round(float(pan[1])))
        self.session.canvas_pan = (
            float(self.horizontalScrollBar().value()),
            float(self.verticalScrollBar().value()),
        )

    def fit_selection(self) -> None:
        rects = [item.sceneBoundingRect() for item in self.scene_model._hit_items.values() if item.isSelected()]
        if rects:
            rect = rects[0]
            for other in rects[1:]:
                rect = rect.united(other)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        window = self.window()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            commit = getattr(window, "commit_pending_operation", None)
            if commit is not None:
                commit()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self.scene_model.donor_ghost.drag is not None:
            self.scene_model.donor_ghost.cancel_drag()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            cancel = getattr(window, "cancel_pending_operation", None)
            if cancel is not None:
                cancel()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self.scene_model.region_edit.drag is not None:
            self.scene_model.region_edit.cancel_drag()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.scene_model.gizmo.drag is not None:
            self.scene_model.gizmo.cancel_drag()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and not self._space_panning:
            self._space_panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return
        tools = {
            Qt.Key.Key_V: "select",
            Qt.Key.Key_G: "move",
            Qt.Key.Key_R: "rotate",
            Qt.Key.Key_S: "scale",
        }
        if event.key() in tools and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            set_tool = getattr(window, "set_canvas_tool", None)
            if set_tool is not None:
                set_tool(tools[event.key()])
                event.accept()
                return
        preview_modes = {Qt.Key.Key_1: "target_only", Qt.Key.Key_2: "donor_only", Qt.Key.Key_3: "composite"}
        if event.key() in preview_modes:
            set_mode = getattr(window, "set_preview_mode_shortcut", None)
            if set_mode is not None:
                set_mode(preview_modes[event.key()])
                event.accept()
                return
        if event.key() == Qt.Key.Key_F:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.fit_canvas()
            else:
                self.fit_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)
