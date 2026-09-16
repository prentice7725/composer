"""Focused Composer accessibility regressions for the production workflow."""
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


@pytest.fixture
def window(qapp, portrait_bundle: Path) -> MainWindow:
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window = MainWindow()
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)
    return window


def test_bake_default_preview_is_static_and_keyboard_inspectable(window):
    window.set_context("BAKE")
    card = window.bake_workbench._cards[0]
    assert [button.property("mode") for button in card.mode_group.buttons()] == [
        "before",
        "after",
        "wipe",
        "difference",
    ]
    assert all(button.accessibleName() for button in card.mode_group.buttons())


def test_ui_scale_is_persisted_through_view_menu(qapp, portrait_bundle: Path, tmp_path: Path):
    settings = QSettings(str(tmp_path / "composer.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)
    window._display_document(document, image_sources, portrait_bundle, source_map=True, import_warnings=warnings)

    view_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "View")
    scale_menu = next(action.menu() for action in view_menu.actions() if action.text() == "UI Scale")
    action_150 = next(action for action in scale_menu.actions() if action.text() == "150%")
    action_150.trigger()
    settings.sync()

    assert settings.value("ui_scale") == 150
    assert action_150.isChecked()
    assert window._read_ui_scale() == 150

    window._set_ui_scale(100)


def test_persistent_alert_survives_diagnostics_refresh(window):
    window.remember_diagnostic("BLOCK", "Rig preflight BLOCK: missing head", context="BAKE")
    assert window.diagnostics_dock.persistent_list.count() == 1
    assert "missing head" in window.diagnostics_dock.persistent_list.item(0).text()

    window._refresh_after_document_change()
    assert window.diagnostics_dock.persistent_list.count() == 1
    assert "missing head" in window.diagnostics_dock.persistent_list.item(0).text()


def test_production_surface_exposes_keyboard_targets(window):
    assert window.canvas.accessibleName() == "Portrait composition canvas"
    assert {button.accessibleName() for button in window.production_buttons.values()} == {
        "COMPOSE production workflow",
        "EXPRESSIONS production workflow",
        "PREPARE RIG production workflow",
    }
    assert window.diagnostics_dock.list.accessibleName() == "Assembly diagnostics"
    assert window.diagnostics_dock.persistent_list.accessibleName() == "Persistent production alerts"
