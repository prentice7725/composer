"""Qt-free tests for the C5-D VariantSet/Expression command layer
(directive #34.2). No PySide6 import anywhere in this module."""
from __future__ import annotations

from pathlib import Path

import pytest

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.ui.commands import (
    add_variant_member,
    remove_variant_member,
    save_and_apply_expression,
    save_expression,
    set_variant_active,
)
from portrait_composer.variants import VariantSetError


@pytest.fixture
def loaded(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)
    return document, image_sources


def _ids(document):
    return list(document.instances)


def test_add_variant_member_creates_the_set_on_first_add(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    assert document.variant_sets["outfit"]["members"] == [a]
    assert document.variant_sets["outfit"]["active"] == a

    add_variant_member(document, image_sources, "outfit", b)
    assert document.variant_sets["outfit"]["members"] == [a, b]
    # exclusive mode: adding a non-active member keeps it hidden
    assert document.instances[b].visible is False


def test_set_variant_active_is_one_undo_step_and_drives_exclusive_visibility(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    add_variant_member(document, image_sources, "outfit", b)
    revision_before = document.history.revision

    set_variant_active(document, image_sources, "outfit", b)

    assert document.variant_sets["outfit"]["active"] == b
    assert document.instances[a].visible is False
    assert document.instances[b].visible is True
    assert document.history.revision == revision_before + 1

    document.undo()
    assert document.variant_sets["outfit"]["active"] == a
    assert document.instances[a].visible is True


def test_remove_variant_member_reassigns_active_and_rolls_back_on_last_member(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    add_variant_member(document, image_sources, "outfit", b)
    set_variant_active(document, image_sources, "outfit", b)

    remove_variant_member(document, image_sources, "outfit", b)
    assert document.variant_sets["outfit"]["members"] == [a]
    assert document.variant_sets["outfit"]["active"] == a
    assert document.instances[a].visible is True

    revision_before = document.history.revision
    with pytest.raises(VariantSetError, match="only member"):
        remove_variant_member(document, image_sources, "outfit", a)
    assert document.history.revision == revision_before
    assert document.variant_sets["outfit"]["members"] == [a]


def test_save_expression_does_not_touch_live_active_selection(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    add_variant_member(document, image_sources, "outfit", b)
    assert document.variant_sets["outfit"]["active"] == a

    save_expression(document, image_sources, "casual", {"outfit": b})

    assert document.expressions["casual"]["variants"] == {"outfit": b}
    assert document.variant_sets["outfit"]["active"] == a  # unchanged -- preview/save only
    assert document.instances[a].visible is True


def test_save_and_apply_expression_is_one_undo_step(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    add_variant_member(document, image_sources, "outfit", b)
    revision_before = document.history.revision

    save_and_apply_expression(document, image_sources, "casual", {"outfit": b})

    assert document.expressions["casual"]["variants"] == {"outfit": b}
    assert document.variant_sets["outfit"]["active"] == b
    assert document.instances[b].visible is True
    assert document.history.revision == revision_before + 1

    document.undo()
    assert document.variant_sets["outfit"]["active"] == a
    assert "casual" not in document.expressions


def test_save_and_apply_expression_updates_an_existing_preset_in_place(loaded):
    document, image_sources = loaded
    a, b = _ids(document)[:2]
    add_variant_member(document, image_sources, "outfit", a)
    add_variant_member(document, image_sources, "outfit", b)
    save_and_apply_expression(document, image_sources, "casual", {"outfit": a})
    assert document.variant_sets["outfit"]["active"] == a

    save_and_apply_expression(document, image_sources, "casual", {"outfit": b})

    assert document.expressions["casual"]["variants"] == {"outfit": b}
    assert document.variant_sets["outfit"]["active"] == b


def test_invalid_expression_member_rolls_back_without_partial_mutation(loaded):
    document, image_sources = loaded
    a = _ids(document)[0]
    add_variant_member(document, image_sources, "outfit", a)
    revision_before = document.history.revision

    with pytest.raises(Exception):
        save_and_apply_expression(document, image_sources, "casual", {"outfit": "no_such_instance"})

    assert document.history.revision == revision_before
    assert "casual" not in document.expressions
