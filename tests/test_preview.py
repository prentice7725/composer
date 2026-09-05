from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.preview import PreviewState
from portrait_composer.render import render_subset
from portrait_composer.visual_ops import add_visual_op

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    return identity_assembly(bundle)


def test_preview_is_transient_and_uses_canonical_renderer(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    instance_id = "topwear__instance"
    document.mark_saved()
    before = document.to_dict()
    preview = PreviewState()
    preview.begin()
    preview.set_visual_ops(
        instance_id,
        [{"id": "preview-tone", "type": "color", "params": {"brightness": 0.5}}],
    )
    preview.set_transform(instance_id, {"x": 3.0, "y": 4.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0})

    rendered = render_subset(
        document,
        image_sources,
        [instance_id],
        transform_overrides=preview.transform_overrides,
        visual_ops_overrides=preview.visual_ops_overrides,
    )
    assert rendered.size == (40, 40)
    assert document.to_dict() == before
    assert not document.dirty
    preview.clear()
    assert preview.snapshot() == {"active": False, "transform_overrides": {}, "visual_ops_overrides": {}}
