"""Qt-free tests for the C5-G Bake command layer (directive #34.2). No
PySide6 import anywhere in this module."""
from __future__ import annotations

from pathlib import Path

import pytest

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import BLOCK, CAN_BAKE, WARN, BakeBlockedError, analyze_bake
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.profiles import PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile
from portrait_composer.rig_intent import set_deformation_scope
from portrait_composer.ui.commands import bake_candidate


@pytest.fixture
def loaded(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)
    return document, image_sources


def test_analyze_profile_does_not_mutate(loaded):
    document, image_sources = loaded
    before = document.to_dict()
    revision_before = document.history.revision

    candidates = analyze_profile(document, PORTRAIT_STATIC)

    assert document.to_dict() == before
    assert document.history.revision == revision_before
    assert len(candidates) >= 1


def test_block_candidate_cannot_apply(loaded, tmp_path: Path):
    document, image_sources = loaded
    # a single-instance "candidate" is a hard BLOCK (bake needs >= 2 sources)
    analysis = analyze_bake(document, [next(iter(document.instances))])
    assert analysis.verdict == BLOCK

    from portrait_composer.profiles import BakeCandidate

    candidate = BakeCandidate(label="bad", instance_ids=analysis.instance_ids, analysis=analysis)
    revision_before = document.history.revision
    with pytest.raises(BakeBlockedError):
        bake_candidate(
            document, image_sources, candidate, derived_id="bad", semantic="bad", work_dir=tmp_path / "bake"
        )
    assert document.history.revision == revision_before


def test_warn_candidate_can_apply_explicitly_and_is_one_undo_step(loaded, tmp_path: Path):
    document, image_sources = loaded
    ids = list(document.instances)[:2]
    analysis = analyze_bake(document, ids)
    assert analysis.verdict == WARN  # no RigIntent authored -> WARN, not BLOCK

    from portrait_composer.profiles import BakeCandidate

    candidate = BakeCandidate(label="merged", instance_ids=ids, analysis=analysis)
    revision_before = document.history.revision

    derived_instance_id, warnings = bake_candidate(
        document, image_sources, candidate, derived_id="merged", semantic="merged", work_dir=tmp_path / "bake"
    )

    assert warnings  # WARN reasons are surfaced, not swallowed
    assert derived_instance_id in document.instances
    assert document.instances[ids[0]].visible is False
    assert document.instances[ids[1]].visible is False
    assert document.history.revision == revision_before + 1

    document.undo()
    assert derived_instance_id not in document.instances
    assert document.instances[ids[0]].visible is True
    assert document.instances[ids[1]].visible is True


def test_can_bake_candidate_when_rig_intent_is_authored(loaded, tmp_path: Path):
    document, image_sources = loaded
    ids = list(document.instances)[:2]
    for instance_id in ids:
        set_deformation_scope(document, instance_id, "rigid")
    analysis = analyze_bake(document, ids)
    assert analysis.verdict == CAN_BAKE

    from portrait_composer.profiles import BakeCandidate

    candidate = BakeCandidate(label="merged", instance_ids=ids, analysis=analysis)
    derived_instance_id, warnings = bake_candidate(
        document, image_sources, candidate, derived_id="merged", semantic="merged", work_dir=tmp_path / "bake"
    )
    assert warnings == []
    assert derived_instance_id in document.instances


def test_provenance_is_visible_after_bake(loaded, tmp_path: Path):
    document, image_sources = loaded
    ids = list(document.instances)[:2]
    for instance_id in ids:
        set_deformation_scope(document, instance_id, "rigid")
    analysis = analyze_bake(document, ids)

    from portrait_composer.profiles import BakeCandidate

    candidate = BakeCandidate(label="merged", instance_ids=ids, analysis=analysis)
    derived_instance_id, _warnings = bake_candidate(
        document, image_sources, candidate, derived_id="merged", semantic="merged", work_dir=tmp_path / "bake", profile=PORTRAIT_RIG
    )

    records = document.provenance.for_target(derived_instance_id)
    assert records and records[-1].operation == "bake"
    assert document.assets["merged"].provenance["operation"] == "alpha_composite"
    assert document.assets["merged"].provenance["profile"] == PORTRAIT_RIG
