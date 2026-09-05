from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import apply_bake_plan
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.seam_repair import normalize_seam_policy

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait", size=(24, 20)))
    document, image_sources, _ = identity_assembly(bundle)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"

    left = Image.new("RGBA", (24, 20), (0, 0, 0, 0))
    ImageDraw.Draw(left).rectangle((2, 4, 10, 16), fill=(240, 240, 240, 255))
    right = Image.new("RGBA", (24, 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(right)
    draw.rectangle((11, 4, 20, 16), fill=(240, 240, 240, 255))
    draw.line((11, 4, 11, 16), fill=(10, 10, 10, 255), width=1)
    left_path = tmp_path / "left.png"
    right_path = tmp_path / "right.png"
    left.save(left_path)
    right.save(right_path)
    image_sources["neck__instance"] = left_path
    image_sources["topwear__instance"] = right_path
    return document, image_sources, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (left_path, right_path)}


def _policy(**changes):
    return normalize_seam_policy(
        {"cleanup": "auto", "expand_under": 1, "remove_internal_lines": True, "contact_band_px": 1, **changes},
        result_semantic="topwear_with_arms",
        mode="semantic_merge",
    )


def test_semantic_merge_repairs_contact_and_preserves_sources(tmp_path: Path):
    document, image_sources, hashes = _doc(tmp_path)
    derived_id, _ = apply_bake_plan(
        document,
        image_sources,
        ["neck__instance", "topwear__instance"],
        derived_id="merged",
        semantic="topwear_with_arms",
        work_dir=tmp_path / "work",
        mode="semantic_merge",
        seam_policy=_policy(),
    )

    provenance = document.assets["merged"].provenance
    assert provenance["operation"] == "semantic_merge"
    assert provenance["bake_mode"] == "semantic_merge"
    assert provenance["seam_policy"]["expand_under"] == 1
    assert provenance["seam_report"]["contact_pixels"] > 0
    assert provenance["seam_report"]["expanded_pixels"] > 0
    assert provenance["seam_report"]["internal_lines_removed"] is True
    assert derived_id in image_sources
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in hashes.items())


def test_semantic_merge_policy_changes_output_and_round_trips(tmp_path: Path):
    document_a, sources_a, _ = _doc(tmp_path / "a")
    document_b, sources_b, _ = _doc(tmp_path / "b")
    apply_bake_plan(
        document_a, sources_a, ["neck__instance", "topwear__instance"],
        derived_id="merged", semantic="topwear_with_arms", work_dir=tmp_path / "work-a",
        mode="semantic_merge", seam_policy=_policy(expand_under=0, remove_internal_lines=False),
    )
    apply_bake_plan(
        document_b, sources_b, ["neck__instance", "topwear__instance"],
        derived_id="merged", semantic="topwear_with_arms", work_dir=tmp_path / "work-b",
        mode="semantic_merge", seam_policy=_policy(expand_under=2, remove_internal_lines=True),
    )
    assert sources_a["merged__instance"].read_bytes() != sources_b["merged__instance"].read_bytes()
    restored = type(document_b).from_dict(document_b.to_dict())
    assert restored.assets["merged"].provenance["seam_policy"]["expand_under"] == 2
