"""PySide6 application entry for the optional C5-A GUI."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run_gui(argv: list[str] | None = None) -> int:
    qt_argv = list(sys.argv if argv is None else [sys.argv[0], *argv])
    app = QApplication(qt_argv)
    app.setApplicationName("Portrait Composer")
    window = MainWindow()
    if argv:
        candidate = Path(argv[0])
        if candidate.exists() and candidate.is_dir():
            window.load_bundle(candidate)
    window.show()
    return app.exec()
