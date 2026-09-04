"""Core tests for assembly.harvest_instance (C5-C's per-semantic re-pick,
directive #8.2/#10). Qt-free -- exercised directly against real Portrait
Bundle fixtures, mirroring how the GUI harvest workbench uses it."""
from __future__ import annotations

from pathlib import Path

import pytest

from portrait_composer.assembly import HarvestError, harvest_instance
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.document import AssemblyDocument
from tests.conftest import make_portrait_bundle


@pytest.fixture
def pool(tmp_path: Path) -> dict:
    run_a = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "a.portrait",
            layers=(("neck", (255, 0, 0, 255)), ("head", (0, 0, 255, 255))),
            generation_overrides={"seed": 42},
        )
    )
    run_b = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "b.portrait",
            layers=(("neck", (255, 10, 10, 255)), ("head", (10, 10, 255, 255))),
            generation_overrides={"seed": 1843},
        )
    )
    return {"seed_42": run_a, "seed_1843": run_b}


def test_first_pick_creates_the_document_and_sets_canvas(pool):
    document = AssemblyDocument()
    image_sources: dict = {}

    harvest_instance(document, image_sources, pool, "head", "seed_42")

    inst_id = "head__instance"
    assert inst_id in document.instances
    assert document.assets["head"].source_binding.source_id == "seed_42"
    assert document.composition["draw_order"] == [inst_id]
    assert document.composition["canvas"]["width"] == 40
    assert image_sources[inst_id] == pool["seed_42"].root / "layers" / "head.png"
    assert document.history.revision == 1


def test_repick_same_tag_preserves_position_and_transform(pool):
    document = AssemblyDocument()
    image_sources: dict = {}
    harvest_instance(document, image_sources, pool, "neck", "seed_42")
    harvest_instance(document, image_sources, pool, "head", "seed_42")

    inst_id = "head__instance"
    with document.transaction():
        document.instances[inst_id].transform.x = 7.0
        document.instances[inst_id].transform.rotation = 12.0
        document.instances[inst_id].visible = False
    index_before = document.composition["draw_order"].index(inst_id)

    harvest_instance(document, image_sources, pool, "head", "seed_1843")

    assert document.assets["head"].source_binding.source_id == "seed_1843"
    assert document.composition["draw_order"].index(inst_id) == index_before
    assert document.instances[inst_id].transform.x == 7.0
    assert document.instances[inst_id].transform.rotation == 12.0
    assert document.instances[inst_id].visible is False
    assert image_sources[inst_id] == pool["seed_1843"].root / "layers" / "head.png"


def test_repick_is_undoable_back_to_the_previous_source(pool):
    document = AssemblyDocument()
    image_sources: dict = {}
    harvest_instance(document, image_sources, pool, "head", "seed_42")
    revision_after_first_pick = document.history.revision

    harvest_instance(document, image_sources, pool, "head", "seed_1843")
    assert document.assets["head"].source_binding.source_id == "seed_1843"
    assert document.history.revision == revision_after_first_pick + 1

    document.undo()
    assert document.assets["head"].source_binding.source_id == "seed_42"


def test_harvest_instance_never_reads_raw_layers(tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "with_raw.portrait",
        layers=(("head", (0, 0, 255, 255)),),
        raw_layers={"eyewhite_candidate": (255, 255, 255, 255)},
    )
    bundle = read_portrait_bundle(root)
    document = AssemblyDocument()
    image_sources: dict = {}

    with pytest.raises(HarvestError, match="raw_layers/ is never a harvesting candidate"):
        harvest_instance(document, image_sources, {"only": bundle}, "eyewhite_candidate", "only")


def test_harvest_instance_unknown_run_raises(pool):
    document = AssemblyDocument()
    with pytest.raises(HarvestError, match="unknown run"):
        harvest_instance(document, {}, pool, "head", "no_such_run")


def test_harvest_instance_canvas_mismatch_rolls_back(pool, tmp_path: Path):
    document = AssemblyDocument()
    image_sources: dict = {}
    harvest_instance(document, image_sources, pool, "head", "seed_42")
    revision_before = document.history.revision

    mismatched_root = make_portrait_bundle(
        tmp_path / "different_canvas.portrait",
        size=(80, 80),
        layers=(("neck", (1, 2, 3, 255)),),
    )
    mismatched = read_portrait_bundle(mismatched_root)
    pool_with_mismatch = dict(pool, other=mismatched)

    with pytest.raises(HarvestError, match="canvas mismatch"):
        harvest_instance(document, image_sources, pool_with_mismatch, "neck", "other")
    assert document.history.revision == revision_before
    assert "neck" not in document.assets
