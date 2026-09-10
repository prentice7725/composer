from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QToolButton

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.donor_slots import set_donor_slot
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.variants import add_variant_set


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def test_inspector_keeps_low_level_fields_behind_advanced(window, qapp):
    instance_id = next(iter(window.document.instances))
    window.selection_model.select(instance_id)
    qapp.processEvents()
    advanced = next(
        button for button in window.inspector_dock.findChildren(QToolButton)
        if button.accessibleName() == "Show advanced inspector controls"
    )
    slot = next(
        combo for combo in window.inspector_dock.findChildren(QComboBox)
        if combo.accessibleName() == "Instance slot"
    )
    assert not slot.isVisible()
    advanced.click()
    assert slot.isVisible()


def test_prepare_rig_exposes_three_readiness_checks(window):
    window._enter_production_context("BAKE")
    assert window.bake_workbench.readiness_labels["torso"].text().startswith("Torso: ")
    assert window.bake_workbench.readiness_labels["expressions"].text().startswith("Expressions: ")
    assert window.bake_workbench.readiness_labels["autorig"].text().startswith("AutoRig Preflight: ")


def test_blink_and_talk_tests_are_transient(window):
    ids = list(window.document.instances)[:2]
    eyes, mouth = ids
    with window.document.transaction():
        add_variant_set(window.document, "eyes_state", members=[eyes], default=eyes)
        add_variant_set(window.document, "mouth_state", members=[mouth], default=mouth)
    set_donor_slot(window.document, "eyes", "closed", eyes)
    set_donor_slot(window.document, "mouth", "a", mouth)
    revision = window.document.history.revision
    window.donor_workbench._preview_articulation("blink")
    assert window.document.history.revision == revision
    assert "Blink Test preview is transient" in window.statusBar().currentMessage()
    window.donor_workbench._preview_articulation("talk")
    assert window.document.history.revision == revision
    assert "Talk Test preview is transient" in window.statusBar().currentMessage()
