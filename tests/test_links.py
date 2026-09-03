from __future__ import annotations

import pytest

from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument, TransactionValidationError
from portrait_composer.instances import LayerInstance
from portrait_composer.links import LinkError, add_member, apply_delta, create_link, dissolve_link, remove_member


def _doc():
    doc = AssemblyDocument()
    with doc.transaction():
        for i in ("hood", "cloak"):
            doc.add_asset(AssetDefinition(id=f"a_{i}", semantic="topwear"))
            doc.add_instance(LayerInstance(id=i, asset_ref=f"a_{i}", slot="torso", draw_order=1))
        doc.composition["draw_order"] = ["hood", "cloak"]
    return doc


def test_create_link_is_the_transform_link_creation_operation():
    doc = _doc()
    with doc.transaction():
        create_link(doc, "outfit_main", ["hood", "cloak"])

    assert doc.links["outfit_main"]["members"] == ["hood", "cloak"]
    assert doc.instances["hood"].transform_link == "outfit_main"
    assert doc.instances["cloak"].transform_link == "outfit_main"
    assert doc.validate().ok


def test_dissolve_link_is_the_transform_link_release_operation():
    doc = _doc()
    with doc.transaction():
        create_link(doc, "outfit_main", ["hood", "cloak"])
    with doc.transaction():
        dissolve_link(doc, "outfit_main")

    assert "outfit_main" not in doc.links
    assert doc.instances["hood"].transform_link is None
    assert doc.instances["cloak"].transform_link is None
    assert doc.validate().ok


def test_apply_delta_moves_every_member_together():
    doc = _doc()
    with doc.transaction():
        create_link(doc, "outfit_main", ["hood", "cloak"])
    with doc.transaction():
        apply_delta(doc, "outfit_main", dx=5, dy=-3, drotation=2)

    assert doc.instances["hood"].transform.x == 5
    assert doc.instances["cloak"].transform.x == 5
    assert doc.instances["hood"].transform.y == -3
    assert doc.instances["cloak"].transform.rotation == 2


def test_add_member_and_remove_member():
    doc = _doc()
    with doc.transaction():
        create_link(doc, "outfit_main", ["hood"])
    with doc.transaction():
        add_member(doc, "outfit_main", "cloak")
    assert doc.instances["cloak"].transform_link == "outfit_main"

    with doc.transaction():
        remove_member(doc, "outfit_main", "hood")
    assert doc.instances["hood"].transform_link is None
    assert doc.links["outfit_main"]["members"] == ["cloak"]


def test_create_link_unknown_instance_raises():
    doc = _doc()
    with pytest.raises(LinkError):
        with doc.transaction():
            create_link(doc, "outfit_main", ["hood", "ghost"])


def test_inconsistent_transform_link_is_hard_error():
    doc = _doc()
    doc.instances["hood"].transform_link = "outfit_main"
    doc.links["outfit_main"] = {"members": ["cloak"]}  # doesn't list "hood"
    result = doc.validate()
    assert not result.ok
    assert any("does not list it as a member" in e for e in result.errors)


def test_link_member_not_matching_its_own_transform_link_is_hard_error():
    doc = _doc()
    doc.links["outfit_main"] = {"members": ["hood"]}
    # hood.transform_link is still None -- inconsistent with membership
    result = doc.validate()
    assert not result.ok
    assert any("transform_link is None" in e for e in result.errors)
