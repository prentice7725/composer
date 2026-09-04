from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow


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
