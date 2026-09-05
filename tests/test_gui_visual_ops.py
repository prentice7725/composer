from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QPushButton, QDoubleSpinBox

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.visual_ops import add_visual_op


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_inspector_authors_color_and_quad_warp_without_nameerror(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)

    add_color = next(button for button in window.inspector_dock.findChildren(QPushButton) if button.text() == "Add Color")
    add_color.click()
    assert any(op.get("type") == "color" for op in document.instances[instance_id].visual_ops)

    brightness = next(
        spin for spin in window.inspector_dock.findChildren(QDoubleSpinBox)
        if spin.accessibleName() == "Color brightness"
    )
    brightness.setValue(0.75)
    update_color = next(button for button in window.inspector_dock.findChildren(QPushButton) if button.text() == "Update Color")
    update_color.click()
    color_op = next(op for op in document.instances[instance_id].visual_ops if op.get("type") == "color")
    assert color_op["params"]["brightness"] == pytest.approx(0.75)

    add_quad = next(button for button in window.inspector_dock.findChildren(QPushButton) if button.text() == "Add Quad Warp")
    add_quad.click()
    quad_spin = next(
        spin for spin in window.inspector_dock.findChildren(QDoubleSpinBox)
        if spin.accessibleName() == "Quad warp TL x"
    )
    quad_spin.setValue(2.0)
    update_quad = next(button for button in window.inspector_dock.findChildren(QPushButton) if button.text() == "Update Quad Warp")
    update_quad.click()
    quad_op = next(op for op in document.instances[instance_id].visual_ops if op.get("type") == "quad_warp")
    assert quad_op["params"]["quad"][0] == pytest.approx(2.0)

    assert any(button.text() == "Paint on Canvas" for button in window.inspector_dock.findChildren(QPushButton)) is False
    window.close()


def test_mask_brush_canvas_drag_commits_one_copy_on_write_stroke(qapp, portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    mask_path = tmp_path / "mask.png"
    from PIL import Image

    Image.new("L", (40, 40), 255).save(mask_path)
    add_visual_op(document, instance_id, {"id": "mask", "type": "mask", "params": {"path": str(mask_path)}})
    window.selection_model.select(instance_id)
    window.show()
    qapp.processEvents()

    paint_button = next(button for button in window.inspector_dock.findChildren(QPushButton) if button.text() == "Paint on Canvas")
    paint_button.click()
    assert window.canvas._mask_brush["op_id"] == "mask"

    item = window.canvas.scene_model._hit_items[instance_id]
    view_pos = window.canvas.mapFromScene(item.mapToScene(item.rect().center()))
    global_pos = window.canvas.viewport().mapToGlobal(view_pos)

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(view_pos), QPointF(global_pos),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    window.canvas.mousePressEvent(press)
    move_pos = view_pos + type(view_pos)(3, 0)
    move_global = window.canvas.viewport().mapToGlobal(move_pos)
    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(move_pos), QPointF(move_global),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    window.canvas.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(move_pos), QPointF(move_global),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    revision = document.history.revision
    window.canvas.mouseReleaseEvent(release)
    qapp.processEvents()

    assert document.history.revision == revision + 1
    assert document.instances[instance_id].visual_ops[0]["params"]["path"] != str(mask_path)
    window.close()
