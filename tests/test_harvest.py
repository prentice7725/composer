"""C1 Multi-Source Harvesting.

Directive: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #10.

    A001 seed 1843 -- eyewhite good
    A001 seed 5902 -- arm good
    A001 seed 8177 -- hair_back good
              |
          Composer harvest (choose between runs' canonical layers/, never
          raw_layers/)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import HarvestError, harvest_assembly, instance_id_for
from portrait_composer.bundle import read_portrait_bundle

from .conftest import make_portrait_bundle

import pytest


def _three_runs(tmp_path: Path):
    run_a = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "seed_1843.portrait",
            source_identity="A001",
            layers=[
                ("neck", (10, 0, 0, 255)),
                ("topwear", (20, 0, 0, 255)),
                ("head", (30, 0, 0, 255)),
            ],
        )
    )
    run_b = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "seed_5902.portrait",
            source_identity="A001",
            layers=[
                ("neck", (0, 10, 0, 255)),
                ("topwear", (0, 20, 0, 255)),
                ("head", (0, 30, 0, 255)),
            ],
        )
    )
    run_c = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "seed_8177.portrait",
            source_identity="A001",
            layers=[
                ("neck", (0, 0, 10, 255)),
                ("topwear", (0, 0, 20, 255)),
                ("head", (0, 0, 30, 255)),
            ],
        )
    )
    return {"seed_1843": run_a, "seed_5902": run_b, "seed_8177": run_c}


def test_harvest_loads_three_bundles_and_picks_per_tag(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    selections = {"neck": "seed_1843", "topwear": "seed_5902", "head": "seed_8177"}

    document, image_sources, warnings = harvest_assembly(bundles, selections)

    assert set(document.assets) == {"neck", "topwear", "head"}
    assert document.validate().ok
    assert warnings == []

    # each instance's image actually came from the selected run
    neck_img = Image.open(image_sources[instance_id_for("neck")])
    assert neck_img.getpixel((0, 0))[:3] == (10, 0, 0)  # from seed_1843
    topwear_img = Image.open(image_sources[instance_id_for("topwear")])
    assert topwear_img.getpixel((0, 0))[:3] == (0, 20, 0)  # from seed_5902
    head_img = Image.open(image_sources[instance_id_for("head")])
    assert head_img.getpixel((0, 0))[:3] == (0, 0, 30)  # from seed_8177


def test_harvest_registers_one_source_per_run_label_not_per_tag(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    selections = {"neck": "seed_1843", "topwear": "seed_1843", "head": "seed_8177"}

    document, _, _ = harvest_assembly(bundles, selections)

    assert set(document.sources) == {"seed_1843", "seed_8177"}
    assert document.sources["seed_1843"].metadata["source_identity"] == "A001"


def test_harvest_provenance_preserves_run_label_and_seed(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    selections = {"neck": "seed_1843"}

    document, _, _ = harvest_assembly(bundles, selections)

    records = document.provenance.for_target(instance_id_for("neck"))
    assert records[0].operation == "multi_source_harvest"
    assert records[0].extra["run_label"] == "seed_1843"
    assert records[0].extra["source_layer_id"] == "neck"
    assert "generation" in records[0].extra


def test_harvest_never_reads_raw_layers(tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "seed_x.portrait",
        source_identity="A001",
        raw_layers={"eyewhite": (250, 250, 250, 255)},
    )
    bundles = {"seed_x": read_portrait_bundle(root)}

    with pytest.raises(HarvestError, match="raw_layers"):
        harvest_assembly(bundles, {"eyewhite": "seed_x"})


def test_harvest_rejects_unknown_run_label(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    with pytest.raises(HarvestError, match="unknown run"):
        harvest_assembly(bundles, {"neck": "seed_nonexistent"})


def test_harvest_rejects_canvas_mismatch(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    mismatched = read_portrait_bundle(
        make_portrait_bundle(
            tmp_path / "seed_bigger.portrait",
            source_identity="A001",
            size=(80, 80),
            layers=[("head", (0, 0, 0, 255))],
        )
    )
    bundles["seed_bigger"] = mismatched

    with pytest.raises(HarvestError, match="canvas mismatch"):
        harvest_assembly(bundles, {"neck": "seed_1843", "head": "seed_bigger"})


def test_harvest_draw_order_follows_originating_runs_z_order(tmp_path: Path):
    bundles = _three_runs(tmp_path)
    selections = {"head": "seed_1843", "neck": "seed_5902", "topwear": "seed_8177"}

    document, _, _ = harvest_assembly(bundles, selections)

    # neck < topwear < head in SEMANTIC_Z_ORDER regardless of which run each came from
    assert document.composition["draw_order"] == [
        instance_id_for("neck"),
        instance_id_for("topwear"),
        instance_id_for("head"),
    ]
