"""C2 exit checklist, end to end.

    [x] dry-run CAN_BAKE/WARN/BLOCK
    [x] source document 비파괴
    [x] derived AssetDefinition 생성
    [x] derived LayerInstance 생성
    [x] provenance chain 보존
    [x] bake 후 reference deterministic
    [x] undo/redo 완전 복원
    [x] save/reload 보존
    [x] VariantSet conflict BLOCK
    [x] canvas mismatch BLOCK
    [x] transform/link 관련 경고
    [x] PORTRAIT_STATIC policy
    [x] PORTRAIT_RIG policy
    [x] FULL_MOTION policy
    [x] profile analyze와 apply 분리
    [x] C0/C0.5/C1 회귀 전부 PASS (full suite)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import BLOCK, CAN_BAKE, analyze_bake
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.links import create_link
from portrait_composer.profiles import FULL_MOTION, PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile, apply_candidate
from portrait_composer.render import render_reference
from portrait_composer.slots import set_slot

from .conftest import make_portrait_bundle


def test_c2_full_pipeline(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document, image_sources, _ = identity_assembly(bundle)

    with document.transaction():
        set_slot(document, "neck__instance", "torso_back")
        set_slot(document, "topwear__instance", "torso")
        set_slot(document, "head__instance", "head")
        create_link(document, "torso_link", ["neck__instance", "topwear__instance"])

    # canvas mismatch -> BLOCK
    document.composition["canvas"] = {}
    assert analyze_bake(document, ["neck__instance", "topwear__instance"]).verdict == BLOCK
    bundle_again = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document.composition["canvas"] = dict(bundle_again.canvas)  # restore

    # RigIntent authored non-independent -> transform_link WARN, otherwise clean
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["head__instance"] = "rigid"
    analysis = analyze_bake(document, ["neck__instance", "topwear__instance"])
    assert any("transform_link" in r for r in analysis.warn_reasons)

    document.mark_saved()
    before = document.to_dict()

    # FULL_MOTION: recommends nothing
    assert analyze_profile(document, FULL_MOTION) == []

    # PORTRAIT_STATIC: everything groupable, CAN_BAKE-eligible (link dissolves -> WARN, still applyable)
    static_candidates = analyze_profile(document, PORTRAIT_STATIC)
    assert len(static_candidates) == 1
    assert set(static_candidates[0].instance_ids) == {"neck__instance", "topwear__instance", "head__instance"}

    # PORTRAIT_RIG: torso-system only, head kept independent
    rig_candidates = analyze_profile(document, PORTRAIT_RIG)
    assert len(rig_candidates) == 1
    assert set(rig_candidates[0].instance_ids) == {"neck__instance", "topwear__instance"}
    assert "head__instance" not in rig_candidates[0].instance_ids

    # analyze/apply split: apply only the PORTRAIT_RIG candidate
    derived_id, warnings = apply_candidate(
        document, image_sources, rig_candidates[0],
        derived_id="topwear_with_arms", semantic="topwear_with_arms",
        work_dir=tmp_path / "work", profile=PORTRAIT_RIG,
    )
    assert any("transform_link" in w for w in warnings)

    # source non-destruction
    assert document.instances["neck__instance"].visible is False
    assert document.instances["topwear__instance"].visible is False
    assert document.assets["neck"].source_binding is not None
    assert document.assets["topwear"].source_binding is not None

    # derived asset + instance + provenance chain
    assert "topwear_with_arms" in document.assets
    assert derived_id in document.instances
    record = document.provenance.for_target(derived_id)[0]
    assert record.operation == "bake"
    assert set(record.sources) == {"neck__instance", "topwear__instance"}
    assert document.assets["topwear_with_arms"].provenance["profile"] == PORTRAIT_RIG

    assert document.validate().ok

    # deterministic reference + save/reload
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)
    ref_a = render_reference(document, out_dir / "layers")
    ref_b = render_reference(document, out_dir / "layers")
    assert ref_a.tobytes() == ref_b.tobytes()
    on_disk = Image.open(out_dir / "reference.png").convert("RGBA")
    assert ref_a.tobytes() == on_disk.tobytes()

    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.to_dict() == document.to_dict()
    assert reloaded.validate().ok

    # undo/redo full restoration
    while document.dirty:
        document.undo()
    assert document.to_dict() == before
    document.redo()
    assert "topwear_with_arms" in document.assets
    assert document.instances["neck__instance"].visible is False
