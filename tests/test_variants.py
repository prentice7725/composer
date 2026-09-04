from __future__ import annotations

import pytest

from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument
from portrait_composer.instances import LayerInstance
from portrait_composer.variants import VariantSetError, add_variant_set, remove_member, remove_variant_set, set_active


def _doc():
    doc = AssemblyDocument()
    with doc.transaction():
        for m in ("mouth_neutral", "mouth_a", "mouth_i"):
            doc.add_asset(AssetDefinition(id=f"a_{m}", semantic="mouth"))
            doc.add_instance(LayerInstance(id=m, asset_ref=f"a_{m}", slot="mouth", draw_order=1))
        doc.composition["draw_order"] = ["mouth_neutral", "mouth_a", "mouth_i"]
    return doc


def test_add_variant_set_sets_default_as_active_and_applies_exclusive_visibility():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a", "mouth_i"], default="mouth_neutral")

    vs = doc.variant_sets["mouth"]
    assert vs["active"] == "mouth_neutral"
    assert doc.instances["mouth_neutral"].visible is True
    assert doc.instances["mouth_a"].visible is False
    assert doc.instances["mouth_i"].visible is False
    assert doc.validate().ok


def test_set_active_is_the_exclusive_switch_operation():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a", "mouth_i"], default="mouth_neutral")
    with doc.transaction():
        set_active(doc, "mouth", "mouth_a")

    assert doc.variant_sets["mouth"]["active"] == "mouth_a"
    assert doc.instances["mouth_neutral"].visible is False
    assert doc.instances["mouth_a"].visible is True
    assert doc.instances["mouth_i"].visible is False


def test_set_active_unknown_member_raises():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a"], default="mouth_neutral")
    with pytest.raises(VariantSetError):
        with doc.transaction():
            set_active(doc, "mouth", "mouth_i")


def test_remove_variant_set():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a"], default="mouth_neutral")
    with doc.transaction():
        remove_variant_set(doc, "mouth")
    assert "mouth" not in doc.variant_sets


def test_default_not_in_members_raises_at_authoring_time():
    doc = _doc()
    with pytest.raises(VariantSetError):
        with doc.transaction():
            add_variant_set(doc, "mouth", members=["mouth_neutral"], default="mouth_a")


def test_active_not_in_members_is_hard_error_on_manual_edit():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a"], default="mouth_neutral")
    doc.variant_sets["mouth"]["active"] = "ghost"
    result = doc.validate()
    assert not result.ok
    assert any("active" in e and "not in members" in e for e in result.errors)


def test_remove_member_reassigns_default_and_active_to_a_remaining_member():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a", "mouth_i"], default="mouth_neutral")
    with doc.transaction():
        remove_member(doc, "mouth", "mouth_neutral")

    vs = doc.variant_sets["mouth"]
    assert "mouth_neutral" not in vs["members"]
    assert vs["default"] != "mouth_neutral"
    assert vs["active"] != "mouth_neutral"
    assert doc.instances[vs["active"]].visible is True
    assert doc.validate().ok


def test_remove_member_of_a_non_active_non_default_member_leaves_active_untouched():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a", "mouth_i"], default="mouth_neutral")
    with doc.transaction():
        remove_member(doc, "mouth", "mouth_i")

    vs = doc.variant_sets["mouth"]
    assert vs["active"] == "mouth_neutral"
    assert vs["default"] == "mouth_neutral"


def test_remove_member_refuses_to_empty_a_variant_set():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral"], default="mouth_neutral")
    with pytest.raises(VariantSetError, match="only member"):
        with doc.transaction():
            remove_member(doc, "mouth", "mouth_neutral")
    assert doc.variant_sets["mouth"]["members"] == ["mouth_neutral"]


def test_remove_member_unknown_member_raises():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a"], default="mouth_neutral")
    with pytest.raises(VariantSetError, match="is not a member"):
        with doc.transaction():
            remove_member(doc, "mouth", "mouth_i")


def test_undo_restores_previous_active_member_and_visibility():
    doc = _doc()
    with doc.transaction():
        add_variant_set(doc, "mouth", members=["mouth_neutral", "mouth_a", "mouth_i"], default="mouth_neutral")
    with doc.transaction():
        set_active(doc, "mouth", "mouth_a")

    doc.undo()
    assert doc.variant_sets["mouth"]["active"] == "mouth_neutral"
    assert doc.instances["mouth_neutral"].visible is True
    assert doc.instances["mouth_a"].visible is False
