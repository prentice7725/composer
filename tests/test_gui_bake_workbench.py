"""Qt-backed tests for the C5-G Bake Workbench (directive #31 exit gate).
Skipped entirely when PySide6 isn't installed."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import CAN_BAKE, WARN
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.rig_intent import set_deformation_scope
from portrait_composer.ui.main_window import MainWindow


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


def test_profile_selector_shows_candidates_without_mutating_document(window):
    before = window.document.to_dict()
    window.set_context("BAKE")
    wb = window.bake_workbench

    assert len(wb._cards) >= 1
    assert window.document.to_dict() == before


def test_warn_candidate_requires_explicit_acknowledgement_before_apply(window):
    window.set_context("BAKE")
    wb = window.bake_workbench
    card = wb._cards[0]
    assert card.candidate.analysis.verdict == WARN  # no RigIntent authored on the fixture

    assert card.acknowledge_box is not None
    assert not card.apply_button.isEnabled()
    card.acknowledge_box.setChecked(True)
    assert card.apply_button.isEnabled()
    card.acknowledge_box.setChecked(False)
    assert not card.apply_button.isEnabled()


def test_bake_output_layer_name_is_user_editable_and_used_for_derived_layer(window):
    for instance_id in window.document.instances:
        set_deformation_scope(window.document, instance_id, "rigid")
    window.set_context("BAKE")
    card = window.bake_workbench._cards[0]
    card.output_name.setText("torso_with_handwear_v2")

    assert card._output_name() == "torso_with_handwear_v2"
    assert card.apply_button.isEnabled()
    card._apply()

    derived_id = "torso_with_handwear_v2__instance"
    assert derived_id in window.document.instances
    assert "torso_with_handwear_v2" in window.document.assets


def test_block_candidate_apply_button_stays_disabled(window):
    # PORTRAIT_STATIC excludes nothing here, so force a BLOCK by putting an
    # instance into a VariantSet -- baking a variant member is a hard BLOCK.
    from portrait_composer.ui.commands import add_variant_member

    instance_id = next(iter(window.document.instances))
    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", instance_id, default=True))
    window.set_context("BAKE")
    wb = window.bake_workbench
    card = wb._cards[0]
    assert card.candidate.analysis.verdict != CAN_BAKE
    if card.candidate.analysis.verdict == "BLOCK":
        assert not card.apply_button.isEnabled()
        assert card.acknowledge_box is None


def test_before_after_wipe_flicker_difference_render_from_core_renderer(window):
    window.set_context("BAKE")
    wb = window.bake_workbench
    card = wb._cards[0]
    scene = window.canvas.scene_model

    for mode in ("before", "after", "wipe", "flicker", "difference"):
        button = next(b for b in card.mode_group.buttons() if b.property("mode") == mode)
        button.setChecked(True)
        assert scene._reference_item.pixmap().size().width() > 0
    scene._stop_flicker()


def test_can_bake_apply_is_one_undo_step_and_provenance_visible(window):
    # Author RigIntent for every instance first, so the PORTRAIT_STATIC
    # candidate's dry-run comes back CAN_BAKE instead of WARN.
    for instance_id in window.document.instances:
        set_deformation_scope(window.document, instance_id, "rigid")
    window.set_context("BAKE")
    wb = window.bake_workbench
    wb.refresh()
    card = wb._cards[0]
    assert card.candidate.analysis.verdict == CAN_BAKE
    assert card.apply_button.isEnabled()

    revision_before = window.document.history.revision
    card._apply()

    assert window.document.history.revision == revision_before + 1
    new_ids = [i for i in window.document.instances if i.endswith(f"{card.candidate.label}__instance")]
    assert len(new_ids) == 1
    derived_instance_id = new_ids[0]
    assert window.selection_model.instance_ids == [derived_instance_id]
    records = window.document.provenance.for_target(derived_instance_id)
    assert records and records[-1].operation == "bake"

    window.undo()
    assert derived_instance_id not in window.document.instances
    for instance_id in card.candidate.instance_ids:
        assert window.document.instances[instance_id].visible is True


def test_leaving_bake_context_restores_the_committed_reference(window):
    window.set_context("BAKE")
    wb = window.bake_workbench
    card = wb._cards[0]
    after_button = next(b for b in card.mode_group.buttons() if b.property("mode") == "after")
    after_button.setChecked(True)

    window.set_context("ASSEMBLE")
    scene = window.canvas.scene_model
    # after leaving, the reference pixmap must match the committed render again
    from portrait_composer.ui.canvas.scene import _qimage
    from PySide6.QtGui import QPixmap

    expected = QPixmap.fromImage(_qimage(scene._committed_reference))
    assert scene._reference_item.pixmap().toImage() == expected.toImage()


def test_bake_context_reopens_hidden_workbench_dock(window, qapp):
    window.show()
    qapp.processEvents()
    window.workbench_dock.hide()
    assert not window.workbench_dock.isVisible()

    window.set_context("ASSEMBLE")
    qapp.processEvents()
    assert not window.workbench_dock.isVisible()

    window.set_context("BAKE")
    qapp.processEvents()

    assert window.workbench_dock.isVisible()
    assert abs(window.workbench_dock.height() - window.WORKBENCH_DEFAULT_HEIGHT) <= 20

    view_menu = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "View"
    )
    view_action_texts = {action.text() for action in view_menu.actions()}
    assert "Context Workbench" in view_action_texts
    assert "Diagnostics / Assembly Status" in view_action_texts


def test_bake_candidate_card_uses_available_height_for_sources_and_apply(window, qapp):
    window.show()
    window.set_context("BAKE")
    qapp.processEvents()

    wb = window.bake_workbench
    card = wb._cards[0]
    source_list = card.findChildren(QListWidget)

    assert card.geometry().bottom() >= wb.cards_body.rect().bottom() - 4
    assert source_list and source_list[0].height() >= 80
    assert card.apply_button.geometry().bottom() >= card.height() - 16


def test_bake_staging_edits_order_and_transform_without_mutating_assembly(window, qapp):
    window.show()
    window.set_context("BAKE")
    qapp.processEvents()

    wb = window.bake_workbench
    card = wb._cards[0]
    before = window.document.to_dict()
    original_order = list(card._staged_order)
    selected_id = original_order[0]

    card.sources.setCurrentRow(0)
    card._move_source(1)
    card._toggle_source_editor()
    card.source_fields["x"].setValue(17.0)
    card.source_fields["x"].editingFinished.emit()
    qapp.processEvents()

    assert card._staged_order != original_order
    assert card._staged_transforms[selected_id].x == 17.0
    assert window.document.to_dict() == before

    card._reset_staging()
    assert card._staged_order == original_order
    assert card._staged_transforms[selected_id].x == 0.0
    assert window.document.to_dict() == before


def test_bake_selected_analyzes_the_current_multi_selection(window):
    selected = list(window.document.instances)[:2]
    window.selection_model.set_instances(selected)
    window.set_context("BAKE")
    wb = window.bake_workbench

    assert wb.bake_selected_button.isEnabled()
    wb._analyze_selected()

    assert len(wb._cards) == 1
    assert wb._cards[0].candidate.label == "selected_layers"
    assert wb._cards[0].candidate.instance_ids == selected
