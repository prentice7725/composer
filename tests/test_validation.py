from __future__ import annotations

from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument
from portrait_composer.instances import LayerInstance
from portrait_composer.sources import SourceAsset, SourceBinding


def test_missing_source_is_hard_error():
    doc = AssemblyDocument()
    doc.assets["a1"] = AssetDefinition(
        id="a1", semantic="topwear",
        source_binding=SourceBinding(source_id="nope", revision="sha256:x", source_layer_id="l1"),
    )
    result = doc.validate()
    assert not result.ok
    assert any("missing source" in e for e in result.errors)


def test_missing_asset_ref_is_hard_error():
    doc = AssemblyDocument()
    doc.instances["i1"] = LayerInstance(id="i1", asset_ref="ghost", slot="torso", draw_order=1)
    result = doc.validate()
    assert not result.ok
    assert any("missing asset" in e for e in result.errors)


def test_invalid_draw_order_ref_is_hard_error():
    doc = AssemblyDocument()
    doc.composition["draw_order"] = ["ghost"]
    result = doc.validate()
    assert not result.ok
    assert any("invalid instance ref" in e for e in result.errors)


def test_duplicate_draw_order_ref_is_hard_error():
    doc = AssemblyDocument()
    doc.assets["a1"] = AssetDefinition(id="a1", semantic="topwear")
    doc.instances["i1"] = LayerInstance(id="i1", asset_ref="a1", slot="torso", draw_order=1)
    doc.composition["draw_order"] = ["i1", "i1"]
    result = doc.validate()
    assert not result.ok
    assert any("duplicate instance ref" in e for e in result.errors)


def test_unresolved_source_binding_only_fails_production_export():
    doc = AssemblyDocument()
    doc.assets["a1"] = AssetDefinition(id="a1", semantic="topwear", source_binding=None)
    assert doc.validate(production=False).ok
    result = doc.validate(production=True)
    assert not result.ok
    assert any("unresolved source binding" in e for e in result.errors)


def test_invalid_variant_set_member_is_hard_error():
    doc = AssemblyDocument()
    doc.variant_sets["mouth"] = {"mode": "exclusive", "default": "ghost", "members": ["ghost"]}
    result = doc.validate()
    assert not result.ok
    assert any("invalid member" in e for e in result.errors)


def test_variant_set_default_not_in_members_is_hard_error():
    doc = AssemblyDocument()
    doc.assets["mouth_a"] = AssetDefinition(id="mouth_a", semantic="mouth")
    doc.variant_sets["mouth"] = {"mode": "exclusive", "default": "mouth_b", "members": ["mouth_a"]}
    result = doc.validate()
    assert not result.ok
    assert any("default" in e and "not in members" in e for e in result.errors)


def test_broken_attachment_target_is_hard_error():
    doc = AssemblyDocument()
    doc.rig_intent["attachments"]["front_hair_attach"] = {"child": "hair_front", "target": "ghost_head", "mode": "follow"}
    result = doc.validate()
    assert not result.ok
    assert any("broken attachment" in e for e in result.errors)


def test_invalid_rig_region_target_is_hard_error():
    doc = AssemblyDocument()
    doc.rig_intent["regions"]["upper_torso_secondary"] = {"target": "ghost"}
    result = doc.validate()
    assert not result.ok
    assert any("rig_intent.regions" in e for e in result.errors)


def test_duplicate_stable_id_across_asset_and_instance_is_hard_error():
    doc = AssemblyDocument()
    doc.assets["shared"] = AssetDefinition(id="shared", semantic="topwear")
    doc.instances["shared"] = LayerInstance(id="shared", asset_ref="shared", slot="torso", draw_order=1)
    result = doc.validate()
    assert not result.ok
    assert any("duplicate stable ID" in e for e in result.errors)


def test_instance_missing_from_draw_order_is_warning_not_error():
    doc = AssemblyDocument()
    doc.assets["a1"] = AssetDefinition(id="a1", semantic="topwear")
    doc.instances["i1"] = LayerInstance(id="i1", asset_ref="a1", slot="torso", draw_order=1)
    result = doc.validate()
    assert result.ok
    assert any("not present in composition.draw_order" in w for w in result.warnings)
