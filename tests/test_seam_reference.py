from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import apply_bake_plan
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.render import render_subset, render_subset_layers
from portrait_composer.seam_reference import repair_bake_seams
from portrait_composer.seam_repair import normalize_seam_policy


FIXTURE = Path(__file__).parent / "fixtures/portrait_bundles/shoulder_seam.portrait"
IDS = ["handwear__instance", "topwear__instance"]


@pytest.fixture
def source(tmp_path):
    root = Path(shutil.copytree(FIXTURE, tmp_path / "source.portrait"))
    document, sources, _ = identity_assembly(read_portrait_bundle(root))
    return document, sources, root


def _repair(document, sources, ids=IDS, *, overrides=None, policy=None):
    composite = render_subset(document, sources, ids, transform_overrides=overrides)
    layers = [
        (iid, document.assets[document.instances[iid].asset_ref].semantic, image)
        for iid, image in render_subset_layers(document, sources, ids, transform_overrides=overrides)
    ]
    repaired, report = repair_bake_seams(
        document, sources, composite, layers,
        normalize_seam_policy(policy, result_semantic="topwear_with_arms"),
        transform_overrides=overrides,
    )
    return composite, repaired, report


@pytest.mark.parametrize("reverse", [False, True])
def test_real_shoulder_restores_seam_and_preserves_armpit(source, tmp_path, reverse):
    document, sources, root = source
    ids = IDS[::-1] if reverse else IDS
    original = Image.open(root / "original.png").convert("RGB")
    before_document = document.to_dict()
    source_bytes = {iid: sources[iid].read_bytes() for iid in ids}
    before, repaired, report = _repair(document, sources, ids)
    assert report["reference_restored_pixels"] > 1000
    assert report["reference_source"]["original_hash"].startswith("sha256:")
    assert document.to_dict() == before_document
    # Shoulder center and the dark armpit crease must match actual original
    # RGB, not an interpolated skin fill that erases the anatomical line.
    for point in [(60, 50), (368, 50), (54, 120), (365, 120)]:
        assert repaired.getpixel(point)[:3] == original.getpixel(point)
    assert repaired.getchannel("A").tobytes() == before.getchannel("A").tobytes()
    box = (360, 30, 380, 95)
    def error(image):
        delta = ImageChops.difference(image.convert("RGB").crop(box), original.crop(box))
        return sum(ImageStat.Stat(delta).mean) / 3
    assert error(repaired) < error(before) * (0.5 if reverse else 0.2)
    # Same entry point as preview must produce the exact committed PNG,
    # including an arbitrary user-authored output semantic/name.
    result, _ = apply_bake_plan(
        document, sources, ids, ordered_instance_ids=ids,
        derived_id="portrait_rig", semantic="portrait_rig", mode="semantic_merge",
        seam_policy=normalize_seam_policy(None, result_semantic="topwear_with_arms"),
        work_dir=tmp_path / "bake",
    )
    with Image.open(sources[result]) as baked:
        assert baked.tobytes() == repaired.tobytes()
    assert all(sources[iid].read_bytes() == data for iid, data in source_bytes.items())
    document.undo()
    assert document.to_dict() == before_document


def test_original_hair_is_not_burned_into_body_even_if_hidden(source):
    document, sources, root = source
    for iid in document.instances:
        if iid not in IDS:
            document.instances[iid].visible = False
    before, repaired, report = _repair(document, sources)
    assert report["reference_restored_pixels"] > 0
    hair = Image.open(root / "layers/front hair.png").getchannel("A")
    difference = ImageChops.difference(before.convert("RGB"), repaired.convert("RGB"))
    for channel in difference.split():
        assert ImageChops.multiply(channel, hair.point(lambda v: 255 if v else 0)).getbbox() is None


@pytest.mark.parametrize("change", [
    "transform", "override", "opacity", "visual_ops", "replacement", "mixed_source",
    "revision", "original_missing", "occluder_missing", "canvas",
])
def test_reference_is_not_used_for_incompatible_sources(source, tmp_path, change):
    document, sources, root = source
    iid = IDS[0]
    overrides = None
    if change == "transform":
        document.instances[iid].transform.x = 3
    elif change == "override":
        overrides = {iid: {"x": 3}}
    elif change == "opacity":
        document.instances[iid].opacity = 0.8
    elif change == "visual_ops":
        # A disabled op still makes original-reference fidelity uncertain.
        document.instances[iid].visual_ops = [{"id": "color1", "type": "color", "enabled": False}]
    elif change == "replacement":
        image = Image.open(sources[iid]).convert("RGBA")
        image.putpixel((50, 50), (10, 20, 30, 255))
        replacement = tmp_path / "edited.png"
        image.save(replacement)
        sources[iid] = replacement
    elif change == "mixed_source":
        document.assets[document.instances[iid].asset_ref].source_binding.source_id = "other"
    elif change == "revision":
        with (root / "manifest.json").open("a") as output:
            output.write("\n")
    elif change == "original_missing":
        (root / "original.png").unlink()
    elif change == "occluder_missing":
        (root / "layers/front hair.png").unlink()
    elif change == "canvas":
        document.composition["canvas"]["width"] += 1
    _, _, report = _repair(document, sources, overrides=overrides)
    assert report["reference_restored_pixels"] == 0
    assert "reference_source" not in report


@pytest.mark.parametrize("policy", [{"cleanup": "off"}, {"remove_internal_lines": False}])
def test_reference_respects_cleanup_switches(source, policy):
    document, sources, _ = source
    _, _, report = _repair(document, sources, policy=policy)
    assert report["reference_restored_pixels"] == 0
    assert "reference_source" not in report


def test_gui_reference_preview_matches_committed_canvas(source, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from portrait_composer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    document, sources, root = source
    window = MainWindow()
    try:
        window._display_document(document, sources, root, source_map=True)
        policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")
        preview = window.canvas.scene_model._bake_after_image(
            IDS, ordered_instance_ids=IDS, bake_mode="semantic_merge", seam_policy=policy,
        )
        assert preview is not None
        apply_bake_plan(
            document, sources, IDS, ordered_instance_ids=IDS,
            derived_id="portrait_rig", semantic="portrait_rig", mode="semantic_merge",
            seam_policy=policy, work_dir=tmp_path / "bake",
        )
        committed = render_subset(document, sources, document.composition["draw_order"])
        assert preview.tobytes() == committed.tobytes()
    finally:
        window.close()
