"""Core-rendered reference scene with lightweight selection hit regions."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene

from ...render import render_reference


INSTANCE_ROLE = 32


def _qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    return QImage(raw, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()


class CanvasScene(QGraphicsScene):
    def __init__(self, selection_model, parent=None):
        super().__init__(parent)
        self.selection_model = selection_model
        self.document = None
        self.layers_dir: Path | None = None
        self.context = "ASSEMBLE"
        self._reference_item: QGraphicsPixmapItem | None = None
        self._hit_items: dict[str, QGraphicsRectItem] = {}
        selection_model.subscribe(self._refresh_selection)
        self.setBackgroundBrush(QBrush(QColor("#20242b"), Qt.BrushStyle.Dense6Pattern))

    def load_document(self, document, layers_dir: Path) -> None:
        self.document = document
        self.layers_dir = Path(layers_dir)
        self.clear()
        self._hit_items = {}
        canvas = document.composition.get("canvas") or {}
        width, height = canvas.get("width"), canvas.get("height")
        reference = render_reference(document, self.layers_dir)
        width, height = reference.size if width is None or height is None else (width, height)
        self._reference_item = self.addPixmap(QPixmap.fromImage(_qimage(reference)))
        self._reference_item.setZValue(-1000)
        self.setSceneRect(0, 0, width, height)

        order = document.composition.get("draw_order", [])
        for index, instance_id in enumerate(order):
            inst = document.instances.get(instance_id)
            if inst is None or not inst.visible or inst.opacity <= 0:
                continue
            bounds = self._instance_bounds(instance_id, width, height)
            item = self.addRect(
                QRectF(*bounds),
                QPen(QColor("#59d4ff"), 1.5),
                # Transparent fill keeps the whole instance bounds clickable;
                # NoBrush would make interior hit testing implementation-dependent.
                QBrush(QColor(0, 0, 0, 0)),
            )
            item.setData(INSTANCE_ROLE, instance_id)
            item.setZValue(index)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._hit_items[instance_id] = item
        self._refresh_selection(self.selection_model.instance_ids)

    def _instance_bounds(self, instance_id: str, width: int, height: int) -> tuple[float, float, float, float]:
        inst = self.document.instances[instance_id]
        image_path = self.layers_dir / f"{instance_id}.png"
        if image_path.exists():
            with Image.open(image_path) as image:
                image_width, image_height = image.size
        else:
            image_width, image_height = width, height
        return (
            inst.transform.x,
            inst.transform.y,
            max(1, image_width * inst.transform.scale_x),
            max(1, image_height * inst.transform.scale_y),
        )

    def _refresh_selection(self, selected_ids: list[str]) -> None:
        for instance_id, item in self._hit_items.items():
            active = instance_id in selected_ids
            item.setPen(QPen(QColor("#ffd166" if active else "#59d4ff"), 2.0 if active else 1.0))
            item.setSelected(active)

    def set_context(self, context: str) -> None:
        self.context = context
