"""End-to-end regression, directive #32 C0 exit checklist item "regression".

Runs the full C0/C0.5 loop -- identity import from a real-contract Portrait
Bundle, recipe apply, validate, render, save/undo/redo -- against one
fixture bundle and checks nothing along the chain silently corrupts the
document.
"""
from __future__ import annotations

import json
from pathlib import Path

from portrait_composer.assembly import apply_recipe, identity_assembly
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.render import render_reference


def test_full_c0_pipeline(portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)

    document, image_sources, import_warnings = identity_assembly(bundle)
    assert import_warnings == []
    assert document.validate().ok
    document.mark_saved()

    recipe = {
        "operations": [
            {"op": "set_transform", "instance": "topwear__instance", "transform": {"x": 2, "y": -1}},
            {"op": "reorder_draw_order", "draw_order": ["neck__instance", "head__instance", "topwear__instance"]},
        ]
    }
    apply_recipe(document, recipe, image_sources)
    assert document.dirty

    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)

    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.composition["draw_order"] == ["neck__instance", "head__instance", "topwear__instance"]
    assert reloaded.instances["topwear__instance"].transform.x == 2
    assert reloaded.validate().ok

    # reference.png on disk must match a fresh render from the reloaded document
    rerendered = render_reference(reloaded, out_dir / "layers")
    from PIL import Image
    on_disk = Image.open(out_dir / "reference.png").convert("RGBA")
    assert rerendered.tobytes() == on_disk.tobytes()

    # undo the recipe, confirm draw order/transform revert
    document.undo()
    assert document.composition["draw_order"] == [
        "neck__instance",
        "topwear__instance",
        "head__instance",
    ]
    assert document.instances["topwear__instance"].transform.x == 0
    assert not document.dirty  # back to the mark_saved() revision
