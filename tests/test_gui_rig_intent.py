"""Qt-free tests for the C5-F RigIntent/Secondary Region command layer
(directive #34.2). No PySide6 import anywhere in this module."""
from __future__ import annotations

from pathlib import Path

import pytest

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.rig_intent import ATTACHMENT_MODES, DEFORMATION_SCOPES, RigIntentError
from portrait_composer.secondary_regions import PREFLIGHT_READY, SecondaryRegionError, visual_preflight
from portrait_composer.ui.commands import (
    add_secondary_region,
    remove_rig_attachment,
    remove_secondary_region,
    set_deformation_scope,
    set_region_geometry,
    set_rig_attachment,
    update_secondary_region,
)


@pytest.fixture
def loaded(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)
    return document, image_sources


def test_all_five_deformation_scopes_are_authorable_and_undoable(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    for scope in DEFORMATION_SCOPES:
        revision_before = document.history.revision
        set_deformation_scope(document, image_sources, instance_id, scope)
        assert document.rig_intent["deformation_scopes"][instance_id] == scope
        assert document.history.revision == revision_before + 1
    document.undo()
    assert document.rig_intent["deformation_scopes"][instance_id] == DEFORMATION_SCOPES[-2]


def test_unknown_scope_rejected_without_partial_mutation(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    revision_before = document.history.revision
    with pytest.raises(RigIntentError):
        set_deformation_scope(document, image_sources, instance_id, "bogus")
    assert document.history.revision == revision_before
    assert instance_id not in document.rig_intent["deformation_scopes"]


def test_all_four_attachment_modes_are_authorable(loaded):
    document, image_sources = loaded
    ids = list(document.instances)
    child, target = ids[0], ids[1]
    for mode in ATTACHMENT_MODES:
        set_rig_attachment(document, image_sources, "att", child=child, target=target, mode=mode)
        assert document.rig_intent["attachments"]["att"]["mode"] == mode


def test_attachment_remove_is_undoable(loaded):
    document, image_sources = loaded
    ids = list(document.instances)
    child, target = ids[0], ids[1]
    set_rig_attachment(document, image_sources, "att", child=child, target=target, mode="weld")
    revision_before = document.history.revision

    remove_rig_attachment(document, image_sources, "att")
    assert "att" not in document.rig_intent["attachments"]
    assert document.history.revision == revision_before + 1

    document.undo()
    assert document.rig_intent["attachments"]["att"]["mode"] == "weld"


def test_add_and_remove_secondary_region_round_trip(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_deformation_scope(document, image_sources, instance_id, "secondary")

    region = add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)
    assert region["geometry"]["kind"] == "two_lobe"
    assert document.rig_intent["regions"]["upper_torso_secondary"]["target"] == instance_id

    report = visual_preflight(document)
    assert report.status == PREFLIGHT_READY

    revision_before = document.history.revision
    remove_secondary_region(document, image_sources, "upper_torso_secondary")
    assert "upper_torso_secondary" not in document.rig_intent["regions"]
    assert document.history.revision == revision_before + 1

    document.undo()
    assert "upper_torso_secondary" in document.rig_intent["regions"]


def test_update_secondary_region_response_profile_and_strength(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_deformation_scope(document, image_sources, instance_id, "secondary")
    add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)

    updated = update_secondary_region(
        document, image_sources, "upper_torso_secondary", response_profile="springy", author_strength=0.4
    )
    assert updated["response_profile"] == "springy"
    assert updated["author_strength"] == 0.4
    assert document.rig_intent["regions"]["upper_torso_secondary"]["response_profile"] == "springy"


def test_no_physics_constants_are_settable_through_the_command_layer(loaded):
    """Directive #12.2: stiffness/damping/spring_mass/solver_iterations must
    never appear as authorable fields anywhere in this GUI surface."""
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_deformation_scope(document, image_sources, instance_id, "secondary")
    region = add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)
    for forbidden in ("stiffness", "damping", "spring_mass", "solver_iterations", "physics_tick"):
        assert forbidden not in region


def test_region_geometry_edit_is_one_undo_step(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_deformation_scope(document, image_sources, instance_id, "secondary")
    add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)
    revision_before = document.history.revision

    new_geometry = {
        "kind": "two_lobe",
        "left": {"center": [0.30, 0.40], "radius": [0.20, 0.18]},
        "right": {"center": [0.70, 0.40], "radius": [0.20, 0.18]},
    }
    set_region_geometry(document, image_sources, "upper_torso_secondary", new_geometry)

    assert document.rig_intent["regions"]["upper_torso_secondary"]["geometry"]["left"]["center"] == [0.30, 0.40]
    assert document.history.revision == revision_before + 1

    document.undo()
    assert document.rig_intent["regions"]["upper_torso_secondary"]["geometry"]["left"]["center"] == [0.39, 0.36]


def test_invalid_geometry_rolls_back_without_partial_mutation(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_deformation_scope(document, image_sources, instance_id, "secondary")
    add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)
    revision_before = document.history.revision

    bad_geometry = {
        "kind": "two_lobe",
        "left": {"center": [0.3, 0.4], "radius": [-1.0, 0.2]},
        "right": {"center": [0.7, 0.4], "radius": [0.2, 0.2]},
    }
    with pytest.raises(SecondaryRegionError):
        set_region_geometry(document, image_sources, "upper_torso_secondary", bad_geometry)
    assert document.history.revision == revision_before
    assert document.rig_intent["regions"]["upper_torso_secondary"]["geometry"]["left"]["radius"] == [0.24, 0.20]


def test_preflight_degrades_when_deformation_scope_missing(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    # no set_deformation_scope call this time
    add_secondary_region(document, image_sources, "upper_torso_secondary", target=instance_id)
    report = visual_preflight(document)
    assert report.status != PREFLIGHT_READY
    assert any("deformation_scope" in reason for reason in report.reasons)
