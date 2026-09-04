"""Qt-backed tests for the C5-F RigIntent Workbench (directive #30 exit
gate). Skipped entirely when PySide6 isn't installed."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QRadioButton

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.rig_intent import ATTACHMENT_MODES, DEFORMATION_SCOPES
from portrait_composer.secondary_regions import PREFLIGHT_DEGRADED, PREFLIGHT_READY, UPPER_TORSO_SECONDARY
from portrait_composer.ui.main_window import MainWindow

FORBIDDEN_PHYSICS_TERMS = ("stiffness", "damping", "spring_mass", "spring mass", "solver", "physics_tick", "physics tick")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, portrait_bundle: Path) -> MainWindow:
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    return window


def test_all_five_deformation_scopes_authorable_via_click(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench

    for scope in DEFORMATION_SCOPES:
        button = next(b for b in wb.scope_group.buttons() if b.property("scope") == scope)
        button.setChecked(True)
        assert window.document.rig_intent["deformation_scopes"][target] == scope


def test_all_four_attachment_modes_authorable_via_ui(window):
    ids = list(window.document.instances)
    child, target = ids[0], ids[1]
    window.selection_model.select(child)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench

    index = wb.target_selector.findData(target)
    assert index >= 0
    wb.target_selector.setCurrentIndex(index)

    for mode in ATTACHMENT_MODES:
        mode_index = wb.mode_selector.findData(mode)
        wb.mode_selector.setCurrentIndex(mode_index)
        wb._set_attachment()
        attachment_id = f"{child}__to__{target}"
        assert window.document.rig_intent["attachments"][attachment_id]["mode"] == mode


def test_no_physics_vocabulary_appears_anywhere_in_the_workbench(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()

    texts = []
    for widget_type in (QLabel, QPushButton, QRadioButton):
        for widget in wb.findChildren(widget_type):
            texts.append(widget.text().lower())
            tooltip = widget.toolTip()
            if tooltip:
                texts.append(tooltip.lower())
    blob = " ".join(texts)
    for term in FORBIDDEN_PHYSICS_TERMS:
        assert term not in blob, f"found forbidden physics term {term!r} in RigIntent workbench UI"


def test_region_add_shows_two_lobe_overlay_and_geometry_editable_on_canvas(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()

    region_edit = window.canvas.scene_model.region_edit
    assert region_edit.active
    assert region_edit.region_id == UPPER_TORSO_SECONDARY

    before = window.document.to_dict()
    revision_before = window.document.history.revision
    region_edit.begin_drag(("left", "center"), QPointF(0, 0))
    region_edit.update_drag(QPointF(15, 15), False)
    geometry = region_edit.end_drag()
    assert geometry is not None
    assert geometry["left"]["center"] != [0.39, 0.36]

    from portrait_composer.ui.commands import set_region_geometry

    window.run_command(lambda doc, srcs: set_region_geometry(doc, srcs, UPPER_TORSO_SECONDARY, geometry))
    assert window.document.history.revision == revision_before + 1
    assert window.document.rig_intent["regions"][UPPER_TORSO_SECONDARY]["geometry"] == geometry
    assert window.document.to_dict() != before


def test_shift_mirror_updates_the_other_lobe(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()

    region_edit = window.canvas.scene_model.region_edit
    right_radius_before = list(region_edit.geometry["right"]["radius"])
    region_edit.begin_drag(("left", "corner"), QPointF(0, 0))
    region_edit.update_drag(QPointF(999, 999), True)  # mirror=True
    assert region_edit.geometry["right"]["radius"] == region_edit.geometry["left"]["radius"]
    assert region_edit.geometry["right"]["radius"] != right_radius_before
    region_edit.cancel_drag()


def test_preflight_status_shown_faithfully_ready_then_degraded(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope, set_instance_visible

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()
    assert wb.preflight_label.text().startswith(PREFLIGHT_READY)

    window.run_command(lambda doc, srcs: set_instance_visible(doc, srcs, target, False))
    wb.refresh()
    assert not wb.preflight_label.text().startswith(PREFLIGHT_READY)


def test_leaving_rig_intent_context_clears_the_region_overlay(window):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()
    assert window.canvas.scene_model.region_edit.active

    window.set_context("ASSEMBLE")
    assert not window.canvas.scene_model.region_edit.active


def test_real_mouse_drag_on_a_handle_commits_through_the_actual_view_wiring(window):
    """Regression test: CanvasView._commit_region_geometry once called
    set_region_geometry with the wrong argument count (missing
    image_sources), which run_command silently swallowed as a failed
    edit -- a drag would visibly move the handle but never actually
    commit. Drives real QMouseEvents through CanvasView, not the
    controller or the command function directly, so this wiring bug
    can't hide behind a test that bypasses it."""
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("RIG INTENT")
    wb = window.rig_intent_workbench
    from portrait_composer.ui.commands import set_deformation_scope

    window.run_command(lambda doc, srcs: set_deformation_scope(doc, srcs, target, "secondary"))
    wb._add_region()
    window.resize(800, 600)
    window.show()
    QApplication.instance().processEvents()

    region_edit = window.canvas.scene_model.region_edit
    handle_item = region_edit._handles[("right", "bottom")]
    view_pt = window.canvas.mapFromScene(handle_item.pos())
    global_pt = window.canvas.viewport().mapToGlobal(view_pt)
    before_geometry = window.document.rig_intent["regions"][UPPER_TORSO_SECONDARY]["geometry"]
    revision_before = window.document.history.revision

    def send(event_type, pos, buttons, button=Qt.MouseButton.LeftButton):
        global_pos = window.canvas.viewport().mapToGlobal(pos)
        event = QMouseEvent(event_type, QPointF(pos), QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)
        window.canvas.mousePressEvent(event) if event_type == QEvent.Type.MouseButtonPress else (
            window.canvas.mouseMoveEvent(event) if event_type == QEvent.Type.MouseMove else window.canvas.mouseReleaseEvent(event)
        )

    send(QEvent.Type.MouseButtonPress, view_pt, Qt.MouseButton.LeftButton)
    move_pt = view_pt + type(view_pt)(10, 6)
    send(QEvent.Type.MouseMove, move_pt, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseButtonRelease, move_pt, Qt.MouseButton.NoButton, button=Qt.MouseButton.LeftButton)
    QApplication.instance().processEvents()

    assert "Edit failed" not in window.statusBar().currentMessage()
    assert window.document.history.revision == revision_before + 1
    assert window.document.rig_intent["regions"][UPPER_TORSO_SECONDARY]["geometry"] != before_geometry
