from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QKeyEvent, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow
from portrait_composer.ui.models.assembly_tree import AssemblyTreeFilter, INSTANCE_ROLE, META_ROLE, WARNING_ROLE


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_workspace_settings_round_trip(qapp, portrait_bundle: Path, tmp_path: Path):
    settings_path = tmp_path / "portrait-composer.ini"
    settings = _settings(settings_path)
    first = MainWindow(settings=settings)
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    first._display_document(
        document,
        image_sources,
        portrait_bundle,
        source_map=True,
        import_warnings=warnings,
    )
    first.set_context("BAKE")
    first.tree_dock.search.setText("topwear")
    first.session.canvas_zoom = 1.75
    first.session.canvas_pan = (12.0, 20.0)
    recent = tmp_path / "sample.assembly"
    first._remember_recent(recent)
    first._save_workspace_settings()

    second = MainWindow(settings=_settings(settings_path))
    assert second.session.active_context == "BAKE"
    assert second.tree_dock.search.text() == "topwear"
    assert second.recent_files == [str(recent.resolve())]
    assert second._pending_view_state == (1.75, (12.0, 20.0))
    assert second.saveState()
    assert first.settings.value("recent_files")
    assert first.settings.value("last_context") == "BAKE"

    first.close()
    second.close()


def test_workspace_axis_navigates_and_persists(qapp, tmp_path: Path):
    settings_path = tmp_path / "axis.ini"
    first = MainWindow(settings=_settings(settings_path))

    first._set_workspace_axis("RIG PREP")
    assert first.session.workspace_axis == "RIG PREP"
    assert first.session.active_context == "DONOR"
    first._save_workspace_settings()
    first.close()

    second = MainWindow(settings=_settings(settings_path))
    assert second.session.workspace_axis == "RIG PREP"
    assert second.session.active_context == "DONOR"

    second._set_workspace_axis("COMPOSE")
    assert second.session.workspace_axis == "COMPOSE"
    assert second.session.active_context == "ASSEMBLE"
    second.close()


def test_context_workbench_is_normalized_to_compact_bottom_dock(qapp, tmp_path: Path):
    window = MainWindow(settings=_settings(tmp_path / "dock.ini"))
    window.show()
    qapp.processEvents()

    window.set_context("BAKE")
    qapp.processEvents()

    assert window.dockWidgetArea(window.workbench_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.workbench_dock.allowedAreas() == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.workbench_dock.height() <= 360
    window.close()


def test_recent_files_are_bounded_deduplicated_and_clearable(qapp, tmp_path: Path):
    window = MainWindow(settings=_settings(tmp_path / "recent.ini"))
    paths = [tmp_path / f"assembly-{index}" for index in range(window.MAX_RECENT_FILES + 2)]
    for path in paths:
        window._remember_recent(path)
    window._remember_recent(paths[-1])

    assert len(window.recent_files) == window.MAX_RECENT_FILES
    assert window.recent_files[0] == str(paths[-1].resolve())
    assert len(set(window.recent_files)) == window.MAX_RECENT_FILES

    window._clear_recent_files()
    assert window.recent_files == []
    assert window.settings.value("recent_files") is None
    window.close()


def test_render_time_is_exposed_as_ephemeral_status(qapp, portrait_bundle: Path, tmp_path: Path):
    window = MainWindow(settings=_settings(tmp_path / "render.ini"))
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window._display_document(
        document,
        image_sources,
        portrait_bundle,
        source_map=True,
        import_warnings=warnings,
    )

    assert window.session.last_render_ms >= 0.0
    assert "render:" in window.statusBar().currentMessage()
    window.close()


def test_save_is_blocked_before_writing_an_invalid_document(qapp, portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow(settings=_settings(tmp_path / "invalid.ini"))
    window._display_document(
        document,
        image_sources,
        portrait_bundle,
        source_map=True,
        import_warnings=warnings,
    )
    document.instances["head__instance"].asset_ref = "missing_asset"
    target = tmp_path / "should-not-be-written.assembly"

    assert window._write_bundle(target) is False
    assert not target.exists()
    assert "Save blocked" in window.statusBar().currentMessage()
    window.close()


def test_selected_source_filter_matches_only_the_selected_source(qapp):
    source_model = QStandardItemModel()
    for instance_id, source in (("head__instance", "seed-a"), ("mouth__instance", "seed-b")):
        item = QStandardItem(instance_id)
        item.setData({"source": source, "variant_sets": []}, META_ROLE)
        item.setData(0, WARNING_ROLE)
        source_model.appendRow(item)
    proxy = AssemblyTreeFilter()
    proxy.setSourceModel(source_model)
    proxy.set_filter_mode("Selected Source")
    proxy.set_selected_source("seed-b")

    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data() == "mouth__instance"


def test_canvas_tool_shortcuts_change_the_next_body_drag_operation(qapp, tmp_path: Path):
    window = MainWindow(settings=_settings(tmp_path / "tools.ini"))
    view = window.canvas
    for key, expected in (
        (Qt.Key.Key_V, None),
        (Qt.Key.Key_G, ("move", None)),
        (Qt.Key.Key_R, ("rotate", None)),
        (Qt.Key.Key_S, ("scale", None)),
    ):
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        assert view._body_drag_role() == expected
    window.close()


def test_escape_cancels_gizmo_before_generic_pending_cancel(qapp, portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow(settings=_settings(tmp_path / "escape.ini"))
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    instance_id = next(iter(document.instances))
    window.selection_model.select(instance_id)
    gizmo = window.canvas.scene_model.gizmo
    gizmo.begin_drag(("move", None), QPointF(0.0, 0.0))
    assert gizmo.drag is not None
    generic_called = []
    window.cancel_pending_operation = lambda: generic_called.append(True)

    window.canvas.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )

    assert gizmo.drag is None
    assert generic_called == []
    window.close()


def test_tree_selection_after_document_load_uses_a_fresh_proxy_model(
    qapp, portrait_bundle: Path, tmp_path: Path
):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow(settings=_settings(tmp_path / "selection.ini"))
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    window.show()
    qapp.processEvents()

    assert window.tree_dock.proxy.rowCount() == window.tree_dock.model.rowCount()
    index = window.tree_dock.proxy.index(0, 0)
    QTest.mouseClick(
        window.tree_dock.tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        window.tree_dock.tree.visualRect(index).center(),
    )
    qapp.processEvents()

    assert window.selection_model.instance_ids == [index.data(INSTANCE_ROLE)]

    second = window.tree_dock.proxy.index(1, 0)
    QTest.mouseClick(
        window.tree_dock.tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        window.tree_dock.tree.visualRect(second).center(),
    )
    qapp.processEvents()

    assert window.selection_model.instance_ids == [index.data(INSTANCE_ROLE), second.data(INSTANCE_ROLE)]
    window.close()
