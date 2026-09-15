from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import BundleError, read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.derived import adopt_derived_split, revert_derived_split
from portrait_composer.profiles import PORTRAIT_RIG, analyze_profile

from .conftest import make_portrait_bundle


def _bundle_with_split(root: Path) -> Path:
    root = make_portrait_bundle(
        root,
        layers=[
            ("handwear", (20, 20, 20, 255)),
            ("topwear", (30, 30, 30, 255)),
        ],
        z_order_override=["handwear", "topwear"],
    )
    derived_dir = root / "derived" / "left_right"
    derived_dir.mkdir(parents=True)
    Image.new("RGBA", (40, 40), (200, 0, 0, 255)).save(derived_dir / "handwear_left.png")
    Image.new("RGBA", (40, 40), (0, 200, 0, 255)).save(derived_dir / "handwear_right.png")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["derived"] = {
        "source_stage": "production_repaired",
        "left_right": {
            "status": "computed",
            "paths": {
                "handwear": {
                    "left": "derived/left_right/handwear_left.png",
                    "right": "derived/left_right/handwear_right.png",
                }
            },
        },
        "depth": {"status": "not_computed", "paths": {}},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_derived_candidates_are_intake_only_until_explicit_adoption(tmp_path):
    bundle = read_portrait_bundle(_bundle_with_split(tmp_path / "split.portrait"))
    candidates = bundle.derived_candidates()
    assert {(candidate.source_semantic, candidate.member) for candidate in candidates} == {
        ("handwear", "left"), ("handwear", "right")
    }
    document, image_sources, _ = identity_assembly(bundle)
    assert "handwear__instance" in document.instances
    assert len(document.instances) == 2
    assert analyze_profile(document, PORTRAIT_RIG) == []

    adopted = adopt_derived_split(document, image_sources, candidates)
    assert adopted == ["handwear.left__instance", "handwear.right__instance"]
    assert document.instances["handwear__instance"].visible is False
    assert document.composition["draw_order"] == adopted + ["topwear__instance"]
    assert all("adopt_producer_derivative" == document.assets[document.instances[i].asset_ref].provenance["operation"] for i in adopted)

    document.undo()
    assert document.composition["draw_order"] == ["handwear__instance", "topwear__instance"]
    document.redo()
    assert document.composition["draw_order"] == adopted + ["topwear__instance"]
    revert_derived_split(document, image_sources, "handwear")
    assert document.composition["draw_order"] == ["handwear__instance", "topwear__instance"]
    assert document.instances["handwear__instance"].visible is True


def test_derived_manifest_rejects_missing_or_aliased_artifacts(tmp_path):
    root = _bundle_with_split(tmp_path / "split.portrait")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["derived"]["left_right"]["paths"]["handwear"]["left"] = "derived/missing.png"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="artifact missing"):
        read_portrait_bundle(root)

    manifest["derived"]["left_right"]["paths"]["handwear"]["left"] = "layers/handwear.png"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="derived/|canonical layer"):
        read_portrait_bundle(root)


def test_adopt_save_reload_revert_preserves_provenance(tmp_path):
    bundle = read_portrait_bundle(_bundle_with_split(tmp_path / "split.portrait"))
    document, image_sources, _ = identity_assembly(bundle)
    adopt_derived_split(document, image_sources, bundle.derived_candidates())
    saved = write_assembly_bundle(document, image_sources, tmp_path / "saved.assembly")

    restored = read_assembly_bundle(saved)
    assert restored.instances["handwear__instance"].visible is False
    assert restored.assets["handwear.left"].provenance["operation"] == "adopt_producer_derivative"
    revert_derived_split(restored, {}, "handwear")
    assert restored.instances["handwear__instance"].visible is True
    assert restored.composition["draw_order"] == ["handwear__instance", "topwear__instance"]
