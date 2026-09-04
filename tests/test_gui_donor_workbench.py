"""Qt-backed tests for the C5-E Donor Align Workbench (directive #29 exit
gate). Skipped entirely when PySide6 isn't installed."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
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


def _load_donor(window, donor_path: Path):
    window.donor_workbench._donor_path = donor_path
    image = Image.open(donor_path).convert("RGBA")
    window.donor_workbench._donor_image = image
    target_instance = window.selection_model.instance_ids[0] if window.selection_model.instance_ids else None
    initial = {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}
    window.canvas.scene_model.donor_ghost.show(image, transform=initial, opacity=0.55)
    window.donor_workbench._set_controls_enabled(True)
    return target_instance


def test_donor_ghost_never_mutates_the_document_while_dragging(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)

    before = window.document.to_dict()
    ghost = window.canvas.scene_model.donor_ghost
    ghost.begin_drag(("move", None), QPointF(0, 0))
    ghost.update_drag(QPointF(30, 12), False)
    ghost.update_drag(QPointF(-5, 40), False)
    assert window.document.to_dict() == before  # transient only, per directive #18

    ghost.cancel_drag()
    assert ghost.transform == {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}


def test_metrics_use_core_check_drift_and_hard_drift_blocks_apply(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)
    window.donor_workbench.semantic_field.setText("mouth")

    # push the ghost far away from the target -> hard drift
    ghost = window.canvas.scene_model.donor_ghost
    ghost.transform["x"] = 9999.0
    ghost.transform["y"] = 9999.0

    window.donor_workbench._refresh_metrics()
    assert "✗" in window.donor_workbench.metrics_label.text()

    revision_before = window.document.history.revision
    window.donor_workbench._apply()
    assert window.document.history.revision == revision_before  # blocked, nothing committed
    assert "Edit failed" in window.statusBar().currentMessage()
    assert window.canvas.scene_model.donor_ghost.active  # ghost stays for the user to fix


def test_allow_drift_override_surfaced_and_commits(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)
    window.donor_workbench.semantic_field.setText("mouth")

    ghost = window.canvas.scene_model.donor_ghost
    ghost.transform["x"] = 9999.0
    ghost.transform["y"] = 9999.0
    window.donor_workbench.allow_drift_box.setChecked(True)

    ok = window.donor_workbench._apply()  # returns None but mutates window.document
    assert not window.canvas.scene_model.donor_ghost.active  # cleared after a successful import
    new_instance_ids = [i for i in window.document.instances if i.endswith("__donor__instance")]
    assert len(new_instance_ids) == 1
    assert window.selection_model.instance_ids == new_instance_ids


def test_undo_removes_the_imported_donor_cleanly(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    # The synthetic donor is a different size than the (full-canvas) target,
    # so a plain identity placement legitimately drifts -- this test is
    # about undo cleanliness, not alignment precision, so allow it through.
    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)
    window.donor_workbench.semantic_field.setText("mouth")
    window.donor_workbench.allow_drift_box.setChecked(True)
    instances_before = set(window.document.instances)

    window.donor_workbench._apply()
    new_ids = set(window.document.instances) - instances_before
    assert len(new_ids) == 1

    window.undo()
    assert set(window.document.instances) == instances_before


def test_preview_modes_do_not_crash_and_restore_on_composite(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)

    scene = window.canvas.scene_model
    for mode in ("target_only", "donor_only", "flicker", "difference", "composite"):
        scene.set_donor_preview_mode(mode)
    assert scene._reference_item.isVisible()
    assert scene.donor_ghost._pixmap_item.isVisible()


def test_leaving_donor_context_clears_the_ghost(window, tmp_path: Path):
    target = next(iter(window.document.instances))
    window.selection_model.select(target)
    window.set_context("DONOR")

    donor_path = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (200, 40, 40, 255)).save(donor_path)
    _load_donor(window, donor_path)
    assert window.canvas.scene_model.donor_ghost.active

    window.set_context("ASSEMBLE")
    assert not window.canvas.scene_model.donor_ghost.active
