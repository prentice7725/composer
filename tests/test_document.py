from __future__ import annotations

import pytest

from portrait_composer.assets import AssetDefinition
from portrait_composer.document import AssemblyDocument, DuplicateIdError, TransactionValidationError
from portrait_composer.instances import LayerInstance


def _asset(id="a1", semantic="topwear"):
    return AssetDefinition(id=id, semantic=semantic)


def _instance(id="i1", asset_ref="a1", slot="torso", draw_order=10):
    return LayerInstance(id=id, asset_ref=asset_ref, slot=slot, draw_order=draw_order)


def test_transaction_commits_valid_change():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(_asset())
        doc.add_instance(_instance())
        doc.composition["draw_order"] = ["i1"]

    assert "a1" in doc.assets
    assert "i1" in doc.instances
    assert doc.dirty is True
    assert doc.history.can_undo()


def test_transaction_rolls_back_on_validation_failure():
    doc = AssemblyDocument()
    with pytest.raises(TransactionValidationError):
        with doc.transaction():
            # instance references an asset that doesn't exist -> hard error
            doc.add_instance(_instance())

    assert doc.instances == {}
    assert doc.dirty is False
    assert not doc.history.can_undo()


def test_transaction_rolls_back_on_exception():
    doc = AssemblyDocument()
    with pytest.raises(RuntimeError):
        with doc.transaction():
            doc.add_asset(_asset())
            raise RuntimeError("boom")

    assert doc.assets == {}
    assert doc.dirty is False


def test_duplicate_asset_id_rejected_immediately():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(_asset())
    with pytest.raises(DuplicateIdError):
        with doc.transaction():
            doc.add_asset(_asset())


def test_instance_id_colliding_with_asset_id_is_hard_error():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(_asset(id="shared"))
    with pytest.raises(TransactionValidationError):
        with doc.transaction():
            doc.add_asset(_asset(id="other"))
            doc.add_instance(_instance(id="shared", asset_ref="other"))


def test_undo_redo_round_trip():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(_asset())
        doc.add_instance(_instance())
        doc.composition["draw_order"] = ["i1"]

    with doc.transaction():
        doc.instances["i1"].visible = False

    assert doc.instances["i1"].visible is False

    doc.undo()
    assert doc.instances["i1"].visible is True

    doc.redo()
    assert doc.instances["i1"].visible is False


def test_mark_saved_clears_dirty():
    doc = AssemblyDocument()
    with doc.transaction():
        doc.add_asset(_asset())
        doc.add_instance(_instance())
        doc.composition["draw_order"] = ["i1"]

    assert doc.dirty is True
    doc.mark_saved()
    assert doc.dirty is False

    with doc.transaction():
        doc.instances["i1"].opacity = 0.5
    assert doc.dirty is True

    doc.undo()
    assert doc.dirty is False  # back to the saved revision
