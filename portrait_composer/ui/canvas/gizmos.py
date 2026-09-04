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
    inverse: object = None
    center_scene: Optional[QPointF] = None
    start_angle: float = 0.0


class TransformGizmo:
    """Owns the handle QGraphicsItems for the current single selection."""

    def __init__(self, scene) -> None:
        self.scene = scene
        self.instance_id: Optional[str] = None
        self.target_item: Optional[QGraphicsRectItem] = None
        self._handles: dict[str, QGraphicsItem] = {}
        self.drag: Optional[_Drag] = None

    # -- lifecycle -----------------------------------------------------
    def attach(self, instance_id: str, item: QGraphicsRectItem) -> None:
        if self.instance_id == instance_id and self.target_item is item:
            self.reposition()
            return
        self.detach()
        self.instance_id = instance_id
        self.target_item = item
        for name in _CORNERS:
            handle = QGraphicsRectItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
            handle.setBrush(QBrush(QColor("#ffd166")))
            handle.setPen(QPen(QColor("#20242b"), 1.0))
            handle.setZValue(10_000)
            handle.setData(GIZMO_ROLE, _encode_role("scale", name))
            self.scene.addItem(handle)
            self._handles[name] = handle
        rotate_handle = QGraphicsEllipseItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
        rotate_handle.setBrush(QBrush(QColor("#59d4ff")))
        rotate_handle.setPen(QPen(QColor("#20242b"), 1.0))
        rotate_handle.setZValue(10_000)
        rotate_handle.setData(GIZMO_ROLE, _encode_role("rotate"))
        self.scene.addItem(rotate_handle)
        self._handles["rotate"] = rotate_handle
        self.reposition()

    def detach(self) -> None:
        for handle in self._handles.values():
            self.scene.removeItem(handle)
        self._handles.clear()
        self.instance_id = None
        self.target_item = None
        self.drag = None

    def reposition(self) -> None:
        if self.target_item is None or self.drag is not None or not self._handles:
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
        top_center = QPointF((rect.left() + rect.right()) / 2.0, rect.top() - ROTATE_OFFSET)
        self._handles["rotate"].setPos(self.target_item.mapToScene(top_center))

    # -- drag ------------------------------------------------------------
    def hit_role(self, item) -> Optional[tuple[str, str | None]]:
        if item is None:
            return None
        return _decode_role(item.data(GIZMO_ROLE))

    def begin_drag(self, role: tuple, scene_pos: QPointF) -> bool:
        if self.target_item is None or self.instance_id is None:
            return False
        instance = self.scene.document.instances.get(self.instance_id)
        if instance is None:
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
        )
        if kind == "scale":
            inverse, invertible = self.target_item.sceneTransform().inverted()
            drag.inverse = inverse if invertible else None
        elif kind == "rotate":
            drag.center_scene = self.target_item.mapToScene(drag.start_rect.center())
            delta = scene_pos - drag.center_scene
            drag.start_angle = math.degrees(math.atan2(delta.y(), delta.x()))
        self.drag = drag
        return True

    def update_drag(self, scene_pos: QPointF, preserve_aspect: bool) -> None:
        drag = self.drag
        if drag is None or self.target_item is None:
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

    def cancel_drag(self) -> None:
        drag = self.drag
        self.drag = None
        if drag is None or self.target_item is None:
            return
        self.target_item.setRect(drag.start_rect)
        self.target_item.setPos(drag.start_pos)
        self.target_item.setRotation(drag.start_rotation)
        self.target_item.setTransformOriginPoint(drag.start_rect.center())
        self.reposition()

    def end_drag(self) -> Optional[dict]:
        drag = self.drag
        self.drag = None
        if drag is None:
            return None
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
        self.reposition()
        return fields or None
