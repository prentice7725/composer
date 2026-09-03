from __future__ import annotations

import pytest

from portrait_composer import hierarchy as H
from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument, TransactionValidationError
from portrait_composer.instances import LayerInstance


def _doc_with_instances(*ids):
    doc = AssemblyDocument()
    with doc.transaction():
        for i in ids:
            doc.add_asset(AssetDefinition(id=f"a_{i}", semantic="topwear"))
            doc.add_instance(LayerInstance(id=i, asset_ref=f"a_{i}", slot="torso", draw_order=1))
        doc.composition["draw_order"] = list(ids)
    return doc


def test_add_node_creates_root_and_child():
    doc = _doc_with_instances("i1", "i2")
    with doc.transaction():
        H.add_node(doc, "grp", label="Upper Body")
        H.add_node(doc, "n1", parent="grp", ref="i1")
        H.add_node(doc, "n2", parent="grp", ref="i2")

    assert H.children_of(doc, None) == ["grp"]
    assert H.children_of(doc, "grp") == ["n1", "n2"]
    assert doc.validate().ok


def test_move_node_is_the_hierarchy_reorder_operation():
    doc = _doc_with_instances("i1", "i2")
    with doc.transaction():
        H.add_node(doc, "grp_a", label="A")
        H.add_node(doc, "grp_b", label="B")
        H.add_node(doc, "n1", parent="grp_a", ref="i1")

    with doc.transaction():
        H.move_node(doc, "n1", new_parent="grp_b")

    assert H.children_of(doc, "grp_a") == []
    assert H.children_of(doc, "grp_b") == ["n1"]


def test_move_node_reorders_siblings_by_index():
    doc = _doc_with_instances("i1", "i2")
    with doc.transaction():
        H.add_node(doc, "n1", ref="i1")
        H.add_node(doc, "n2", ref="i2")
    assert H.children_of(doc, None) == ["n1", "n2"]

    with doc.transaction():
        H.move_node(doc, "n2", new_parent=None, index=0)
    assert H.children_of(doc, None) == ["n2", "n1"]


def test_remove_node_reparents_children_instead_of_deleting_them():
    doc = _doc_with_instances("i1")
    with doc.transaction():
        H.add_node(doc, "grp", label="Group")
        H.add_node(doc, "n1", parent="grp", ref="i1")

    with doc.transaction():
        H.remove_node(doc, "grp")

    assert "grp" not in doc.hierarchy["nodes"]
    assert H.children_of(doc, None) == ["n1"]
    assert doc.hierarchy["nodes"]["n1"]["parent"] is None


def test_hierarchy_missing_parent_is_hard_error():
    doc = _doc_with_instances("i1")
    doc.hierarchy = {"nodes": {"n1": {"parent": "ghost", "ref": "i1", "label": None}}, "children": {}}
    result = doc.validate()
    assert not result.ok
    assert any("missing parent" in e for e in result.errors)


def test_hierarchy_dangling_ref_is_hard_error():
    doc = _doc_with_instances("i1")
    doc.hierarchy = {"nodes": {"n1": {"parent": None, "ref": "ghost", "label": None}}, "children": {"": ["n1"]}}
    result = doc.validate()
    assert not result.ok
    assert any("is not an instance" in e for e in result.errors)


def test_hierarchy_cycle_is_hard_error():
    doc = _doc_with_instances()
    doc.hierarchy = {
        "nodes": {
            "a": {"parent": "b", "ref": None, "label": None},
            "b": {"parent": "a", "ref": None, "label": None},
        },
        "children": {"a": ["b"], "b": ["a"]},
    }
    result = doc.validate()
    assert not result.ok
    assert any("cycle" in e for e in result.errors)


def test_hierarchy_edits_participate_in_transaction_rollback():
    doc = _doc_with_instances("i1")
    with pytest.raises(TransactionValidationError):
        with doc.transaction():
            H.add_node(doc, "n1", ref="ghost")  # dangling ref -> validation fail
    assert doc.hierarchy.get("nodes", {}) == {}
