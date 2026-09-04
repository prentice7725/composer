"""Qt-backed tests for the C5-B canvas gizmo and MainWindow command wiring.

Runs offscreen (no visible window needed). Skipped entirely when PySide6
isn't installed, matching the project's optional GUI dependency.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle, write_assembly_bundle
from portrait_composer.ui.canvas.scene import CanvasScene
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.ui.session import SelectionModel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


class _FakeSelection:
    def subscribe(self, listener) -> None:
        pass

    instance_ids: list = []


def test_scene_loads_a_freshly_imported_portrait_bundle_without_crashing(qapp, portrait_bundle: Path):
    """Regression test: load_document used to raise UnboundLocalError for
    ``order`` on this exact path (a Portrait Bundle imported through
    identity_assembly, which uses image_sources rather than the on-disk
    layers/ convention)."""
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)

    scene = CanvasScene(_FakeSelection())
    scene.load_document(document, portrait_bundle, image_sources)

    assert len(scene._hit_items) == len(document.instances)
    for instance_id in document.instances:
        width, height = scene.image_size(instance_id)
        assert width > 0 and height > 0


def test_main_window_run_command_refreshes_and_preserves_selection(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)

    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)

    from portrait_composer.ui.commands import set_instance_transform

    ok = window.run_command(
        lambda doc, srcs: set_instance_transform(doc, srcs, instance_id, x=33.0, y=-7.0)
    )

    assert ok is True
    assert window.document.instances[instance_id].transform.x == 33.0
    assert window.selection_model.instance_ids == [instance_id]
    # canvas/tree/inspector all rebuilt from the committed document
    assert instance_id in window.canvas.scene_model._hit_items
    item = window.canvas.scene_model._hit_items[instance_id]
    assert item.pos().x() == 33.0


def test_main_window_run_command_survives_before_first_save(qapp, portrait_bundle: Path):
    """A gizmo edit right after Import (bundle_path is still None) must not
    silently no-op -- this was a latent bug in _refresh_after_document_change."""
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)

    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    assert window.bundle_path is None

    instance_id = next(iter(document.instances))
    from portrait_composer.ui.commands import set_instance_visible

    ok = window.run_command(lambda doc, srcs: set_instance_visible(doc, srcs, instance_id, False))
    assert ok is True
    assert window.document.instances[instance_id].visible is False

    window.undo()
    assert window.document.instances[instance_id].visible is True


def test_run_command_reports_failure_without_a_modal_dialog(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)

    def boom(doc, srcs):
        raise KeyError("no such instance: 'missing'")

    ok = window.run_command(boom)
    assert ok is False
    assert "Edit failed" in window.statusBar().currentMessage()


def test_gizmo_move_drag_commits_one_transaction_and_esc_is_a_document_noop(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)

    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)

    gizmo = window.canvas.scene_model.gizmo
    assert gizmo.instance_id == instance_id
    before = document.to_dict()
    revision_before = document.history.revision

    # Esc-style cancel: begin a move, nudge it, then cancel -- document must
    # be byte-identical (the drag never touched it).
    gizmo.begin_drag(("move", None), QPointF(0.0, 0.0))
    gizmo.update_drag(QPointF(15.0, 9.0), False)
    gizmo.cancel_drag()
    assert document.to_dict() == before
    assert document.history.revision == revision_before

    # A real drag-and-release commits exactly once through run_command.
    gizmo.begin_drag(("move", None), QPointF(0.0, 0.0))
    gizmo.update_drag(QPointF(20.0, -6.0), False)
    fields = gizmo.end_drag()
    assert fields == {"x": 20.0, "y": -6.0}

    from portrait_composer.ui.commands import set_instance_transform

    window.run_command(lambda doc, srcs: set_instance_transform(doc, srcs, instance_id, **fields))
    assert document.instances[instance_id].transform.x == 20.0
    assert document.instances[instance_id].transform.y == -6.0
    assert document.history.revision == revision_before + 1


def test_gizmo_scale_drag_is_center_anchored(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)

    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)

    gizmo = window.canvas.scene_model.gizmo
    item = gizmo.target_item
    image_w, image_h = window.canvas.scene_model.image_size(instance_id)
    start_center = item.mapToScene(item.rect().center())

    gizmo.begin_drag(("scale", "bottom_right"), item.mapToScene(item.rect().bottomRight()))
    corner_target = item.mapToScene(item.rect().bottomRight()) + QPointF(image_w / 2.0, image_h / 2.0)
    gizmo.update_drag(corner_target, False)
    fields = gizmo.end_drag()

    assert fields is not None
    assert fields["scale_x"] == pytest.approx(2.0, abs=0.05)
    assert fields["scale_y"] == pytest.approx(2.0, abs=0.05)
    # center stays put under a center-anchored scale
    new_center = QPointF(
        fields["x"] + image_w * fields["scale_x"] / 2.0,
        fields["y"] + image_h * fields["scale_y"] / 2.0,
    )
    assert new_center.x() == pytest.approx(start_center.x(), abs=0.5)
    assert new_center.y() == pytest.approx(start_center.y(), abs=0.5)


def test_tree_visibility_checkbox_commits_through_run_command(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))

    from PySide6.QtCore import Qt

    from portrait_composer.ui.models.assembly_tree import INSTANCE_ROLE

    row = None
    for r in range(window.tree_dock.model.rowCount()):
        item = window.tree_dock.model.item(r)
        if item.data(INSTANCE_ROLE) == instance_id:
            row = item
            break
    assert row is not None
    row.setCheckState(Qt.CheckState.Unchecked)

    assert window.document.instances[instance_id].visible is False


def test_draw_order_nudge_shortcut_moves_selected_instance(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    first = document.composition["draw_order"][0]
    window.selection_model.select(first)

    window._nudge_draw_order(to_extreme=1)

    assert window.document.composition["draw_order"][-1] == first


def test_tree_drop_reorders_draw_order_in_one_transaction(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    first = document.composition["draw_order"][0]
    before_revision = document.history.revision
    window.selection_model.select(first)

    class _DropAtEnd:
        def position(self):
            return QPointF(2.0, 10000.0)

    assert window.tree_dock._drop_reorder(_DropAtEnd()) is True
    assert document.composition["draw_order"][-1] == first
    assert document.history.revision == before_revision + 1
    window.undo()
    assert document.composition["draw_order"][0] == first


def test_inspector_slot_and_plane_controls_commit(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)

    from PySide6.QtWidgets import QComboBox

    boxes = window.inspector_dock.findChildren(QComboBox)
    assert len(boxes) == 2
    slot_box, plane_box = boxes
    slot_box.setCurrentText("torso")
    slot_box.lineEdit().editingFinished.emit()
    assert document.instances[instance_id].slot == "torso"

    plane = document.assets[document.instances[instance_id].asset_ref].planes[0]
    plane_box = window.inspector_dock.findChildren(QComboBox)[1]
    plane_index = plane_box.findData(plane)
    plane_box.activated[int].emit(plane_index)
    assert document.instances[instance_id].plane == plane


def test_save_after_gizmo_edit_matches_core_reference_on_reopen(qapp, portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))

    from portrait_composer.ui.commands import set_instance_transform

    window.run_command(lambda doc, srcs: set_instance_transform(doc, srcs, instance_id, x=5.0, y=5.0))

    target = tmp_path / "out.assembly"
    write_assembly_bundle(window.document, window.image_sources, target)

    reopened = MainWindow()
    reopened.load_bundle(target)
    assert reopened.document.instances[instance_id].transform.x == 5.0
