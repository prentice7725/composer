"""Move/scale/rotate gizmo for the single-instance selection (C5-B).

Every drag is Qt-only transient state (directive #6.3, #18, #20): begin_drag
captures the committed AssemblyDocument transform, update_drag only touches
the QGraphicsRectItem's visual geometry, and end_drag returns the field(s)
to commit through the command layer as exactly one authoring transaction.
cancel_drag restores the item's visual geometry with no document access at
all -- the document was never touched during the drag, so Esc is always a
byte-identical no-op for free.

Corner-handle scaling is anchored at the instance's own center rather than
the opposite corner: it keeps the math well-defined regardless of the
instance's current rotation (translation and center-anchored scaling both
commute with rotation, so no rotation-aware position bookkeeping is
needed), at the cost of not offering an opposite-corner-anchored resize in
this v1. Rotation uses a live QGraphicsItem inverse transform captured once
at drag start, so it stays correct through any prior rotation/position.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsRectItem

from ...instances import Transform

GIZMO_ROLE = 33
HANDLE_SIZE = 9.0
ROTATE_OFFSET = 28.0
MIN_EXTENT = 4.0

_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")


def _encode_role(kind: str, detail: str | None = None) -> str:
    """Store only Qt built-in data in QGraphicsItem user data.

    Passing Python tuples through ``QGraphicsItem.setData`` relies on a
    PySide QVariant wrapper.  On some Qt/PySide Windows combinations that
    wrapper can later be reconstructed as an invalid metatype.  The role is
    a tiny protocol, so a string is both safer and sufficient.
    """
    return kind if detail is None else f"{kind}:{detail}"


def _decode_role(value) -> Optional[tuple[str, str | None]]:
    if not isinstance(value, str) or not value:
        return None
    kind, separator, detail = value.partition(":")
    if not kind:
        return None
    return kind, detail if separator and detail else None


@dataclass
class _Drag:
    kind: str
    start_scene_pos: QPointF
    start_rect: QRectF
    start_pos: QPointF
    start_rotation: float
    image_w: float
    image_h: float
    start_transform: dict
    start_bounds: Optional[QRectF] = None
    inverse: object = None
    center_scene: Optional[QPointF] = None
    start_angle: float = 0.0


@dataclass
class _GroupDrag:
    kind: str
    start_scene_pos: QPointF
    selected_ids: list[str]
    target_ids: list[str]
    start_transforms: dict
    pivot: QPointF
    start_bounds: QRectF
    start_angle: float = 0.0
    start_distance: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    scale_factor: float = 1.0
    rotation_delta: float = 0.0


class TransformGizmo:
    """Owns the handle graphics items for the active selection."""

    def __init__(self, scene) -> None:
        self.scene = scene
        self.instance_id: Optional[str] = None
        self.instance_ids: list[str] = []
        self.target_item: Optional[QGraphicsRectItem] = None
        self._handles: dict[str, QGraphicsItem] = {}
        self.drag: Optional[_Drag] = None

    # -- lifecycle -----------------------------------------------------
    def attach(self, instance_id: str, item: QGraphicsRectItem) -> None:
        self._attach_selection([instance_id], target_item=item)

    def attach_selection(self, instance_ids) -> None:
        self._attach_selection(list(dict.fromkeys(str(value) for value in instance_ids)))

    def _attach_selection(
        self, instance_ids: list[str], *, target_item: QGraphicsRectItem | None = None
    ) -> None:
        if self.instance_ids == instance_ids:
            self.reposition()
            return
        self.detach()
        self.instance_ids = instance_ids
        self.instance_id = instance_ids[0] if len(instance_ids) == 1 else None
        self.target_item = (
            target_item if target_item is not None else self.scene._hit_items.get(instance_ids[0])
        ) if len(instance_ids) == 1 else None
        if not instance_ids:
            return
        for name in _CORNERS:
            handle = QGraphicsRectItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
            handle.setBrush(QBrush(QColor("#ffd166")))
            handle.setPen(QPen(QColor("#20242b"), 1.0))
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            handle.setZValue(10_000)
            handle.setData(GIZMO_ROLE, _encode_role("scale", name))
            self.scene.addItem(handle)
            self._handles[name] = handle
        rotate_handle = QGraphicsEllipseItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
        rotate_handle.setBrush(QBrush(QColor("#59d4ff")))
        rotate_handle.setPen(QPen(QColor("#20242b"), 1.0))
        rotate_handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        rotate_handle.setZValue(10_000)
        rotate_handle.setData(GIZMO_ROLE, _encode_role("rotate"))
        self.scene.addItem(rotate_handle)
        self._handles["rotate"] = rotate_handle
        self.reposition()

    def detach(self) -> None:
        if self.drag is not None:
            self.cancel_drag()
        for handle in self._handles.values():
            self.scene.removeItem(handle)
        self._handles.clear()
        self.instance_id = None
        self.instance_ids = []
        self.target_item = None
        self.drag = None

    def reposition(self) -> None:
        if not self.instance_ids or self.drag is not None or not self._handles:
            return
        if len(self.instance_ids) > 1:
            rect = self._selection_bounds(self.instance_ids)
            points = {
                "top_left": rect.topLeft(),
                "top_right": rect.topRight(),
                "bottom_left": rect.bottomLeft(),
                "bottom_right": rect.bottomRight(),
            }
            for name, point in points.items():
                self._handles[name].setPos(point)
            zoom = 1.0
            views = self.scene.views()
            if views:
                zoom = max(0.001, abs(float(views[0].transform().m11())))
            self._handles["rotate"].setPos(
                QPointF(rect.center().x(), rect.top() - ROTATE_OFFSET / zoom)
            )
            return
        if self.target_item is None:
            return
        rect = self.target_item.rect()
        points = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        for name, local_point in points.items():
            self._handles[name].setPos(self.target_item.mapToScene(local_point))
        zoom = 1.0
        views = self.scene.views()
        if views:
            zoom = max(0.001, abs(float(views[0].transform().m11())))
        offset = ROTATE_OFFSET / zoom
        top_mid_x = (rect.left() + rect.right()) / 2.0
        top_center = self.target_item.mapToScene(QPointF(top_mid_x, rect.top()))
        outside = self.target_item.mapToScene(QPointF(top_mid_x, rect.top() - 1.0))
        normal = top_center - outside
        normal_length = math.hypot(normal.x(), normal.y())
        if normal_length > 1e-9:
            top_center += normal * (offset / normal_length)
        self._handles["rotate"].setPos(top_center)

    # -- drag ------------------------------------------------------------
    def hit_role(self, item) -> Optional[tuple[str, str | None]]:
        if item is None:
            return None
        return _decode_role(item.data(GIZMO_ROLE))

    def begin_drag(self, role: tuple, scene_pos: QPointF) -> bool:
        if len(self.instance_ids) > 1:
            return self._begin_group_drag(role, scene_pos)
        if self.target_item is None or self.instance_id is None:
            return False
        instance = self.scene.document.instances.get(self.instance_id)
        if instance is None:
            return False
        if (self.scene.document.instance_authoring or {}).get(self.instance_id, {}).get("locked"):
            return False
        kind, _corner = role
        image_w, image_h = self.scene.image_size(self.instance_id)
        transform = instance.transform
        drag = _Drag(
            kind=kind,
            start_scene_pos=QPointF(scene_pos),
            start_rect=QRectF(self.target_item.rect()),
            start_pos=QPointF(self.target_item.pos()),
            start_rotation=self.target_item.rotation(),
            image_w=float(image_w),
            image_h=float(image_h),
            start_transform={
                "x": transform.x,
                "y": transform.y,
                "scale_x": transform.scale_x,
                "scale_y": transform.scale_y,
                "rotation": transform.rotation,
            },
            start_bounds=QRectF(self.target_item.sceneBoundingRect()),
        )
        if kind == "scale":
            inverse, invertible = self.target_item.sceneTransform().inverted()
            drag.inverse = inverse if invertible else None
        elif kind == "rotate":
            drag.center_scene = self.target_item.mapToScene(drag.start_rect.center())
            delta = scene_pos - drag.center_scene
            drag.start_angle = math.degrees(math.atan2(delta.y(), delta.x()))
        self.drag = drag
        self.scene.preview_state.begin()
        self.scene.preview_state.set_transform(self.instance_id, drag.start_transform)
        return True

    def _selection_bounds(self, instance_ids) -> QRectF:
        bounds = None
        for instance_id in instance_ids:
            item = self.scene._hit_items.get(instance_id)
            if item is not None:
                rect = item.sceneBoundingRect()
            else:
                instance = self.scene.document.instances.get(instance_id)
                if instance is None:
                    continue
                width, height = self.scene.image_size(instance_id)
                transform = instance.transform
                scaled_w = width * abs(transform.scale_x)
                scaled_h = height * abs(transform.scale_y)
                radians = math.radians(transform.rotation)
                bound_w = abs(math.cos(radians)) * scaled_w + abs(math.sin(radians)) * scaled_h
                bound_h = abs(math.sin(radians)) * scaled_w + abs(math.cos(radians)) * scaled_h
                center = QPointF(transform.x + scaled_w / 2.0, transform.y + scaled_h / 2.0)
                rect = QRectF(center.x() - bound_w / 2.0, center.y() - bound_h / 2.0, bound_w, bound_h)
            bounds = rect if bounds is None else bounds.united(rect)
        return bounds if bounds is not None else QRectF()

    def _begin_group_drag(self, role: tuple, scene_pos: QPointF) -> bool:
        document = self.scene.document
        selected = list(self.instance_ids)
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
            window = self.scene.views()[0].window() if self.scene.views() else None
            if window is not None and hasattr(window, "statusBar"):
                window.statusBar().showMessage(
                    "Edit failed: locked layer(s): " + ", ".join(names) + ". Unlock them before editing.",
                    6000,
                )
            return False
        kind, _detail = role
        bounds = self._selection_bounds(selected)
        pivot = bounds.center()
        delta = scene_pos - pivot
        start_transforms = {
            instance_id: Transform.from_dict(document.instances[instance_id].transform.to_dict())
            for instance_id in targets
        }
        self.drag = _GroupDrag(
            kind=kind,
            start_scene_pos=QPointF(scene_pos),
            selected_ids=selected,
            target_ids=targets,
            start_transforms=start_transforms,
            pivot=pivot,
            start_bounds=QRectF(bounds),
            start_angle=math.degrees(math.atan2(delta.y(), delta.x())),
            start_distance=max(1.0, math.hypot(delta.x(), delta.y())),
        )
        self.scene.preview_state.begin()
        for instance_id, transform in start_transforms.items():
            self.scene.preview_state.set_transform(instance_id, transform.to_dict())
        return True

    def _group_preview_transforms(self, drag: _GroupDrag) -> dict:
        transforms = {}
        pivot_x, pivot_y = drag.pivot.x(), drag.pivot.y()
        radians = math.radians(drag.rotation_delta)
        cosine, sine = math.cos(radians), math.sin(radians)
        for instance_id, start in drag.start_transforms.items():
            transform = Transform.from_dict(start.to_dict())
            width, height = self.scene.image_size(instance_id)
            center_x = start.x + width * abs(start.scale_x) / 2.0
            center_y = start.y + height * abs(start.scale_y) / 2.0
            if drag.kind == "move":
                transform.x += drag.dx
                transform.y += drag.dy
            elif drag.kind == "scale":
                center_x = pivot_x + (center_x - pivot_x) * drag.scale_factor
                center_y = pivot_y + (center_y - pivot_y) * drag.scale_factor
                transform.scale_x *= drag.scale_factor
                transform.scale_y *= drag.scale_factor
                transform.x = center_x - width * abs(transform.scale_x) / 2.0
                transform.y = center_y - height * abs(transform.scale_y) / 2.0
            elif drag.kind == "rotate":
                offset_x, offset_y = center_x - pivot_x, center_y - pivot_y
                center_x = pivot_x + cosine * offset_x - sine * offset_y
                center_y = pivot_y + sine * offset_x + cosine * offset_y
                transform.x = center_x - width * abs(transform.scale_x) / 2.0
                transform.y = center_y - height * abs(transform.scale_y) / 2.0
                transform.rotation += drag.rotation_delta
            transforms[instance_id] = transform
        return transforms

    def update_drag(self, scene_pos: QPointF, preserve_aspect: bool) -> None:
        drag = self.drag
        if drag is None:
            return
        if isinstance(drag, _GroupDrag):
            if drag.kind == "move":
                delta = scene_pos - drag.start_scene_pos
                drag.dx, drag.dy = delta.x(), delta.y()
            elif drag.kind == "scale":
                delta = scene_pos - drag.pivot
                drag.scale_factor = max(
                    0.02, math.hypot(delta.x(), delta.y()) / drag.start_distance
                )
            elif drag.kind == "rotate":
                delta = scene_pos - drag.pivot
                current_angle = math.degrees(math.atan2(delta.y(), delta.x()))
                drag.rotation_delta = (current_angle - drag.start_angle + 180.0) % 360.0 - 180.0
            self.scene.preview_transforms(self._group_preview_transforms(drag))
            return
        if self.target_item is None:
            return
        if drag.kind == "move":
            delta = scene_pos - drag.start_scene_pos
            self.target_item.setPos(drag.start_pos + delta)
        elif drag.kind == "scale":
            if drag.inverse is None:
                return
            local_pt = drag.inverse.map(scene_pos)
            center_local = drag.start_rect.center()
            offset_x = abs(local_pt.x() - center_local.x())
            offset_y = abs(local_pt.y() - center_local.y())
            new_w = max(MIN_EXTENT, 2.0 * offset_x)
            new_h = max(MIN_EXTENT, 2.0 * offset_y)
            if preserve_aspect:
                ratio = max(new_w / drag.image_w, new_h / drag.image_h)
                new_w, new_h = drag.image_w * ratio, drag.image_h * ratio
            new_rect = QRectF(
                center_local.x() - new_w / 2.0,
                center_local.y() - new_h / 2.0,
                new_w,
                new_h,
            )
            self.target_item.setRect(new_rect)
            self.target_item.setTransformOriginPoint(new_rect.center())
        elif drag.kind == "rotate":
            delta = scene_pos - drag.center_scene
            current_angle = math.degrees(math.atan2(delta.y(), delta.x()))
            self.target_item.setRotation(drag.start_rotation + (current_angle - drag.start_angle))
        self.scene.preview_state.set_transform(self.instance_id, self._current_preview_transform(drag))

    def _current_preview_transform(self, drag: _Drag) -> dict:
        """Read the proxy item into a transient transform override."""
        preview = dict(drag.start_transform)
        if self.target_item is None:
            return preview
        if drag.kind == "move":
            position = self.target_item.pos()
            preview.update(x=position.x(), y=position.y())
        elif drag.kind == "scale":
            rect = self.target_item.rect()
            scale_x = rect.width() / drag.image_w
            scale_y = rect.height() / drag.image_h
            preview.update(
                scale_x=scale_x,
                scale_y=scale_y,
                x=drag.start_transform["x"] + drag.image_w * drag.start_transform["scale_x"] / 2.0 - drag.image_w * scale_x / 2.0,
                y=drag.start_transform["y"] + drag.image_h * drag.start_transform["scale_y"] / 2.0 - drag.image_h * scale_y / 2.0,
            )
        elif drag.kind == "rotate":
            preview["rotation"] = self.target_item.rotation()
        return preview

    def cancel_drag(self) -> None:
        drag = self.drag
        self.drag = None
        if drag is None:
            return
        if isinstance(drag, _GroupDrag):
            self.scene.clear_transform_preview(drag.target_ids)
            self.scene.set_snap_guides()
            return
        self.scene.preview_state.clear()
        if self.target_item is not None:
            self.target_item.setRect(drag.start_rect)
            self.target_item.setPos(drag.start_pos)
            self.target_item.setRotation(drag.start_rotation)
            self.target_item.setTransformOriginPoint(drag.start_rect.center())
        self.reposition()
        self.scene.set_snap_guides()

    def end_drag(self) -> Optional[dict]:
        drag = self.drag
        self.drag = None
        if drag is None:
            return None
        if isinstance(drag, _GroupDrag):
            values = self._group_preview_transforms(drag)
            changed = any(
                any(
                    abs(getattr(values[instance_id], name) - getattr(start, name)) >= 1e-6
                    for name in ("x", "y", "scale_x", "scale_y", "rotation")
                )
                for instance_id, start in drag.start_transforms.items()
            )
            if not changed:
                self.scene.clear_transform_preview(drag.target_ids)
                return None
            self.scene.preview_state.clear()
            self.reposition()
            return {"group_transforms": {key: value.to_dict() for key, value in values.items()}}
        fields: dict = {}
        if drag.kind == "move":
            new_pos = self.target_item.pos()
            if (
                abs(new_pos.x() - drag.start_transform["x"]) >= 0.5
                or abs(new_pos.y() - drag.start_transform["y"]) >= 0.5
            ):
                fields = {"x": new_pos.x(), "y": new_pos.y()}
        elif drag.kind == "scale":
            rect = self.target_item.rect()
            new_scale_x = rect.width() / drag.image_w
            new_scale_y = rect.height() / drag.image_h
            if (
                abs(new_scale_x - drag.start_transform["scale_x"]) >= 1e-4
                or abs(new_scale_y - drag.start_transform["scale_y"]) >= 1e-4
            ):
                start_center_x = drag.start_transform["x"] + drag.image_w * drag.start_transform["scale_x"] / 2.0
                start_center_y = drag.start_transform["y"] + drag.image_h * drag.start_transform["scale_y"] / 2.0
                fields = {
                    "scale_x": new_scale_x,
                    "scale_y": new_scale_y,
                    "x": start_center_x - drag.image_w * new_scale_x / 2.0,
                    "y": start_center_y - drag.image_h * new_scale_y / 2.0,
                }
        elif drag.kind == "rotate":
            new_rotation = self.target_item.rotation()
            if abs(new_rotation - drag.start_transform["rotation"]) >= 0.5:
                fields = {"rotation": new_rotation}
        if not fields:
            # nothing changed enough to commit -- restore the transient
            # preview exactly like an Esc cancel so a no-op click leaves no
            # visual drift either.
            self.target_item.setRect(drag.start_rect)
            self.target_item.setPos(drag.start_pos)
            self.target_item.setRotation(drag.start_rotation)
            self.target_item.setTransformOriginPoint(drag.start_rect.center())
        self.scene.preview_state.clear()
        self.reposition()
        return fields or None
