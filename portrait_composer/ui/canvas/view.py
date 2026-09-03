"""Interactive pan/zoom view; document transforms are C5-B, not C5-A."""
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
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QGraphicsView { border: 0; }")

    def load_document(self, document, layers_dir) -> None:
        self.scene_model.load_document(document, layers_dir)
        self.fit_canvas()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.session.canvas_pan = (
            float(self.horizontalScrollBar().value()),
            float(self.verticalScrollBar().value()),
        )

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            instance_id = item.data(INSTANCE_ROLE)
            if instance_id:
                self.selection_model.select(
                    str(instance_id),
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                )
        super().mousePressEvent(event)

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

    def fit_selection(self) -> None:
        rects = [item.sceneBoundingRect() for item in self.scene_model._hit_items.values() if item.isSelected()]
        if rects:
            rect = rects[0]
            for other in rects[1:]:
                rect = rect.united(other)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.fit_canvas()
            else:
                self.fit_selection()
            event.accept()
            return
        super().keyPressEvent(event)
