from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.diagnostics import collect_diagnostics
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.ui.models.assembly_tree import INSTANCE_ROLE
from portrait_composer.ui.session import UISessionState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_collect_diagnostics_targets_import_warning(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, _sources, _warnings = identity_assembly(bundle)
    instance_id = "topwear__instance"
    with document.transaction():
        document.instances[instance_id].slot = "custom_slot"

    diagnostics = collect_diagnostics(document, ["semantic warning: topwear"])
    assert any(item.target_id == instance_id for item in diagnostics)
    assert any(item.message == "semantic warning: topwear" for item in diagnostics)


def test_diagnostics_badge_provenance_and_checklist(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    instance_id = "topwear__instance"
    window = MainWindow()
    window._display_document(
        document,
        image_sources,
        portrait_bundle,
        source_map=True,
        import_warnings=["semantic warning: topwear"],
    )

    assert window.diagnostics
    assert window.diagnostics_dock.checklist.count() == 6
    assert window.diagnostics_dock.list.count() >= 1
    badge_item = next(
        window.tree_dock.model.item(row)
        for row in range(window.tree_dock.model.rowCount())
        if window.tree_dock.model.item(row).data(INSTANCE_ROLE) == instance_id
    )
    assert "[WARN:" in badge_item.text()

    window.selection_model.select(instance_id)
    provenance_views = window.inspector_dock.findChildren(QTextEdit)
    assert provenance_views
    assert all(view.isReadOnly() for view in provenance_views)
    assert "identity_import" in provenance_views[-1].toPlainText()

    target = next(item for item in window.diagnostics if item.target_id == instance_id)
    window.focus_diagnostic(target)
    assert window.selection_model.instance_ids == [instance_id]


def test_diagnostic_click_preserves_tree_filter(qapp, portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    window.tree_dock.search.setText("does-not-match")
    target = window.diagnostics[0] if window.diagnostics else None
    if target is None:
        with document.transaction():
            document.instances[next(iter(document.instances))].slot = "custom_slot"
        window._refresh_after_document_change()
        target = window.diagnostics[0]
    window.focus_diagnostic(target)
    assert window.tree_dock.search.text() == "does-not-match"
