"""Interactive donor ghost overlay for the C5-E Donor Align workspace.

The move/scale/rotate math here deliberately mirrors gizmos.py's
center-anchored scale and frozen-inverse-transform rotation -- but a donor
isn't a committed AssemblyDocument instance yet (that's the whole point of
aligning it *before* import), so there's nothing to attach the C5-B
TransformGizmo to. This is a small, self-contained twin instead of forcing
a shared abstraction onto two genuinely different backing models.

Every drag here is Qt-only transient state, same as gizmos.py: nothing
commits until DonorWorkbench.apply() calls donors.import_donor with the
final alignment. Esc during a drag simply restores the pre-drag transform
dict -- no document is ever involved.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
)

DONOR_HANDLE_ROLE = 34
HANDLE_SIZE = 9.0
ROTATE_OFFSET = 28.0
MIN_EXTENT = 4.0
_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")


def identity_transform() -> dict:
    return {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}


@dataclass
class _Drag:
    kind: str
    start_scene_pos: QPointF
    start_transform: dict
    inverse: object = None
    center_scene: Optional[QPointF] = None
    start_angle: float = 0.0


class DonorAlignController:
    """Owns the transient donor ghost pixmap + its handles."""

    def __init__(self, scene, qimage_fn) -> None:
        self.scene = scene
        self._qimage = qimage_fn  # PIL.Image -> QImage, shared with CanvasScene
        self.image: Optional[Image.Image] = None
        self.transform: dict = identity_transform()
        self.opacity = 0.55
        self.target_roi: dict | None = None
        self.target_rotation = 0.0
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._target_box: Optional[QGraphicsRectItem] = None
        self._donor_box: Optional[QGraphicsRectItem] = None
        self._target_crosshair: list[QGraphicsLineItem] = []
        self._donor_crosshair: list[QGraphicsLineItem] = []
        self._handles: dict[str, QGraphicsItem] = {}
        self.drag: Optional[_Drag] = None

    @property
    def active(self) -> bool:
        return self._pixmap_item is not None

    def show(
        self,
        image: Image.Image,
        *,
        transform: dict | None = None,
        opacity: float = 0.55,
        target_roi: dict | None = None,
        target_rotation: float = 0.0,
    ) -> None:
        self.clear()
        self.image = image
        self.transform = dict(transform) if transform else identity_transform()
        self.opacity = opacity
        self.target_roi = dict(target_roi) if target_roi else None
        self.target_rotation = float(target_rotation)
        if self.target_roi:
            self._target_box = QGraphicsRectItem()
            self._target_box.setPen(QPen(QColor("#59d4ff"), 2.0, Qt.PenStyle.DashLine))
            self._target_box.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._target_box.setZValue(8_900)
            self.scene.addItem(self._target_box)
            self._target_crosshair = self._make_crosshair(QColor("#59d4ff"), 12.0, 8_950)
        self._donor_box = QGraphicsRectItem()
        self._donor_box.setPen(QPen(QColor("#7fffa0"), 1.5, Qt.PenStyle.DotLine))
        self._donor_box.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._donor_box.setZValue(9_050)
        self.scene.addItem(self._donor_box)
        self._donor_crosshair = self._make_crosshair(QColor("#7fffa0"), 10.0, 9_100)
        self._pixmap_item = self.scene.addPixmap(QPixmap())
        self._pixmap_item.setZValue(9_000)
        for name in _CORNERS:
            handle = QGraphicsRectItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
            handle.setBrush(QBrush(QColor("#7fffa0")))
            handle.setPen(QPen(QColor("#20242b"), 1.0))
            handle.setZValue(10_500)
            handle.setData(DONOR_HANDLE_ROLE, ("scale", name))
            self.scene.addItem(handle)
            self._handles[name] = handle
        rotate_handle = QGraphicsEllipseItem(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
        rotate_handle.setBrush(QBrush(QColor("#7fffa0")))
        rotate_handle.setPen(QPen(QColor("#20242b"), 1.0))
        rotate_handle.setZValue(10_500)
        rotate_handle.setData(DONOR_HANDLE_ROLE, ("rotate", None))
        self.scene.addItem(rotate_handle)
        self._handles["rotate"] = rotate_handle
        self._redraw()

    def clear(self) -> None:
        if self._pixmap_item is not None:
            self.scene.removeItem(self._pixmap_item)
            self._pixmap_item = None
        for handle in self._handles.values():
            self.scene.removeItem(handle)
        self._handles = {}
        for item in (self._target_box, self._donor_box):
            if item is not None:
                self.scene.removeItem(item)
        for item in (*self._target_crosshair, *self._donor_crosshair):
            self.scene.removeItem(item)
        self._target_box = None
        self._donor_box = None
        self._target_crosshair = []
        self._donor_crosshair = []
        self.target_roi = None
        self.image = None
        self.drag = None

    def _make_crosshair(self, color: QColor, extent: float, z_value: float) -> list[QGraphicsLineItem]:
        lines = [
            QGraphicsLineItem(-extent, 0.0, extent, 0.0),
            QGraphicsLineItem(0.0, -extent, 0.0, extent),
        ]
        for line in lines:
            line.setPen(QPen(color, 1.25))
            line.setZValue(z_value)
            self.scene.addItem(line)
        return lines

    @staticmethod
    def _place_crosshair(lines: list[QGraphicsLineItem], point: QPointF) -> None:
        for line in lines:
            line.setPos(point)

    def set_opacity(self, opacity: float) -> None:
        self.opacity = opacity
        if self._pixmap_item is not None:
            self._pixmap_item.setOpacity(opacity)

    def set_visible(self, visible: bool) -> None:
        if self._pixmap_item is not None:
            self._pixmap_item.setVisible(visible)
        for handle in self._handles.values():
            handle.setVisible(visible)

    def _scaled_size(self) -> tuple[float, float]:
        w, h = self.image.size
        t = self.transform
        return max(1.0, w * t["scale_x"]), max(1.0, h * t["scale_y"])

    def _redraw(self) -> None:
        if self._pixmap_item is None or self.image is None:
            return
        scaled_w, scaled_h = self._scaled_size()
        pixmap = QPixmap.fromImage(self._qimage(self.image)).scaled(
            max(1, round(scaled_w)),
            max(1, round(scaled_h)),
        )
        self._pixmap_item.setPixmap(pixmap)
        self._pixmap_item.setOpacity(self.opacity)
        self._pixmap_item.setPos(self.transform["x"], self.transform["y"])
        self._pixmap_item.setTransformOriginPoint(scaled_w / 2.0, scaled_h / 2.0)
        self._pixmap_item.setRotation(self.transform["rotation"])
        if self._donor_box is not None:
            self._donor_box.setRect(0.0, 0.0, scaled_w, scaled_h)
            self._donor_box.setPos(self.transform["x"], self.transform["y"])
            self._donor_box.setTransformOriginPoint(scaled_w / 2.0, scaled_h / 2.0)
            self._donor_box.setRotation(self.transform["rotation"])
            donor_center = self._pixmap_item.mapToScene(QPointF(scaled_w / 2.0, scaled_h / 2.0))
            self._place_crosshair(self._donor_crosshair, donor_center)
        if self._target_box is not None and self.target_roi is not None:
            width = float(self.target_roi.get("width", 0.0))
            height = float(self.target_roi.get("height", 0.0))
            self._target_box.setRect(0.0, 0.0, width, height)
            self._target_box.setPos(float(self.target_roi.get("x", 0.0)), float(self.target_roi.get("y", 0.0)))
            self._target_box.setTransformOriginPoint(width / 2.0, height / 2.0)
            self._target_box.setRotation(self.target_rotation)
            target_center = QPointF(
                float(self.target_roi.get("x", 0.0)) + width / 2.0,
                float(self.target_roi.get("y", 0.0)) + height / 2.0,
            )
            self._place_crosshair(self._target_crosshair, target_center)
        self._reposition_handles(scaled_w, scaled_h)

    def _reposition_handles(self, scaled_w: float, scaled_h: float) -> None:
        if not self._handles or self._pixmap_item is None:
            return
        rect = QRectF(0, 0, scaled_w, scaled_h)
        points = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        for name, local_point in points.items():
            self._handles[name].setPos(self._pixmap_item.mapToScene(local_point))
        top_center = QPointF((rect.left() + rect.right()) / 2.0, rect.top() - ROTATE_OFFSET)
        self._handles["rotate"].setPos(self._pixmap_item.mapToScene(top_center))

    # -- drag ------------------------------------------------------------
    def hit_role(self, item) -> Optional[tuple]:
        if item is None:
            return None
        return item.data(DONOR_HANDLE_ROLE)

    def begin_drag(self, role: tuple, scene_pos: QPointF) -> bool:
        if self._pixmap_item is None:
            return False
        kind, _corner = role
        drag = _Drag(kind=kind, start_scene_pos=QPointF(scene_pos), start_transform=dict(self.transform))
        if kind == "scale":
            inverse, invertible = self._pixmap_item.sceneTransform().inverted()
            drag.inverse = inverse if invertible else None
        elif kind == "rotate":
            scaled_w, scaled_h = self._scaled_size()
            center_local = QPointF(scaled_w / 2.0, scaled_h / 2.0)
            drag.center_scene = self._pixmap_item.mapToScene(center_local)
            delta = scene_pos - drag.center_scene
            drag.start_angle = math.degrees(math.atan2(delta.y(), delta.x()))
        self.drag = drag
        return True

    def update_drag(self, scene_pos: QPointF, preserve_aspect: bool) -> None:
        drag = self.drag
        if drag is None or self.image is None:
            return
        image_w, image_h = self.image.size
        if drag.kind == "move":
            delta = scene_pos - drag.start_scene_pos
            self.transform["x"] = drag.start_transform["x"] + delta.x()
            self.transform["y"] = drag.start_transform["y"] + delta.y()
        elif drag.kind == "scale":
            if drag.inverse is None:
                return
            local_pt = drag.inverse.map(scene_pos)
            start_w = image_w * drag.start_transform["scale_x"]
            start_h = image_h * drag.start_transform["scale_y"]
            center_local = QPointF(start_w / 2.0, start_h / 2.0)
            offset_x = abs(local_pt.x() - center_local.x())
            offset_y = abs(local_pt.y() - center_local.y())
            new_w = max(MIN_EXTENT, 2.0 * offset_x)
            new_h = max(MIN_EXTENT, 2.0 * offset_y)
            if preserve_aspect:
                ratio = max(new_w / image_w, new_h / image_h)
                new_w, new_h = image_w * ratio, image_h * ratio
            self.transform["scale_x"] = new_w / image_w
            self.transform["scale_y"] = new_h / image_h
        elif drag.kind == "rotate":
            delta = scene_pos - drag.center_scene
            current_angle = math.degrees(math.atan2(delta.y(), delta.x()))
            self.transform["rotation"] = drag.start_transform["rotation"] + (current_angle - drag.start_angle)
        self._redraw()

    def cancel_drag(self) -> None:
        drag = self.drag
        self.drag = None
        if drag is None:
            return
        self.transform = dict(drag.start_transform)
        self._redraw()

    def end_drag(self) -> None:
        self.drag = None
