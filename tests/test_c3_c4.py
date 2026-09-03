from __future__ import annotations

from pathlib import Path

import pytest
import json
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import CAN_BAKE, WARN, analyze_bake
from portrait_composer.bundle import BundleError, read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.donors import DonorDriftError, import_donor
from portrait_composer.expressions import apply_expression_preset, create_expression_preset
from portrait_composer.rig_intent import add_attachment, set_deformation_scope
from portrait_composer.secondary_regions import (
    PREFLIGHT_DISABLED,
    PREFLIGHT_READY,
    add_upper_torso_secondary,
    set_geometry,
    visual_preflight,
)
from portrait_composer.slots import set_slot

from .conftest import make_portrait_bundle


def _portrait_doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    return identity_assembly(bundle)


def test_c4_rig_intent_and_upper_torso_preflight_round_trip(tmp_path: Path):
    document, image_sources, _ = _portrait_doc(tmp_path)
    with document.transaction():
        document.assets["neck"].semantic = "body"
        set_slot(document, "neck__instance", "torso_back")
        set_slot(document, "topwear__instance", "torso")
        set_slot(document, "head__instance", "head")
        set_deformation_scope(document, "topwear_with_arms", "secondary")
        add_upper_torso_secondary(
            document,
            target="topwear_with_arms",
            response_profile="firm_bounce",
            author_strength=0.85,
        )
        add_attachment(document, "head_follow", child="head__instance", target="head", mode="follow")

    region = document.rig_intent["regions"]["upper_torso_secondary"]
    assert region["geometry"]["kind"] == "two_lobe"
    assert region["response_profile"] == "firm_bounce"
    assert "stiffness" not in region and "damping" not in region
    assert visual_preflight(document).status == PREFLIGHT_READY

    # The logical PORTRAIT_RIG surface scope closes C2's previous WARN.
    assert analyze_bake(document, ["neck__instance", "topwear__instance"]).verdict == CAN_BAKE

    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)
    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.to_dict() == document.to_dict()
    assert reloaded.rig_intent["attachments"]["head_follow"]["mode"] == "follow"


def test_c4_preflight_disables_rigid_target_and_manual_geometry_edit(tmp_path: Path):
    document, _, _ = _portrait_doc(tmp_path)
    with document.transaction():
        set_slot(document, "topwear__instance", "torso")
        set_deformation_scope(document, "torso", "secondary")
        add_upper_torso_secondary(document, target="torso")
    assert visual_preflight(document).status == PREFLIGHT_READY

    with document.transaction():
        set_geometry(
            document,
            "upper_torso_secondary",
            {
                "kind": "two_lobe",
                "left": {"center": [-0.2, 0.4], "radius": [0.2, 0.2]},
                "right": {"center": [0.6, 0.4], "radius": [0.2, 0.2]},
            },
        )
    assert visual_preflight(document).status == PREFLIGHT_DISABLED

    with document.transaction():
        set_deformation_scope(document, "torso", "rigid")
    assert visual_preflight(document).status == PREFLIGHT_DISABLED


def test_c4_absent_rig_intent_keeps_c2_warn_before_scope_authoring(tmp_path: Path):
    document, _, _ = _portrait_doc(tmp_path)
    with document.transaction():
        document.assets["neck"].semantic = "body"
        set_slot(document, "neck__instance", "torso_back")
        set_slot(document, "topwear__instance", "torso")
    assert analyze_bake(document, ["neck__instance", "topwear__instance"]).verdict == WARN
    with document.transaction():
        set_deformation_scope(document, "topwear_with_arms", "secondary")
    assert analyze_bake(document, ["neck__instance", "topwear__instance"]).verdict == CAN_BAKE


def test_c3_c4_public_authoring_apis_create_undoable_transactions(tmp_path: Path):
    document, _, _ = _portrait_doc(tmp_path)
    before = document.to_dict()
    set_deformation_scope(document, "topwear_with_arms", "secondary")
    assert document.dirty
    document.undo()
    assert document.to_dict() == before
    document.redo()
    assert document.rig_intent["deformation_scopes"]["topwear_with_arms"] == "secondary"

    add_upper_torso_secondary(document, target="topwear_with_arms")
    document.undo()
    assert "upper_torso_secondary" not in document.rig_intent["regions"]
    document.redo()
    assert "upper_torso_secondary" in document.rig_intent["regions"]


def test_c3_donor_import_provenance_matte_roi_and_expression(tmp_path: Path):
    document, image_sources, _ = _portrait_doc(tmp_path)
    donor = tmp_path / "annoyed.png"
    Image.new("RGBA", (20, 20), (220, 40, 40, 255)).save(donor)
    matte = tmp_path / "matte.png"
    Image.new("L", (20, 20), 255).save(matte)

    result = import_donor(
        document,
        donor,
        semantic="eye_state",
        asset_id="eyes_annoyed",
        instance_id="eyes_annoyed__instance",
        matte=matte,
        roi={"x": 2, "y": 3, "width": 10, "height": 8},
        alignment={"x": 4, "y": 5, "scale_x": 1, "scale_y": 1, "rotation": 0},
        variant_set_id="eye_state",
        image_sources=image_sources,
        work_dir=tmp_path / "donors",
    )

    assert result.drift.ok
    assert Image.open(result.image_path).size == (10, 8)
    assert document.variant_sets["eye_state"]["members"] == [result.instance_id]
    detail = document.provenance.for_target(result.instance_id)[0].extra["detail"]
    for key in ("source_donor", "crop", "matte", "alignment_transform", "semantic_roi", "operations"):
        assert key in detail
    assert document.assets[result.asset_id].provenance["operation"] == "donor_import"
    assert document.validate().ok

    with document.transaction():
        create_expression_preset(document, "expression_annoyed", {"eye_state": result.instance_id})
    with document.transaction():
        apply_expression_preset(document, "expression_annoyed")
    assert document.variant_sets["eye_state"]["active"] == result.instance_id

    # The processed Assembly manifest is valid under the tightened C3/C4
    # contract, including the explicit expressions field.
    import jsonschema
    schema = json.loads(Path("schemas/portrait-assembly-v0.2.schema.json").read_text())
    manifest = {"format": "portrait-assembly", "version": "0.2", **document.to_dict()}
    jsonschema.validate(manifest, schema)


def test_assembly_reader_rejects_unknown_minor_version(tmp_path: Path):
    document, image_sources, _ = _portrait_doc(tmp_path)
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "0.3"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BundleError, match="unsupported assembly version"):
        read_assembly_bundle(out_dir)


def test_c3_donor_drift_is_hard_by_default(tmp_path: Path):
    donor = tmp_path / "donor.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 255)).save(donor)
    from portrait_composer.document import AssemblyDocument

    with pytest.raises(DonorDriftError):
        import_donor(
            AssemblyDocument(), donor, semantic="mouth", roi={"x": -1, "y": 0, "width": 5, "height": 5},
            work_dir=tmp_path / "donors",
        )


def test_c3_donor_target_alignment_drift_is_measured(tmp_path: Path):
    donor = tmp_path / "donor.png"
    Image.new("RGBA", (20, 20), (1, 2, 3, 255)).save(donor)
    from portrait_composer.document import AssemblyDocument

    with pytest.raises(DonorDriftError, match="target ROI center drift"):
        import_donor(
            AssemblyDocument(),
            donor,
            semantic="mouth",
            roi={"x": 0, "y": 0, "width": 10, "height": 10},
            alignment={"x": 15, "y": 15},
            target_roi={"x": 0, "y": 0, "width": 10, "height": 10},
            work_dir=tmp_path / "donors",
        )
