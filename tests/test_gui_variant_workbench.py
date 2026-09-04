"""Qt-backed tests for the C5-D VariantSet/Expression Workbench (directive
#28 exit gate). Skipped entirely when PySide6 isn't installed."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.ui.models.assembly_tree import INSTANCE_MIME_TYPE


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


def _instance_ids(window):
    return list(window.document.instances)


class _FakeDropEvent:
    def __init__(self, mime: QMimeData):
        self._mime = mime

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        pass


def test_new_variant_set_from_tree_selection_then_drag_adds_a_member(window, monkeypatch):
    a, b = _instance_ids(window)[:2]
    window.selection_model.select(a)

    workbench = window.variant_workbench
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("outfit", True)))
    workbench._new_variant_set()

    assert "outfit" in window.document.variant_sets
    assert window.document.variant_sets["outfit"]["members"] == [a]
    window.set_context("VARIANTS")
    row = workbench._rows["outfit"]

    mime = QMimeData()
    mime.setData(INSTANCE_MIME_TYPE, b.encode("utf-8"))
    row.dropEvent(_FakeDropEvent(mime))

    assert window.document.variant_sets["outfit"]["members"] == [a, b]
    assert window.document.instances[b].visible is False  # exclusive: non-active member stays hidden


def test_variant_member_click_commits_and_canvas_reflects_it(window):
    a, b = _instance_ids(window)[:2]
    from portrait_composer.ui.commands import add_variant_member

    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", a, default=True))
    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", b))
    window.set_context("VARIANTS")
    row = window.variant_workbench._rows["outfit"]

    row._pick(b)

    assert window.document.variant_sets["outfit"]["active"] == b
    assert window.document.instances[b].visible is True
    assert window.document.instances[a].visible is False
    # canvas rebuilt from the committed document: only the visible member
    # gets a hit item (scene.py skips invisible instances)
    assert b in window.canvas.scene_model._hit_items
    assert a not in window.canvas.scene_model._hit_items


def test_remove_member_via_row_and_last_member_guard(window):
    a, b = _instance_ids(window)[:2]
    from portrait_composer.ui.commands import add_variant_member

    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", a, default=True))
    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", b))
    window.set_context("VARIANTS")
    row = window.variant_workbench._rows["outfit"]

    row._remove(b)
    assert window.document.variant_sets["outfit"]["members"] == [a]

    revision_before = window.document.history.revision
    row._remove(a)  # would empty the set -- must be rejected, no partial mutation
    assert window.document.variant_sets["outfit"]["members"] == [a]
    assert window.document.history.revision == revision_before
    assert "Edit failed" in window.statusBar().currentMessage()


def test_expression_preview_is_transient_then_apply_commits(window, monkeypatch):
    a, b = _instance_ids(window)[:2]
    from portrait_composer.ui.commands import add_variant_member

    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", a, default=True))
    window.run_command(lambda doc, srcs: add_variant_member(doc, srcs, "outfit", b))
    window.set_context("VARIANTS")
    editor = window.variant_workbench.expression_editor

    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("casual", True)))
    editor._new_preset()
    assert "casual" in window.document.expressions

    combo = editor._dropdowns["outfit"]
    index_b = combo.findData(b)
    combo.setCurrentIndex(index_b)

    committed_active_before = window.document.variant_sets["outfit"]["active"]
    editor._preview()
    # preview never mutates the document
    assert window.document.variant_sets["outfit"]["active"] == committed_active_before
    assert window.document.instances[a].visible is True

    editor._apply()
    assert window.document.variant_sets["outfit"]["active"] == b
    assert window.document.expressions["casual"]["variants"] == {"outfit": b}

    window.undo()
    assert window.document.variant_sets["outfit"]["active"] == committed_active_before
