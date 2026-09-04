"""Direct-canvas two_lobe secondary-region editor (C5-F, directive #12.1).

Unlike the C5-B transform gizmo or the C5-E donor ghost, two_lobe geometry
has no rotation and lives in normalized [0,1] target-space, not scene
pixels -- so this controller just remaps normalized<->scene coordinates
through the target instance's current bounding box on every redraw, using
plain axis-aligned ellipse/handle geometry. No QGraphicsItem transform
composition is needed (there's nothing to rotate).

Per lobe: a center handle (move), a right-edge handle (radius X), a
bottom-edge handle (radius Y), and a corner handle (both radii) --
directive #12.1's full handle set. Shift mirrors the edit onto the other
lobe across the region's vertical center (x=0.5 in normalized space) --
"symmetric edit" (#12.1) read in the context of this L/R lobe pair.

Every drag is transient: nothing commits until end_drag() returns the
changed geometry for the view to hand to commands.set_region_geometry.
"""
from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsRectItem

REGION_HANDLE_ROLE = 35
HANDLE_SIZE = 8.0
MIN_RADIUS = 0.02
_SIDES = ("left", "right")
_HANDLE_NAMES = ("center", "right", "bottom", "corner")


class RegionEditController:
    def __init__(self, scene) -> None:
        self.scene = scene
        self.region_id: Optional[str] = None
        self.target_id: Optional[str] = None
        self.geometry: Optional[dict] = None
        self._lobe_items: dict[str, QGraphicsEllipseItem] = {}
        self._handles: dict[tuple[str, str], QGraphicsItem] = {}
        self.drag: Optional[dict] = None

    @property
    def active(self) -> bool:
        return self.geometry is not None

    def show(self, region_id: str, target_id: str, geometry: dict) -> None:
        self.clear()
        self.region_id = region_id
        self.target_id = target_id
        self.geometry = {
            "kind": geometry.get("kind", "two_lobe"),
            "left": {"center": list(geometry["left"]["center"]), "radius": list(geometry["left"]["radius"])},
            "right": {"center": list(geometry["right"]["center"]), "radius": list(geometry["right"]["radius"])},
        }
        for side in _SIDES:
            lobe_item = QGraphicsEllipseItem()
            lobe_item.setPen(QPen(QColor("#c792ff"), 1.5))
            lobe_item.setBrush(QBrush(QColor(199, 146, 255, 40)))
            lobe_item.setZValue(9_200)
            self.scene.addItem(lobe_item)
            self._lobe_items[side] = lobe_item
            for name in _HANDLE_NAMES:
                shape = QGraphicsEllipseItem if name == "center" else QGraphicsRectItem
                handle = shape(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)
                handle.setBrush(QBrush(QColor("#c792ff")))
                handle.setPen(QPen(QColor("#20242b"), 1.0))
                handle.setZValue(10_600)
                handle.setData(REGION_HANDLE_ROLE, (side, name))
                self.scene.addItem(handle)
                self._handles[(side, name)] = handle
        self._redraw()

    def clear(self) -> None:
        for item in self._lobe_items.values():
            self.scene.removeItem(item)
        self._lobe_items = {}
        for handle in self._handles.values():
            self.scene.removeItem(handle)
        self._handles = {}
        self.region_id = None
        self.target_id = None
        self.geometry = None
        self.drag = None

    # -- coordinate mapping -----------------------------------------------
    def _target_box(self):
        """(x, y, width, height) of the target instance in scene pixels, or
        None if the target can't currently be resolved/drawn."""
        document = self.scene.document
        if document is None or self.target_id is None:
            return None
        instance = document.instances.get(self.target_id)
        if instance is None:
            return None
        image_w, image_h = self.scene.image_size(self.target_id)
        return (
            instance.transform.x,
            instance.transform.y,
            image_w * instance.transform.scale_x,
            image_h * instance.transform.scale_y,
        )

    @staticmethod
    def _to_scene(norm_point, box):
        x, y, w, h = box
        return x + norm_point[0] * w, y + norm_point[1] * h

    @staticmethod
    def _to_norm(scene_point, box):
        x, y, w, h = box
        return ((scene_point[0] - x) / w if w else 0.0, (scene_point[1] - y) / h if h else 0.0)

    def _redraw(self) -> None:
        box = self._target_box()
        if box is None or self.geometry is None:
            return
        _, _, box_w, box_h = box
        for side in _SIDES:
            lobe = self.geometry[side]
            cx, cy = self._to_scene(lobe["center"], box)
            rx = lobe["radius"][0] * box_w
            ry = lobe["radius"][1] * box_h
            self._lobe_items[side].setRect(cx - rx, cy - ry, 2 * rx, 2 * ry)
            self._handles[(side, "center")].setPos(cx, cy)
            self._handles[(side, "right")].setPos(cx + rx, cy)
            self._handles[(side, "bottom")].setPos(cx, cy + ry)
            self._handles[(side, "corner")].setPos(cx + rx, cy + ry)

    # -- drag ----------------------------------------------------------
    def hit_role(self, item):
        if item is None:
            return None
        return item.data(REGION_HANDLE_ROLE)

    def begin_drag(self, role: tuple, scene_pos) -> bool:
        if self.geometry is None or self._target_box() is None:
            return False
        side, handle = role
        self.drag = {
            "side": side,
            "handle": handle,
            "start_geometry": copy.deepcopy(self.geometry),
        }
        return True

    def update_drag(self, scene_pos, mirror: bool) -> None:
        box = self._target_box()
        if self.drag is None or box is None or self.geometry is None:
            return
        side = self.drag["side"]
        handle = self.drag["handle"]
        norm_x, norm_y = self._to_norm((scene_pos.x(), scene_pos.y()), box)
        lobe = self.geometry[side]
        if handle == "center":
            lobe["center"] = [norm_x, norm_y]
        elif handle == "right":
            lobe["radius"][0] = max(MIN_RADIUS, abs(norm_x - lobe["center"][0]))
        elif handle == "bottom":
            lobe["radius"][1] = max(MIN_RADIUS, abs(norm_y - lobe["center"][1]))
        elif handle == "corner":
            lobe["radius"][0] = max(MIN_RADIUS, abs(norm_x - lobe["center"][0]))
            lobe["radius"][1] = max(MIN_RADIUS, abs(norm_y - lobe["center"][1]))

        if mirror:
            other_side = "right" if side == "left" else "left"
            other = self.geometry[other_side]
            if handle == "center":
                other["center"] = [1.0 - lobe["center"][0], lobe["center"][1]]
            else:
                other["radius"] = list(lobe["radius"])
        self._redraw()

    def cancel_drag(self) -> None:
        if self.drag is None:
            return
        self.geometry = self.drag["start_geometry"]
        self.drag = None
        self._redraw()

    def end_drag(self) -> Optional[dict]:
        drag = self.drag
        self.drag = None
        if drag is None or self.geometry is None:
            return None
        if self.geometry == drag["start_geometry"]:
            return None
        return copy.deepcopy(self.geometry)
