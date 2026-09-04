"""Qt-backed tests for the C5-C Harvest Workbench (directive #27 exit gate).

Skipped entirely when PySide6 isn't installed.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.main_window import MainWindow
from tests.conftest import make_portrait_bundle


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pool(tmp_path: Path) -> dict:
    runs = {}
    for label, seed, color in (("seed_42", 42, (255, 0, 0, 255)), ("seed_1843", 1843, (0, 255, 0, 255)), ("seed_5902", 5902, (0, 0, 255, 255))):
        root = make_portrait_bundle(
            tmp_path / f"{label}.portrait",
            layers=(("head", color),),
            generation_overrides={"seed": seed},
        )
        runs[label] = read_portrait_bundle(root)
    return runs


def test_three_plus_runs_loaded_and_candidates_populated(qapp, pool):
    window = MainWindow()
    window.harvest_source_pool = pool
    window.set_context("HARVEST")

    assert window.workbench.currentWidget() is window.harvest_workbench
    assert window.harvest_workbench.tag_selector.count() == 1
    assert window.harvest_workbench.tag_selector.itemText(0) == "head"
    assert len(window.harvest_workbench._cards) == 3


def test_hover_never_mutates_the_document_and_apply_commits_with_provenance(qapp, pool):
    window = MainWindow()
    window.harvest_source_pool = pool
    window.set_context("HARVEST")
    workbench = window.harvest_workbench
    card = workbench._cards[0]

    assert window.document is None
    card.hovered.emit(card.run_label, card.image_path, "overlay")
    assert window.document is None  # hover alone never creates/mutates anything
    card.unhovered.emit()

    card.picked.emit(card.run_label)
    assert workbench.apply_button.isEnabled()
    workbench._apply()

    assert window.document is not None
    inst_id = "head__instance"
    assert window.document.assets["head"].source_binding.source_id == card.run_label
    records = window.document.provenance.for_target(inst_id)
    assert records and records[-1].operation == "multi_source_harvest"


def test_undo_restores_the_previous_source_choice(qapp, pool):
    window = MainWindow()
    window.harvest_source_pool = pool
    window.set_context("HARVEST")

    window.apply_harvest_pick("head", "seed_42")
    assert window.document.assets["head"].source_binding.source_id == "seed_42"

    window.apply_harvest_pick("head", "seed_1843")
    assert window.document.assets["head"].source_binding.source_id == "seed_1843"

    window.undo()
    assert window.document.assets["head"].source_binding.source_id == "seed_42"


def test_raw_layers_are_never_offered_as_candidates(qapp, tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "with_raw.portrait",
        layers=(("head", (0, 0, 255, 255)),),
        raw_layers={"eyewhite_candidate": (255, 255, 255, 255)},
    )
    bundle = read_portrait_bundle(root)
    window = MainWindow()
    window.harvest_source_pool = {"only": bundle}
    window.set_context("HARVEST")

    tags = {window.harvest_workbench.tag_selector.itemText(i) for i in range(window.harvest_workbench.tag_selector.count())}
    assert tags == {"head"}
    assert "eyewhite_candidate" not in tags


def test_apply_harvest_pick_after_document_exists_is_one_undo_step(qapp, pool):
    window = MainWindow()
    window.harvest_source_pool = pool
    window.set_context("HARVEST")
    window.apply_harvest_pick("head", "seed_42")
    revision_before = window.document.history.revision

    window.apply_harvest_pick("head", "seed_5902")

    assert window.document.history.revision == revision_before + 1
    assert window.document.instances["head__instance"] in window.document.instances.values()


def test_composite_preview_replaces_current_candidate_while_overlay_keeps_it(qapp, tmp_path: Path):
    first_root = make_portrait_bundle(
        tmp_path / "first.portrait", layers=(("head", (255, 0, 0, 255)),)
    )
    second_root = make_portrait_bundle(
        tmp_path / "second.portrait", layers=(("head", (0, 255, 0, 128)),)
    )
    pool = {
        "first": read_portrait_bundle(first_root),
        "second": read_portrait_bundle(second_root),
    }
    window = MainWindow()
    window.harvest_source_pool = pool
    window.apply_harvest_pick("head", "first")
    window.set_context("HARVEST")
    workbench = window.harvest_workbench
    candidate = next(card for card in workbench._cards if card.run_label == "second")

    candidate.hovered.emit("second", candidate.image_path, "composite")
    composite_color = window.canvas.scene_model._reference_item.pixmap().toImage().pixelColor(10, 10)
    candidate.hovered.emit("second", candidate.image_path, "overlay")
    overlay_color = window.canvas.scene_model._reference_item.pixmap().toImage().pixelColor(10, 10)

    assert composite_color.green() > composite_color.red()
    assert overlay_color.red() > composite_color.red()
    assert composite_color.alpha() < overlay_color.alpha()
