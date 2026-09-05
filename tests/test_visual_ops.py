from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.visual_ops import VisualOpError, add_visual_op, apply_visual_ops, reorder_visual_op

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait", size=(8, 8)))
    return identity_assembly(bundle)


def test_visual_ops_are_ordered_serialized_and_undoable(tmp_path: Path):
    document, _, _ = _doc(tmp_path)
    instance_id = "topwear__instance"

    add_visual_op(
        document,
        instance_id,
        {"id": "tone", "type": "color", "params": {"saturation": 0.5}},
    )
    add_visual_op(
        document,
        instance_id,
        {"id": "mask", "type": "mask", "params": {"path": "mask.png"}},
    )

    assert [op["id"] for op in document.instances[instance_id].visual_ops] == ["tone", "mask"]
    restored = type(document).from_dict(document.to_dict())
    assert restored.instances[instance_id].visual_ops == document.instances[instance_id].visual_ops

    document.undo()
    assert [op["id"] for op in document.instances[instance_id].visual_ops] == ["tone"]
    document.undo()
    assert document.instances[instance_id].visual_ops == []
    document.redo()
    document.redo()
    assert [op["id"] for op in document.instances[instance_id].visual_ops] == ["tone", "mask"]


def test_visual_ops_evaluate_without_mutating_source_and_keep_stack_order(tmp_path: Path):
    source = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    mask_path = tmp_path / "mask.png"
    Image.new("L", (8, 8), 128).save(mask_path)
    ops = [
        {"id": "tone", "type": "color", "params": {"saturation": 0.0, "brightness": 0.5}},
        {"id": "mask", "type": "mask", "params": {"path": mask_path.name}},
    ]

    result = apply_visual_ops(source, ops, base_dir=tmp_path)
    assert source.getpixel((0, 0)) == (255, 0, 0, 255)
    assert result.getpixel((0, 0))[3] == 128
    assert result.getpixel((0, 0))[:3] == (38, 38, 38)


def test_visual_ops_reject_invalid_stack_and_support_reorder(tmp_path: Path):
    document, _, _ = _doc(tmp_path)
    instance_id = "topwear__instance"
    add_visual_op(document, instance_id, {"id": "a", "type": "color", "params": {}})
    add_visual_op(document, instance_id, {"id": "b", "type": "color", "params": {}})

    reorder_visual_op(document, instance_id, "b", 0)
    assert [op["id"] for op in document.instances[instance_id].visual_ops] == ["b", "a"]
    with pytest.raises(VisualOpError):
        add_visual_op(document, instance_id, {"id": "bad", "type": "quad_warp", "params": {"quad": [1, 2]}})
