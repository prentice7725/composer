from __future__ import annotations

from pathlib import Path

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import BLOCK, CAN_BAKE, WARN
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.profiles import (
    FULL_MOTION,
    PORTRAIT_RIG,
    PORTRAIT_STATIC,
    ProfileError,
    analyze_profile,
    apply_candidate,
    apply_non_blocking_candidates,
)
from portrait_composer.slots import set_slot
from portrait_composer.variants import add_variant_set

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document, image_sources, _ = identity_assembly(bundle)
    # remap the placeholder tag-as-slot identity import onto real slot
    # vocabulary, matching how a C1 authoring step would place these --
    # profiles.py's grouping is slot-driven, not tag-driven.
    with document.transaction():
        # Keep the fixture's back torso plane eligible; semantic neck is
        # intentionally protected even when manually placed in torso_back.
        document.assets["neck"].semantic = "body"
        set_slot(document, "neck__instance", "neck")
        set_slot(document, "topwear__instance", "torso")
        set_slot(document, "head__instance", "head")
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["head__instance"] = "rigid"
    return document, image_sources


def test_unknown_profile_raises():
    from portrait_composer.document import AssemblyDocument

    try:
        analyze_profile(AssemblyDocument(), "NOT_A_PROFILE")
        assert False, "expected ProfileError"
    except ProfileError:
        pass


def test_full_motion_recommends_nothing(tmp_path: Path):
    document, _ = _doc(tmp_path)
    assert analyze_profile(document, FULL_MOTION) == []


def test_portrait_static_groups_everything_not_variant_protected(tmp_path: Path):
    document, _ = _doc(tmp_path)
    candidates = analyze_profile(document, PORTRAIT_STATIC)
    assert len(candidates) == 1
    assert set(candidates[0].instance_ids) == {"neck__instance", "topwear__instance", "head__instance"}
    assert candidates[0].analysis.verdict == CAN_BAKE


def test_portrait_static_excludes_variant_set_members(tmp_path: Path):
    document, _ = _doc(tmp_path)
    with document.transaction():
        add_variant_set(document, "head_choice", members=["head__instance"], default="head__instance")

    candidates = analyze_profile(document, PORTRAIT_STATIC)
    assert len(candidates) == 1
    assert "head__instance" not in candidates[0].instance_ids
    assert set(candidates[0].instance_ids) == {"neck__instance", "topwear__instance"}


def test_portrait_rig_groups_torso_slots_keeps_head_independent(tmp_path: Path):
    document, _ = _doc(tmp_path)
    with document.transaction():
        set_slot(document, "neck__instance", "torso_back")  # both neck and topwear now torso-system

    candidates = analyze_profile(document, PORTRAIT_RIG)
    assert len(candidates) == 1
    assert candidates[0].label == "topwear_with_arms"
    assert set(candidates[0].instance_ids) == {"neck__instance", "topwear__instance"}
    assert "head__instance" not in candidates[0].instance_ids  # head slot kept independent


def test_portrait_rig_semantic_protection_cannot_be_bypassed_by_reslot(tmp_path: Path):
    document, _ = _doc(tmp_path)
    with document.transaction():
        document.assets["neck"].semantic = "neck"
        set_slot(document, "neck__instance", "torso_back")
    candidates = analyze_profile(document, PORTRAIT_RIG)
    assert candidates == []


def test_portrait_rig_recommends_nothing_when_only_one_torso_instance(tmp_path: Path):
    document, _ = _doc(tmp_path)
    # neck stays slot="neck" (not torso-system), only topwear is torso-system
    candidates = analyze_profile(document, PORTRAIT_RIG)
    assert candidates == []


def test_apply_candidate_applies_a_single_analyzed_candidate(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    candidates = analyze_profile(document, PORTRAIT_STATIC)

    derived_id, warnings = apply_candidate(
        document, image_sources, candidates[0],
        derived_id="static_composite", semantic="static_composite", work_dir=tmp_path / "work",
        profile=PORTRAIT_STATIC,
    )
    assert derived_id in document.instances
    assert document.assets["static_composite"].provenance["profile"] == PORTRAIT_STATIC


def test_apply_non_blocking_candidates_skips_blocked_ones(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    with document.transaction():
        add_variant_set(document, "head_choice", members=["head__instance"], default="head__instance")
        # force a second, deliberately blocked candidate by making an asset's
        # source binding unresolved
    document.assets["neck"].source_binding = None

    static_candidates = analyze_profile(document, PORTRAIT_STATIC)  # neck+topwear (head excluded by variant)
    assert static_candidates[0].analysis.verdict == BLOCK  # neck now has unresolved source binding

    results = apply_non_blocking_candidates(
        document, image_sources, static_candidates, work_dir=tmp_path / "work"
    )
    assert results == [{"label": "static_composite", "applied": False, "skipped": "BLOCK"}]
    assert "static_composite" not in document.assets  # never applied


def test_apply_non_blocking_candidates_applies_can_bake_and_warn(tmp_path: Path):
    document, image_sources = _doc(tmp_path)
    with document.transaction():
        set_slot(document, "neck__instance", "torso_back")

    candidates = analyze_profile(document, PORTRAIT_RIG)
    assert candidates[0].analysis.verdict == CAN_BAKE

    results = apply_non_blocking_candidates(
        document, image_sources, candidates, work_dir=tmp_path / "work", profile=PORTRAIT_RIG
    )
    assert results[0]["applied"] is True
    assert results[0]["label"] == "topwear_with_arms"
    assert document.assets["topwear_with_arms"].provenance["profile"] == PORTRAIT_RIG
