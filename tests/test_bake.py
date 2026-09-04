from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import (
    BLOCK,
    CAN_BAKE,
    WARN,
    BakeBlockedError,
    analyze_bake,
    apply_bake_plan,
)
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.instances import Transform
from portrait_composer.links import create_link
from portrait_composer.variants import add_variant_set

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document, image_sources, _ = identity_assembly(bundle)
    return document, image_sources


def test_analyze_bake_warns_when_rig_intent_absent_never_treats_absence_as_safe(tmp_path: Path):
    document, _ = _doc(tmp_path)
    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == WARN
    assert any("RigIntent" in r for r in analysis.warn_reasons)


def test_analyze_bake_reaches_can_bake_once_rig_intent_is_authored_and_non_independent(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == CAN_BAKE
    assert analysis.reasons == []


def test_analyze_bake_blocks_on_independent_rig_intent(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "independent"

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == BLOCK
    assert any("independent RigIntent" in r for r in analysis.block_reasons)


def test_analyze_bake_blocks_on_broken_attachment(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.rig_intent["attachments"]["hair_attach"] = {"child": "topwear__instance", "target": "head__instance", "mode": "follow"}

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == BLOCK
    assert any("attachment" in r for r in analysis.block_reasons)


def test_analyze_bake_blocks_on_variant_set_membership(tmp_path: Path):
    document, _ = _doc(tmp_path)
    with document.transaction():
        add_variant_set(document, "expr", members=["neck__instance", "topwear__instance"], default="neck__instance")

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == BLOCK
    assert any("variant_set" in r for r in analysis.block_reasons)


def test_analyze_bake_blocks_on_unresolved_source_binding(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.assets["neck"].source_binding = None

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == BLOCK
    assert any("unresolved source binding" in r for r in analysis.block_reasons)


def test_analyze_bake_blocks_on_single_instance(tmp_path: Path):
    document, _ = _doc(tmp_path)
    analysis = analyze_bake(document, ["neck__instance"])
    assert analysis.verdict == BLOCK


def test_analyze_bake_blocks_on_missing_canvas(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.composition["canvas"] = {}

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == BLOCK
    assert any("canvas" in r for r in analysis.block_reasons)


def test_analyze_bake_warns_on_transform_link_dissolution(tmp_path: Path):
    document, _ = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    with document.transaction():
        create_link(document, "grp", ["neck__instance", "topwear__instance"])

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert analysis.verdict == WARN
    assert any("transform_link" in r for r in analysis.warn_reasons)


def test_analyze_bake_warns_on_multi_source_span(tmp_path: Path):
    bundle_a = read_portrait_bundle(make_portrait_bundle(tmp_path / "a.portrait", source_identity="A001"))
    document, image_sources, _ = identity_assembly(bundle_a)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    # simulate the topwear asset having been remapped from a different source
    from portrait_composer.sources import SourceBinding

    document.sources["A002"] = document.sources["A001"].__class__(source_id="A002", path="somewhere")
    document.assets["topwear"].source_binding = SourceBinding(
        source_id="A002", revision="sha256:x", source_layer_id="topwear", fallback_semantic="topwear"
    )

    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert any("multiple bundles/seeds" in r for r in analysis.warn_reasons)


def test_apply_bake_plan_raises_on_block_and_never_mutates(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    with document.transaction():
        add_variant_set(document, "expr", members=["neck__instance", "topwear__instance"], default="neck__instance")
    before = document.to_dict()

    with pytest.raises(BakeBlockedError):
        apply_bake_plan(
            document, image_sources, ["neck__instance", "topwear__instance"],
            derived_id="merged", semantic="merged", work_dir=tmp_path / "work",
        )
    assert document.to_dict() == before


def test_apply_bake_plan_is_non_destructive_and_undo_restores_exactly(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    document.mark_saved()
    before = document.to_dict()

    derived_id, warnings = apply_bake_plan(
        document, image_sources, ["neck__instance", "topwear__instance"],
        derived_id="neck_topwear", semantic="neck_topwear", work_dir=tmp_path / "work", profile="TEST",
    )

    # sources are hidden, not deleted
    assert "neck__instance" in document.instances
    assert "topwear__instance" in document.instances
    assert document.instances["neck__instance"].visible is False
    assert document.instances["topwear__instance"].visible is False
    assert document.assets["neck"].source_binding is not None  # untouched

    assert derived_id == "neck_topwear__instance"
    assert derived_id in document.instances
    assert derived_id in image_sources
    assert document.validate().ok

    document.undo()
    assert document.to_dict() == before
    assert not document.dirty

    document.redo()
    assert document.instances["neck__instance"].visible is False
    assert derived_id in document.instances
    assert "neck_topwear" in document.assets  # derived asset back too


def test_apply_bake_plan_records_derived_provenance_and_asset_provenance(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"

    derived_id, _ = apply_bake_plan(
        document, image_sources, ["neck__instance", "topwear__instance"],
        derived_id="neck_topwear", semantic="neck_topwear", work_dir=tmp_path / "work", profile="TEST",
    )

    record = document.provenance.for_target(derived_id)[0]
    assert record.operation == "bake"
    assert set(record.sources) == {"neck__instance", "topwear__instance"}
    detail = record.extra["detail"]
    assert {d["instance"] for d in detail} == {"neck__instance", "topwear__instance"}
    assert all(d["source_bundle"] == "A001" for d in detail)

    asset_provenance = document.assets["neck_topwear"].provenance
    assert asset_provenance["operation"] == "alpha_composite"
    assert asset_provenance["profile"] == "TEST"
    assert {d["instance"] for d in asset_provenance["derived_from"]} == {"neck__instance", "topwear__instance"}


def test_apply_bake_plan_composite_pixels_match_manual_composite(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"

    expected = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for inst_id in ("neck__instance", "topwear__instance"):
        with Image.open(image_sources[inst_id]) as im:
            expected.alpha_composite(im.convert("RGBA"))

    derived_id, _ = apply_bake_plan(
        document, image_sources, ["neck__instance", "topwear__instance"],
        derived_id="neck_topwear", semantic="neck_topwear", work_dir=tmp_path / "work",
    )

    actual = Image.open(image_sources[derived_id]).convert("RGBA")
    assert actual.tobytes() == expected.tobytes()


def test_apply_bake_plan_draw_order_replaces_sources_in_place(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    assert document.composition["draw_order"] == ["neck__instance", "topwear__instance", "head__instance"]

    derived_id, _ = apply_bake_plan(
        document, image_sources, ["neck__instance", "topwear__instance"],
        derived_id="neck_topwear", semantic="neck_topwear", work_dir=tmp_path / "work",
    )

    assert document.composition["draw_order"] == [derived_id, "head__instance"]


def test_apply_bake_plan_uses_transient_staging_order_and_transforms(tmp_path: Path):
    from portrait_composer.render import render_subset

    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    ordered = ["topwear__instance", "neck__instance"]
    overrides = {
        "topwear__instance": Transform(x=3.0, y=4.0),
        "neck__instance": Transform(x=0.0, y=0.0),
    }
    expected = render_subset(document, image_sources, ordered, transform_overrides=overrides)

    derived_id, _ = apply_bake_plan(
        document,
        image_sources,
        ["neck__instance", "topwear__instance"],
        derived_id="staged_merge",
        semantic="staged_merge",
        work_dir=tmp_path / "work",
        ordered_instance_ids=ordered,
        transform_overrides=overrides,
    )

    actual = Image.open(image_sources[derived_id]).convert("RGBA")
    assert actual.tobytes() == expected.tobytes()
    assert document.instances["topwear__instance"].transform.to_dict() == Transform().to_dict()
    assert [item["instance"] for item in document.assets["staged_merge"].provenance["derived_from"]] == ordered


def test_apply_bake_plan_deterministic_reference_render(tmp_path: Path):
    from portrait_composer.bundle import write_assembly_bundle
    from portrait_composer.render import render_reference

    document, image_sources = _doc(tmp_path)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    apply_bake_plan(
        document, image_sources, ["neck__instance", "topwear__instance"],
        derived_id="neck_topwear", semantic="neck_topwear", work_dir=tmp_path / "work",
    )

    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)
    render_a = render_reference(document, out_dir / "layers")
    render_b = render_reference(document, out_dir / "layers")
    assert render_a.tobytes() == render_b.tobytes()

    reloaded = read_assembly_bundle_helper(out_dir)
    assert reloaded.to_dict() == document.to_dict()


def read_assembly_bundle_helper(out_dir):
    from portrait_composer.bundle import read_assembly_bundle

    return read_assembly_bundle(out_dir)
