from __future__ import annotations

import importlib.util

import pytest

from portrait_composer.gui import GuiUnavailableError, main
from portrait_composer.ui.session import SelectionModel, UISessionState, sync_session_selection


def test_selection_model_is_document_free_and_preserves_selection_across_contexts():
    session = UISessionState()
    selection = SelectionModel()
    selection.set_instances(["hair__instance", "head__instance"], asset_id="hair")
    sync_session_selection(session, selection)
    session.active_context = "DONOR"
    session.tree_filter = "warnings"
    assert session.selected_instance_ids == ["hair__instance", "head__instance"]
    assert session.selected_asset_id == "hair"
    assert session.active_context == "DONOR"


def test_gui_facade_does_not_require_pyside6_for_import():
    if importlib.util.find_spec("PySide6") is not None:
        pytest.skip("PySide6 is installed; do not launch a GUI in the headless test suite")
    try:
        result = main([])
    except GuiUnavailableError:
        # The facade may be used directly by an embedding application.
        result = 2
    assert result == 2


def test_cli_gui_entry_reports_optional_dependency_without_importing_qt():
    if importlib.util.find_spec("PySide6") is not None:
        pytest.skip("PySide6 is installed; do not launch a GUI in the headless test suite")
    assert main([]) == 2
