from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.mask_ops import edit_mask_stroke
from portrait_composer.visual_ops import add_visual_op

from .conftest import make_portrait_bundle


def test_mask_stroke_is_copy_on_write_and_one_undo_step(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    document, _, _ = identity_assembly(bundle)
    instance_id = "topwear__instance"
    original = tmp_path / "mask.png"
    Image.new("L", (20, 20), 255).save(original)
    add_visual_op(document, instance_id, {"id": "mask", "type": "mask", "params": {"path": str(original)}})
    document.mark_saved()
    before = document.to_dict()

    revised = edit_mask_stroke(
        document,
        instance_id,
        "mask",
        points=[(10, 10)],
        radius=3,
        mode="erase",
        work_dir=tmp_path / "revisions",
    )
    assert revised.exists()
    assert revised != original
    assert Image.open(original).getpixel((10, 10)) == 255
    assert Image.open(revised).getpixel((10, 10)) == 0
    assert document.dirty

    document.undo()
    assert document.to_dict() == before
    assert document.instances[instance_id].visual_ops[0]["params"]["path"] == str(original)

