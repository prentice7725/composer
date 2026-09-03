from __future__ import annotations

import pytest

from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument
from portrait_composer.instances import LayerInstance
from portrait_composer.slots import SLOT_VOCABULARY, SlotError, is_known_slot, set_plane, set_slot


def _doc():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(AssetDefinition(id="uniform", semantic="topwear", planes=["sleeve_back", "torso", "sleeve_front"]))
        doc.add_instance(LayerInstance(id="i1", asset_ref="uniform", slot="torso", draw_order=1))
        doc.composition["draw_order"] = ["i1"]
    return doc


def test_known_slots_cover_the_directive_vocabulary():
    for slot in ("torso", "hair_front", "headwear", "eye", "mouth"):
        assert is_known_slot(slot)
    assert not is_known_slot("banana")
    assert len(SLOT_VOCABULARY) == 13


def test_set_slot_is_the_slot_change_operation():
    doc = _doc()
    with doc.transaction():
        set_slot(doc, "i1", "torso_front")
    assert doc.instances["i1"].slot == "torso_front"
    assert doc.validate().ok


def test_unknown_slot_is_a_warning_not_a_hard_error():
    doc = _doc()
    with doc.transaction():
        set_slot(doc, "i1", "banana")
    result = doc.validate()
    assert result.ok
    assert any("SLOT_VOCABULARY" in w for w in result.warnings)


def test_set_slot_unknown_instance_raises():
    doc = _doc()
    with pytest.raises(SlotError):
        with doc.transaction():
            set_slot(doc, "ghost", "torso")


def test_plane_must_belong_to_asset_planes():
    doc = _doc()
    with doc.transaction():
        set_plane(doc, "i1", "sleeve_back")
    assert doc.validate().ok

    with pytest.raises(Exception):
        with doc.transaction():
            set_plane(doc, "i1", "not_a_declared_plane")
    assert doc.instances["i1"].plane == "sleeve_back"  # rolled back to the last valid state


def test_multi_plane_asset_placed_via_multiple_instances():
    """directive #14: one asset, several planes, several instances/slots."""
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(
            AssetDefinition(id="uniform", semantic="topwear", planes=["sleeve_back", "torso", "sleeve_front"])
        )
        doc.add_instance(
            LayerInstance(id="i_back", asset_ref="uniform", slot="torso_back", draw_order=1, plane="sleeve_back")
        )
        doc.add_instance(
            LayerInstance(id="i_main", asset_ref="uniform", slot="torso", draw_order=2, plane="torso")
        )
        doc.add_instance(
            LayerInstance(id="i_front", asset_ref="uniform", slot="torso_front", draw_order=3, plane="sleeve_front")
        )
        doc.composition["draw_order"] = ["i_back", "i_main", "i_front"]

    assert doc.validate().ok
    assert {i.plane for i in doc.instances.values()} == {"sleeve_back", "torso", "sleeve_front"}
