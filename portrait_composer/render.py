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

``render_reference`` reads images from an on-disk ``layers/<instance_id>.png``
convention (an already-written Assembly Bundle). ``render_subset`` (C2,
bake.py's compositor) instead resolves images through a caller-given
``image_sources``-style {instance_id: Path} map and an explicit instance
list -- bake needs to composite a handful of not-yet-written source
instances into one new image before any bundle exists on disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

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


def _composite(
    document: "AssemblyDocument",
    instance_ids: list,
    resolve_path: Callable[[str], Optional[Path]],
    canvas_size: tuple,
) -> Image.Image:
    width, height = canvas_size
    composite = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    for inst_id in instance_ids:
        inst = document.instances.get(inst_id)
        if inst is None or not inst.visible or inst.opacity <= 0.0:
            continue
        path = resolve_path(inst_id)
        if path is None or not Path(path).exists():
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

    return _composite(document, draw_order, lambda iid: layer_image_path(layers_dir, iid), (width, height))


def render_subset(document: "AssemblyDocument", image_sources: dict, instance_ids: list) -> Image.Image:
    """Composites just ``instance_ids`` (in the given order), resolving each
    one's image through ``image_sources`` ({instance_id: Path}) instead of
    an on-disk ``layers/`` convention. Requires ``composition.canvas`` to
    already be set -- bake operates on an already-imported/harvested
    document, which always has one (C0.5/C1 both populate it)."""
    canvas = document.composition.get("canvas") or {}
    width, height = canvas.get("width"), canvas.get("height")
    if width is None or height is None:
        raise ValueError("render_subset requires document.composition['canvas'] to be set")

    return _composite(document, instance_ids, lambda iid: image_sources.get(iid), (width, height))
