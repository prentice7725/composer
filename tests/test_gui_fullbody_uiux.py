from __future__ import annotations

import os
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton
from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow
from .conftest import make_portrait_bundle


@pytest.fixture
def fullbody_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = make_portrait_bundle(tmp_path / "fullbody", size=(120, 480),
                                layers=(("unclassified", (160, 120, 80, 255)),))
    document, sources, warnings = identity_assembly(read_portrait_bundle(path))
    window = MainWindow()
    window._display_document(document, sources, path, source_map=True, import_warnings=warnings)
    window.show()
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)
    app.processEvents()
    yield app, window, instance_id
    window.close()
    app.processEvents()


def test_tall_single_layer_fit_and_transformed_pick_preserve_native_coordinates(fullbody_window):
    app, window, instance_id = fullbody_window
    document = window.document
    revision = document.history.revision
    assert len(document.instances) == 1  # no guessed head/limb segmentation
    window.canvas.fit_canvas()
    window.canvas.fit_selection()
    assert window.canvas.scene_model.sceneRect().width() == 120
    assert window.canvas.scene_model.sceneRect().height() == 480
    item = window.canvas.scene_model._hit_items[instance_id]
    item.setPos(22, 35)
    item.setRotation(27)
    item.setScale(1.5)
    scene_point = item.mapToScene(QPointF(30, 300))
    assert window.canvas.color_pick_point(scene_point, instance_id) == pytest.approx((30, 300))
    assert window.canvas.color_pick_point(QPointF(60, 450)) == (60, 450)
    assert window.canvas.color_pick_point(QPointF(60, 600)) is None
    assert document.history.revision == revision


def test_color_preview_cancel_is_transient_and_apply_is_one_undo(fullbody_window):
    app, window, instance_id = fullbody_window
    source = window.image_sources[instance_id]
    original_bytes = source.read_bytes()
    revision = window.document.history.revision
    window.inspector_dock._color_match()
    dialog = window.inspector_dock.findChild(QDialog)
    buttons = dialog.findChild(QDialogButtonBox)
    next(button for button in buttons.findChildren(QPushButton) if button.text() == "Preview").click()
    assert window.document.history.revision == revision
    dialog.reject()
    app.processEvents()
    assert window.document.history.revision == revision
    assert window.canvas._color_pick is None
    window.inspector_dock._color_match()
    dialog = window.inspector_dock.findChild(QDialog)
    next(button for button in dialog.findChildren(QPushButton)
         if button.text() == "Pick source on canvas").click()
    assert window.canvas._color_pick[0] == instance_id
    # Esc from canvas returns to the same dialog without authoring a change.
    from PySide6.QtGui import QKeyEvent
    window.canvas.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert window.canvas._color_pick is None
    dialog.accept()
    app.processEvents()
    assert window.document.history.revision == revision + 1
    assert len(window.document.instances[instance_id].visual_ops) == 1
    window.undo()
    assert window.document.instances[instance_id].visual_ops == []
    assert source.read_bytes() == original_bytes
