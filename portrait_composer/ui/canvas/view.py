"""Interactive pan/zoom view with a direct-manipulation transform gizmo (C5-B).

mousePress captures the committed transform (via the gizmo), mouseMove only
updates the transient Qt preview, and mouseRelease performs exactly one
authoring transaction through MainWindow.run_command -- see gizmos.py and
commands.py. Plain left-drag manipulates the canvas; Space held temporarily
switches to pan, matching the directive's Space=Pan contract.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsView

from ...instances import Transform
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
        self._mask_brush: dict | None = None
        self._color_pick = None
        self._color_pick_source_image = None
        self._color_pick_error = "Choose a visible point in the canvas."
        self._keyboard_move: dict | None = None
        selection_model.subscribe(self._selection_changed_during_nudge)

    def _canvas_has_key_focus(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is None or focus is self or focus is self.viewport()

    def _selection_changed_during_nudge(self, selected_ids: list[str]) -> None:
        if self._keyboard_move is not None and list(selected_ids) != self._keyboard_move["selection"]:
            self.cancel_keyboard_move()

    def cancel_keyboard_move(self) -> None:
        gesture = self._keyboard_move
        self._keyboard_move = None
        if gesture is not None:
            self.scene_model.clear_transform_preview(gesture["targets"])

    def _begin_keyboard_move(self) -> bool:
        document = self.scene_model.document
        selected = list(self.selection_model.instance_ids)
        if document is None or not selected:
            return False
        from ..commands import selection_move_targets

        targets = selection_move_targets(document, selected)
        locked = [
            instance_id for instance_id in targets
            if (document.instance_authoring or {}).get(instance_id, {}).get("locked")
        ]
        if locked:
            names = [
                (document.instance_authoring or {}).get(instance_id, {}).get("display_name") or instance_id
                for instance_id in locked
            ]
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage(
                    "Edit failed: locked layer(s): " + ", ".join(names) + ". Unlock them before editing.",
                    6000,
                )
            return False
        self._keyboard_move = {
            "selection": selected,
            "targets": targets,
            "start": {
                instance_id: Transform.from_dict(document.instances[instance_id].transform.to_dict())
                for instance_id in targets
            },
            "dx": 0.0,
            "dy": 0.0,
            "active_keys": set(),
        }
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(
                "Nudge: Arrow 1 document px · Shift+Arrow 10 px · release commits once · Esc cancels",
                5000,
            )
        return True

    def _nudge_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        directions = {
            Qt.Key.Key_Left: (-1.0, 0.0),
            Qt.Key.Key_Right: (1.0, 0.0),
            Qt.Key.Key_Up: (0.0, -1.0),
            Qt.Key.Key_Down: (0.0, 1.0),
        }
        if key not in directions:
            return False
        if self._keyboard_move is None and not self._begin_keyboard_move():
            return True
        gesture = self._keyboard_move
        if gesture is None:
            return True
        if list(self.selection_model.instance_ids) != gesture["selection"]:
            self.cancel_keyboard_move()
            return True
        if not event.isAutoRepeat():
            gesture["active_keys"].add(key)
        distance = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        dx, dy = directions[key]
        gesture["dx"] += dx * distance
        gesture["dy"] += dy * distance
        transforms = {}
        for instance_id, start in gesture["start"].items():
            transform = Transform.from_dict(start.to_dict())
            transform.x += gesture["dx"]
            transform.y += gesture["dy"]
            transforms[instance_id] = transform
        self.scene_model.preview_transforms(transforms)
        return True

    def _commit_keyboard_move(self) -> None:
        gesture = self._keyboard_move
        self._keyboard_move = None
        if gesture is None:
            return
        dx, dy = gesture["dx"], gesture["dy"]
        self.scene_model.clear_transform_preview(gesture["targets"])
        if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
            return
        window = self.window()
        run_command = getattr(window, "run_command", None)
        if run_command is None:
            return
        from ..commands import move_instances_relative

        run_command(
            lambda document, image_sources: move_instances_relative(
                document, image_sources, gesture["selection"], dx=dx, dy=dy
            )
        )

    def begin_color_pick(self, instance_id, callback, *, source_image=None) -> None:
        """Pick native source pixels, or canvas pixels when instance_id is None."""
        self.cancel_mask_brush()
        self._color_pick = (instance_id, callback)
        self._color_pick_source_image = source_image.copy() if source_image is not None else None
        self._color_pick_error = "Choose a visible point in the canvas."
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel_color_pick(self) -> None:
        self._color_pick = None
        self._color_pick_source_image = None
        self.unsetCursor()

    def color_pick_point(self, scene_pos, instance_id=None):
        if instance_id is None:
            rect = self.scene_model.sceneRect()
            image = self.scene_model._committed_reference
            if image is None or not rect.contains(scene_pos) or rect.width() <= 0 or rect.height() <= 0:
                self._color_pick_error = "Target sample is outside the committed canvas."
                return None
            x = min(image.width - 1, int((scene_pos.x() - rect.left()) / rect.width() * image.width))
            y = min(image.height - 1, int((scene_pos.y() - rect.top()) / rect.height() * image.height))
            if image.getpixel((x, y))[3] <= 8:
                self._color_pick_error = "Target sample is transparent in the committed image. Pick a visible pixel."
                return None
            return (x, y)
        item = self.scene_model._hit_items.get(instance_id)
        if item is None:
            self._color_pick_error = "The selected source layer is not visible on the canvas."
            return None
        local = item.mapFromScene(scene_pos)
        rect = item.rect()
        if not rect.contains(local) or rect.isEmpty():
            self._color_pick_error = "Source sample is outside the selected layer. Pick inside its visible bounds."
            return None
        width, height = self.scene_model.image_size(instance_id)
        x = min(width - 1, int((local.x() - rect.left()) / rect.width() * width))
        y = min(height - 1, int((local.y() - rect.top()) / rect.height() * height))
        path = self.scene_model._resolve_image_path(instance_id)
        try:
            if self._color_pick_source_image is not None:
                alpha = self._color_pick_source_image.getpixel((x, y))[3]
            elif path is not None:
                with Image.open(path) as raw:
                    alpha = raw.convert("RGBA").getpixel((x, y))[3]
            else:
                raise OSError("source path is unavailable")
            visible = alpha > 8
        except (OSError, ValueError, IndexError):
            visible = False
        if not visible:
            self._color_pick_error = "Source sample is transparent or unavailable. Pick a visible pixel."
            return None
        return (x, y)

    def load_document(self, document, layers_dir, image_sources=None, *, preserve_view_state=None) -> None:
        view_state = preserve_view_state
        if view_state is True:
            view_state = self.capture_view_state()
        self.scene_model.load_document(document, layers_dir, image_sources)
        if view_state is None:
            self.fit_canvas()
        else:
            self.restore_exact_view_state(view_state)

    def capture_view_state(self) -> dict | None:
        """Capture the actual viewport, not just the coarse session values."""
        if self.scene_model.sceneRect().isEmpty() or self.viewport().size().isEmpty():
            return None
        return {
            "transform": QTransform(self.transform()),
            "center": self.mapToScene(self.viewport().rect().center()),
            "zoom": float(self.session.canvas_zoom),
        }

    def restore_exact_view_state(self, state: dict) -> None:
        """Restore a view after a scene reload without fitting the canvas."""
        transform = state.get("transform")
        center = state.get("center")
        if transform is None or center is None:
            self.fit_canvas()
            return
        self.setTransform(QTransform(transform))
        self.centerOn(center)
        self.scene_model.gizmo.reposition()
        self.session.canvas_zoom = max(0.05, min(32.0, float(state.get("zoom", self.session.canvas_zoom))))
        self.session.canvas_pan = (
            float(self.horizontalScrollBar().value()),
            float(self.verticalScrollBar().value()),
        )

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.session.canvas_pan = (
            float(self.horizontalScrollBar().value()),
            float(self.verticalScrollBar().value()),
        )

    # -- selection + gizmo/donor-ghost gestures --------------------------
    def enable_mask_brush(
        self, instance_id: str, op_id: str, *, radius: float, mode: str, strength: float = 1.0
    ) -> None:
        self._mask_brush = {
            "instance_id": instance_id,
            "op_id": op_id,
            "radius": float(radius),
            "mode": mode,
            "strength": max(0.0, min(1.0, float(strength))),
            "points": [],
        }
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(
                f"Mask brush: {mode} · drag inside the selected layer; Esc cancels", 5000
            )

    def cancel_mask_brush(self) -> None:
        if self._mask_brush is not None:
            self._mask_brush = None
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage("Mask brush cancelled", 2500)

    def _mask_image_point(self, scene_pos):
        brush = self._mask_brush
        if brush is None:
            return None
        item = self.scene_model._hit_items.get(brush["instance_id"])
        if item is None:
            return None
        local = item.mapFromScene(scene_pos)
        rect = item.rect()
        if rect.width() <= 0 or rect.height() <= 0 or not rect.contains(local):
            return None
        image_w, image_h = self.scene_model.image_size(brush["instance_id"])
        x = (local.x() - rect.left()) / rect.width() * image_w
        y = (local.y() - rect.top()) / rect.height() * image_h
        if not (0.0 <= x < image_w and 0.0 <= y < image_h):
            return None
        return (x, y)

    def _commit_mask_brush(self) -> None:
        brush = self._mask_brush
        self._mask_brush = None
        if brush is None or not brush["points"]:
            return
        window = self.window()
        run_command = getattr(window, "run_command", None)
        if run_command is None:
            return
        from ..commands import paint_instance_mask

        layers_dir = self.scene_model.layers_dir
        source_path = self.scene_model._resolve_image_path(brush["instance_id"])
        base_dir = (
            source_path.parent.parent if source_path is not None and source_path.parent.name == "layers"
            else source_path.parent if source_path is not None
            else layers_dir.parent if layers_dir is not None
            else None
        )
        work_dir = Path(tempfile.gettempdir()) / "portrait-composer-mask" / uuid4().hex
        result_holder = {}

        def commit(document, image_sources):
            result_holder["path"] = paint_instance_mask(
                document,
                image_sources,
                brush["instance_id"],
                op_id=brush["op_id"],
                points=brush["points"],
                radius=brush["radius"],
                mode=brush["mode"],
                strength=brush["strength"],
                work_dir=work_dir,
                base_dir=base_dir,
            )

        if run_command(commit) and result_holder.get("path") is None:
            window.statusBar().showMessage("Mask stroke made no change; no history entry was added.", 4000)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.scene_model.document is None:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.cancel_keyboard_move()
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)
        if self._color_pick is not None:
            instance_id, callback = self._color_pick
            point = self.color_pick_point(scene_pos, instance_id)
            if point is not None:
                self.cancel_color_pick()
                callback(point)
            else:
                window = self.window()
                if hasattr(window, "statusBar"):
                    window.statusBar().showMessage(self._color_pick_error, 5000)
            event.accept()
            return
        if self._mask_brush is not None:
            point = self._mask_image_point(scene_pos)
            if point is not None:
                self._mask_brush["points"] = [point]
            else:
                window = self.window()
                if hasattr(window, "statusBar"):
                    window.statusBar().showMessage("Mask strokes must start inside the selected layer.", 4000)
            event.accept()
            return
        # BAKE owns its source selection and transient staging recipe.  A
        # canvas click in this context must not fall through to the normal
        # ASSEMBLE picker, otherwise an accidental click changes the inputs
        # of Bake Selected (and can rebuild its candidate card).  Space-pan
        # remains available because it is a view gesture, not selection.
        if getattr(self.session, "active_context", "ASSEMBLE") == "BAKE":
            if self._space_panning:
                super().mousePressEvent(event)
            else:
                event.accept()
            return
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
                role = self._body_drag_role()
                if role is not None:
                    self.scene_model.gizmo.begin_drag(role, scene_pos)
            event.accept()
            return
        self.selection_model.clear()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._mask_brush is not None and self._mask_brush["points"]:
            point = self._mask_image_point(self.mapToScene(event.position().toPoint()))
            if point is not None:
                self._mask_brush["points"].append(point)
            event.accept()
            return
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
        if self._mask_brush is not None and self._mask_brush["points"]:
            self._commit_mask_brush()
            event.accept()
            return
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

        committed = run_command(
            lambda document, image_sources: set_instance_transform(
                document, image_sources, instance_id, **fields
            )
        )
        if not committed:
            # end_drag has cleared its transient preview already. Rebuild the
            # committed scene so a rejected linked edit cannot look applied.
            refresh = getattr(window, "_refresh_after_document_change", None)
            if refresh is not None:
                refresh()

    def _body_drag_role(self) -> tuple[str, None] | None:
        tool = getattr(self.session, "canvas_tool", "select")
        return None if tool == "select" else (tool, None)

    def wheelEvent(self, event):
        self.cancel_keyboard_move()
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.session.canvas_zoom = max(0.05, min(32.0, self.session.canvas_zoom * factor))
        self.scene_model.gizmo.reposition()
        event.accept()

    def fit_canvas(self) -> None:
        if not self.scene_model.sceneRect().isEmpty():
            self.fitInView(self.scene_model.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.scene_model.gizmo.reposition()
            self.session.canvas_zoom = 1.0
            self.session.canvas_pan = (0.0, 0.0)

    def restore_view_state(self, zoom: float, pan: tuple[float, float]) -> None:
        """Restore ephemeral view state after a document has been loaded."""
        self.fit_canvas()
        zoom = max(0.05, min(32.0, float(zoom)))
        if zoom != 1.0:
            self.scale(zoom, zoom)
        self.scene_model.gizmo.reposition()
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
            self.scene_model.gizmo.reposition()
            self.session.canvas_zoom = float(self.transform().m11())
            self.session.canvas_pan = (
                float(self.horizontalScrollBar().value()),
                float(self.verticalScrollBar().value()),
            )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._canvas_has_key_focus():
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape and self._keyboard_move is not None:
            self.cancel_keyboard_move()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.scene_model.donor_ghost.active:
                if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
                    super().keyPressEvent(event)
                    return
                directions = {
                    Qt.Key.Key_Left: (-1.0, 0.0),
                    Qt.Key.Key_Right: (1.0, 0.0),
                    Qt.Key.Key_Up: (0.0, -1.0),
                    Qt.Key.Key_Down: (0.0, 1.0),
                }
                distance = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
                dx, dy = directions[event.key()]
                if self.scene_model.donor_ghost.nudge(dx * distance, dy * distance):
                    window = self.window()
                    if hasattr(window, "statusBar"):
                        window.statusBar().showMessage(
                            "Donor moved in document pixels · Arrow 1 px · Shift+Arrow 10 px · Import applies placement",
                            4000,
                        )
                    event.accept()
                    return
            if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
                super().keyPressEvent(event)
            else:
                self._nudge_key(event)
                event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._color_pick is not None:
            _, callback = self._color_pick
            self.cancel_color_pick()
            callback(None)
            event.accept()
            return
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
        if event.key() == Qt.Key.Key_Escape and self._mask_brush is not None:
            self.cancel_mask_brush()
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
        if event.key() == Qt.Key.Key_Escape:
            cancel = getattr(window, "cancel_pending_operation", None)
            if cancel is not None:
                cancel()
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
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            gesture = self._keyboard_move
            if gesture is not None and not event.isAutoRepeat():
                gesture["active_keys"].discard(event.key())
                if not gesture["active_keys"]:
                    self._commit_keyboard_move()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        self.cancel_keyboard_move()
        super().focusOutEvent(event)
