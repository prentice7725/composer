from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake_plan import create_bake_plan
from portrait_composer.bundle import BundleError, read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.render import render_reference
from portrait_composer.rig_bundle import export_rig_bundle, validate_exported_rig_bundle
from portrait_composer.visual_ops import add_visual_op, apply_visual_ops

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    return identity_assembly(bundle)


def test_assembly_save_persists_visual_op_mask_as_bundle_artifact(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    mask = tmp_path / "author-mask.png"
    Image.new("L", (40, 40), 255).save(mask)
    add_visual_op(
        document,
        "topwear__instance",
        {"id": "mask_1", "type": "mask", "params": {"path": str(mask)}},
    )

    out_dir = write_assembly_bundle(document, image_sources, tmp_path / "out.assembly")
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    sidecar = json.loads((out_dir / "composer-authoring-v03.json").read_text(encoding="utf-8"))
    op = sidecar["visual_ops"]["topwear__instance"][0]
    assert op["params"]["path"] == "masks/topwear__instance__mask_1.png"
    assert (out_dir / op["params"]["path"]).exists()

    reloaded = read_assembly_bundle(out_dir)
    rendered = render_reference(reloaded, out_dir / "layers")
    assert rendered.size == (40, 40)


def test_assembly_v02_manifest_keeps_composer_v03_state_in_sidecar(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    create_bake_plan(
        document,
        "torso_plan",
        sources=["topwear__instance"],
        result_semantic="torso_baked",
        result_slot="torso",
    )
    document.remap_review = {
        "status": "RESOLVED",
        "source_id": "source-a",
        "entries": [],
        "unresolved_assets": [],
    }

    out_dir = write_assembly_bundle(document, image_sources, tmp_path / "compat.assembly")
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "bake_plans" not in manifest
    assert "remap_review" not in manifest
    assert all("visual_ops" not in instance for instance in manifest["instances"].values())

    sidecar = json.loads((out_dir / "composer-authoring-v03.json").read_text(encoding="utf-8"))
    sidecar_schema = json.loads(
        Path("schemas/portrait-composer-authoring-v0.3.schema.json").read_text(encoding="utf-8")
    )
    import jsonschema

    jsonschema.validate(sidecar, sidecar_schema)
    assert sidecar["format"] == "portrait-composer-authoring"
    assert sidecar["version"] == "0.3"
    assert sidecar["bake_plans"] == document.bake_plans
    assert sidecar["remap_review"] == document.remap_review
    assert sidecar["visual_ops"]

    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.bake_plans == document.bake_plans
    assert reloaded.remap_review == document.remap_review
    assert reloaded.to_dict()["instances"] == document.to_dict()["instances"]


def test_assembly_v02_without_composer_sidecar_still_reads(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    out_dir = write_assembly_bundle(document, image_sources, tmp_path / "legacy.assembly")
    (out_dir / "composer-authoring-v03.json").unlink()

    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.bake_plans == {}
    assert reloaded.remap_review is None


def test_assembly_authoring_sidecar_rejects_unknown_minor_version(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    out_dir = write_assembly_bundle(document, image_sources, tmp_path / "bad-sidecar.assembly")
    sidecar_path = out_dir / "composer-authoring-v03.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["version"] = "0.4"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    with pytest.raises(BundleError, match="unsupported authoring state version"):
        read_assembly_bundle(out_dir)


def test_rig_bundle_export_is_separate_and_contains_visible_canonical_layers(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    out_dir = export_rig_bundle(document, image_sources, tmp_path / "out.rigbundle")

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "portrait-rig-bundle"
    assert manifest["version"] == "0.3"
    assert set(manifest["layers"]) == set(document.instances)
    assert (out_dir / "reference.png").exists()
    assert (out_dir / "rig_intent.json").exists()
    assert (out_dir / "provenance" / "assembly.json").exists()
    assert validate_exported_rig_bundle(out_dir) == []


def test_rig_bundle_export_from_reloaded_assembly_resolves_relative_visual_op_paths(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    mask = tmp_path / "mask.png"
    Image.new("L", (40, 40), 255).save(mask)
    add_visual_op(document, "topwear__instance", {"id": "m", "type": "mask", "params": {"path": str(mask)}})
    assembly_dir = write_assembly_bundle(document, image_sources, tmp_path / "saved.assembly")
    reloaded = read_assembly_bundle(assembly_dir)
    reloaded_sources = {
        instance_id: assembly_dir / "layers" / f"{instance_id}.png"
        for instance_id in reloaded.instances
    }
    rig_dir = export_rig_bundle(reloaded, reloaded_sources, tmp_path / "saved.rigbundle")
    assert (rig_dir / "reference.png").exists()
    rig_manifest = json.loads((rig_dir / "manifest.json").read_text(encoding="utf-8"))
    assert rig_manifest["instances"]["topwear__instance"]["visual_ops"][0]["params"]["path"].startswith("masks/")
    assert list((rig_dir / "masks").glob("topwear__instance__*.png"))


def test_rig_bundle_exports_visual_ops_and_autorig_layer_metadata(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    add_visual_op(
        document,
        "topwear__instance",
        {"id": "desaturate", "type": "color", "params": {"saturation": 0.0}},
    )

    out_dir = export_rig_bundle(document, image_sources, tmp_path / "metadata.rigbundle")
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    exported = Image.open(out_dir / "layers" / "topwear__instance.png").convert("RGBA")
    with Image.open(image_sources["topwear__instance"]) as raw:
        expected = apply_visual_ops(raw, document.instances["topwear__instance"].visual_ops)

    assert manifest["instances"]["topwear__instance"]["visual_ops"][0]["id"] == "desaturate"
    assert manifest["assets"]["topwear"]["semantic"] == "topwear"
    assert (out_dir / "donors.json").exists()
    assert exported.tobytes() == expected.tobytes()
