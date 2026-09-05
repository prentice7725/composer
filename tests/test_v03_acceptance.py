from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import CAN_BAKE
from portrait_composer.bake_plan import analyze_bake_plan, apply_bake_plan, create_bake_plan
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.donors import import_donor
from portrait_composer.render import render_reference
from portrait_composer.rig_bundle import export_rig_bundle
from portrait_composer.rig_intent import set_deformation_scope
from portrait_composer.secondary_regions import add_upper_torso_secondary, visual_preflight
from portrait_composer.slots import set_slot
from portrait_composer.visual_ops import add_visual_op

from .conftest import make_portrait_bundle


def test_v03_end_to_end_bake_rig_export_and_reload(tmp_path: Path):
    bundle_root = make_portrait_bundle(
        tmp_path / "source.portrait",
        layers=[
            ("body_remainder", (220, 100, 90, 255)),
            ("topwear", (40, 180, 90, 220)),
            ("head", (70, 90, 220, 255)),
        ],
        source_identity="A001",
    )
    bundle = read_portrait_bundle(bundle_root)
    document, image_sources, _ = identity_assembly(bundle)
    body = "body_remainder__instance"
    topwear = "topwear__instance"

    mask_path = tmp_path / "mask.png"
    Image.new("L", (40, 40), 255).save(mask_path)
    add_visual_op(document, topwear, {"id": "tone", "type": "color", "params": {"brightness": 0.9}})
    add_visual_op(document, topwear, {"id": "mask", "type": "mask", "params": {"path": str(mask_path)}})

    with document.transaction():
        set_slot(document, body, "torso_back")
        set_slot(document, topwear, "torso")
        set_deformation_scope(document, "topwear_with_arms", "secondary")
        add_upper_torso_secondary(document, target="topwear_with_arms", response_profile="firm_bounce")

    assert visual_preflight(document).status == "READY"
    create_bake_plan(
        document,
        "torso_plan",
        sources=[body, topwear],
        result_semantic="topwear_with_arms",
        result_slot="torso",
    )
    assert analyze_bake_plan(document, "torso_plan").verdict == CAN_BAKE
    derived_id, warnings = apply_bake_plan(
        document,
        image_sources,
        "torso_plan",
        work_dir=tmp_path / "bake",
        profile="PORTRAIT_RIG",
    )
    assert derived_id == "topwear_with_arms__instance"
    assert document.bake_plans["torso_plan"]["status"] == "BAKED"
    assert warnings == []

    donor_path = tmp_path / "blink.png"
    Image.new("RGBA", (40, 40), (255, 255, 255, 180)).save(donor_path)
    donor = import_donor(
        document,
        donor_path,
        semantic="eye_closed",
        roi={"x": 0, "y": 0, "width": 40, "height": 40},
        work_dir=tmp_path / "donor",
        image_sources=image_sources,
    )
    assert donor.variant_set_id == "eyes_state"

    rig_dir = export_rig_bundle(document, image_sources, tmp_path / "final.rigbundle")
    rig_manifest = json.loads((rig_dir / "manifest.json").read_text(encoding="utf-8"))
    assert rig_manifest["instances"][derived_id]["slot"] == "torso"
    assert rig_manifest["rig_intent"]["regions"]["upper_torso_secondary"]["response_profile"] == "firm_bounce"
    assert donor.asset_id in rig_manifest["donors"]
    assert (rig_dir / "donors.json").exists()

    assembly_dir = write_assembly_bundle(document, image_sources, tmp_path / "final.assembly")
    reloaded = read_assembly_bundle(assembly_dir)
    reloaded_reference = render_reference(reloaded, assembly_dir / "layers")
    assert reloaded_reference.tobytes() == Image.open(rig_dir / "reference.png").convert("RGBA").tobytes()
