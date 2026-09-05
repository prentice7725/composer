from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.rig_export_dialog import RigExportReviewDialog

from .conftest import make_portrait_bundle


def test_rig_export_review_reports_ready_contract(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document, image_sources, _ = identity_assembly(bundle)
    review = RigExportReviewDialog(document, image_sources)

    assert review.errors == []
    assert "Visible canonical layers: 3" in review.list.item(0).text()
    assert review.list.findItems("[INFO] Donor assets: 0", Qt.MatchFlag.MatchExactly)
    review.close()
