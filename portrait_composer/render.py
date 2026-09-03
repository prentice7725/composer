"""Reference render.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #9, #29;
SEETHROUGH_..._MASTER_v0.2.md #2 ("Assembly Truth").

Composer must always be able to produce ``reference.png``: the canonical
composite of the document as it stands right now, in
``composition.draw_order``, honoring ``visible``/``opacity``/``transform``.

This is intentionally a plain alpha-compositor -- no mesh/deformation/
physics (directive final rule, #0 mission statement in both docs). Rotation
support here is a flat 2D affine convenience for authoring preview; it is
not a rig evaluator.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from .document import AssemblyDocument


def layer_image_path(layers_dir: Path, instance_id: str) -> Path:
    return layers_dir / f"{instance_id}.png"


def _positioned(img: Image.Image, transform) -> tuple[Image.Image, tuple[int, int]]:
    w, h = img.size
    if transform.scale_x != 1.0 or transform.scale_y != 1.0:
        new_w = max(1, round(w * transform.scale_x))
        new_h = max(1, round(h * transform.scale_y))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        w, h = new_w, new_h
    ox, oy = 0, 0
    if transform.rotation:
        pre_w, pre_h = w, h
        img = img.rotate(-transform.rotation, expand=True, resample=Image.BICUBIC)
        w, h = img.size
        ox = (w - pre_w) // 2
        oy = (h - pre_h) // 2
    x = round(transform.x) - ox
    y = round(transform.y) - oy
    return img, (x, y)


def render_reference(document: "AssemblyDocument", layers_dir: Path) -> Image.Image:
    canvas = document.composition.get("canvas") or {}
    width = canvas.get("width")
    height = canvas.get("height")

    draw_order = document.composition.get("draw_order", [])

    if width is None or height is None:
        # infer from the first resolvable layer image
        for inst_id in draw_order:
            p = layer_image_path(layers_dir, inst_id)
            if p.exists():
                with Image.open(p) as im:
                    width, height = im.size
                break
    if width is None or height is None:
        width, height = 1, 1

    composite = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    for inst_id in draw_order:
        inst = document.instances.get(inst_id)
        if inst is None or not inst.visible or inst.opacity <= 0.0:
            continue
        path = layer_image_path(layers_dir, inst_id)
        if not path.exists():
            raise FileNotFoundError(f"layer image missing for instance {inst_id!r}: {path}")
        with Image.open(path) as im:
            im = im.convert("RGBA")
            if inst.opacity < 1.0:
                r, g, b, a = im.split()
                a = a.point(lambda v: round(v * inst.opacity))
                im = Image.merge("RGBA", (r, g, b, a))
            im, (x, y) = _positioned(im, inst.transform)
            composite.alpha_composite(im, dest=(x, y))

    return composite
