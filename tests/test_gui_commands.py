"""Qt-free tests for the GUI command layer (directive #34.2).

These exercise ui/commands.py directly against a real AssemblyDocument --
no PySide6 import anywhere in this module -- verifying transaction count,
undo/redo, rollback and TransformLink propagation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.links import create_link
from portrait_composer.ui.commands import (
    nudge_draw_order,
    reorder_draw_order,
    set_instance_opacity,
    set_instance_transform,
    set_instance_visible,
)


@pytest.fixture
def loaded(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)
    return document, image_sources


def test_set_instance_transform_is_one_undo_step(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    revision_before = document.history.revision

    set_instance_transform(document, image_sources, instance_id, x=12.0, y=-4.0)

    assert document.instances[instance_id].transform.x == 12.0
    assert document.instances[instance_id].transform.y == -4.0
    assert document.history.revision == revision_before + 1
    assert document.history.can_undo()

    document.undo()
    assert document.instances[instance_id].transform.x == 0.0
    assert document.instances[instance_id].transform.y == 0.0

    document.redo()
    assert document.instances[instance_id].transform.x == 12.0


def test_set_instance_transform_partial_fields_only_touch_named_fields(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_instance_transform(document, image_sources, instance_id, scale_x=2.0)
    transform = document.instances[instance_id].transform
    assert transform.scale_x == 2.0
    assert transform.scale_y == 1.0
    assert transform.x == 0.0


def test_set_instance_transform_unknown_instance_rolls_back_and_raises(loaded):
    document, image_sources = loaded
    revision_before = document.history.revision
    undo_depth_before = len(document.history.undo_stack)
    with pytest.raises(KeyError):
        set_instance_transform(document, image_sources, "no_such_instance", x=1.0)
    assert document.history.revision == revision_before
    assert len(document.history.undo_stack) == undo_depth_before


def test_transform_link_moves_all_members_together(loaded):
    document, image_sources = loaded
    ids = list(document.instances)
    a, b = ids[0], ids[1]
    with document.transaction():
        create_link(document, "link_ab", [a, b])
    start_ax, start_ay = document.instances[a].transform.x, document.instances[a].transform.y
    start_bx, start_by = document.instances[b].transform.x, document.instances[b].transform.y

    set_instance_transform(document, image_sources, a, x=start_ax + 10.0, y=start_ay + 5.0)

    assert document.instances[a].transform.x == start_ax + 10.0
    assert document.instances[a].transform.y == start_ay + 5.0
    # linked member b moved by the same delta, not to a's absolute position
    assert document.instances[b].transform.x == start_bx + 10.0
    assert document.instances[b].transform.y == start_by + 5.0


def test_transform_link_does_not_apply_to_scale(loaded):
    document, image_sources = loaded
    ids = list(document.instances)
    a, b = ids[0], ids[1]
    with document.transaction():
        create_link(document, "link_ab", [a, b])

    set_instance_transform(document, image_sources, a, scale_x=2.0)

    assert document.instances[a].transform.scale_x == 2.0
    assert document.instances[b].transform.scale_x == 1.0


def test_set_instance_visible_and_opacity(loaded):
    document, image_sources = loaded
    instance_id = next(iter(document.instances))
    set_instance_visible(document, image_sources, instance_id, False)
    assert document.instances[instance_id].visible is False
    set_instance_opacity(document, image_sources, instance_id, 0.5)
    assert document.instances[instance_id].opacity == 0.5
    document.undo()
    assert document.instances[instance_id].opacity == 1.0
    document.undo()
    assert document.instances[instance_id].visible is True


def test_nudge_draw_order_forward_and_extremes(loaded):
    document, _image_sources = loaded
    order = list(document.composition["draw_order"])
    assert len(order) >= 3
    first = order[0]

    moved = nudge_draw_order(document, first, direction=1)
    assert moved is True
    assert document.composition["draw_order"][1] == first

    moved = nudge_draw_order(document, first, to_extreme=1)
    assert moved is True
    assert document.composition["draw_order"][-1] == first

    # already at the front: no-op, no transaction recorded
    revision_before = document.history.revision
    moved = nudge_draw_order(document, first, to_extreme=1)
    assert moved is False
    assert document.history.revision == revision_before


def test_nudge_draw_order_unknown_instance_is_noop(loaded):
    document, _image_sources = loaded
    revision_before = document.history.revision
    assert nudge_draw_order(document, "missing", direction=1) is False
    assert document.history.revision == revision_before


def test_reorder_draw_order_matches_set_draw_order(loaded):
    document, _image_sources = loaded
    order = list(document.composition["draw_order"])
    reversed_order = list(reversed(order))
    reorder_draw_order(document, reversed_order)
    assert document.composition["draw_order"] == reversed_order
