from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMenu

from portrait_composer.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_runtime_language_switch_uses_qtranslator_and_persists_setting(qapp, tmp_path: Path):
    settings = QSettings(str(tmp_path / "locale.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.set_locale("ko")

    top_menus = {menu.title() for menu in window.menuBar().findChildren(QMenu)}
    assert "파일" in top_menus
    assert window.context_buttons["ASSEMBLE"].text() == "조립"
    assert window.workbench_dock.windowTitle() == "컨텍스트 작업대"
    assert window.workbench_placeholder.text().startswith("ASSEMBLE 작업대")
    assert settings.value("locale") == "ko"

    window.set_locale("en")
    top_menus = {menu.title() for menu in window.menuBar().findChildren(QMenu)}
    assert "File" in top_menus
    assert window.context_buttons["ASSEMBLE"].text() == "ASSEMBLE"
    window.close()
