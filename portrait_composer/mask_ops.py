"""Copy-on-write mask editing primitives (C6-F).

Mask pixels are separate PNG artifacts.  A stroke creates a new revision and
the document transaction swaps the VisualOp path to that revision, so undo
restores the previous mask without mutating the old file.
"""
from __future__ import annotations

import copy
from math import isfinite
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from .visual_ops import VisualOpError, update_visual_op


class MaskEditError(ValueError):
    pass


def _resolve(path: str, base_dir: Path | None) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = Path(base_dir) / candidate
    return candidate


def edit_mask_stroke(
    document,
    instance_id: str,
    op_id: str,
    *,
    points: list[tuple[float, float]],
    radius: float,
    mode: str,
    strength: float = 1.0,
    work_dir: Path,
    base_dir: Path | None = None,
) -> Path | None:
    """Apply one erase/restore stroke and commit it as one undo step."""
    if mode not in {"erase", "restore"}:
        raise MaskEditError("mask stroke mode must be 'erase' or 'restore'")
    if not points:
        raise MaskEditError("mask stroke needs at least one point")
    if radius <= 0:
        raise MaskEditError("mask stroke radius must be positive")
    try:
        strength_value = float(strength)
    except (TypeError, ValueError) as exc:
        raise MaskEditError("mask stroke strength must be between 0 and 1") from exc
    if not isfinite(strength_value) or not 0.0 <= strength_value <= 1.0:
        raise MaskEditError("mask stroke strength must be between 0 and 1")
    if strength_value == 0:
        return None

    instance = document.instances.get(instance_id)
    if instance is None:
        raise MaskEditError(f"no such instance: {instance_id!r}")
    op = next((item for item in instance.visual_ops if item.get("id") == op_id), None)
    if op is None or op.get("type") != "mask":
        raise MaskEditError(f"no such mask visual op: {op_id!r}")
    source = _resolve(op.get("params", {}).get("path", ""), base_dir)
    if not source.exists():
        raise MaskEditError(f"mask file missing: {source}")

    with Image.open(source) as raw:
        mask = raw.convert("L")
    original = mask.copy()
    stroke_mask = Image.new("L", mask.size, 0)
    draw = ImageDraw.Draw(stroke_mask)
    scaled_points = [(round(float(x)), round(float(y))) for x, y in points]
    width = max(1, round(float(radius) * 2))
    draw.line(scaled_points, fill=255, width=width, joint="curve")
    half = width / 2.0
    for x, y in scaled_points:
        draw.ellipse((round(x - half), round(y - half), round(x + half), round(y + half)), fill=255)
    target = Image.new("L", mask.size, 0 if mode == "erase" else 255)
    blended = Image.blend(mask, target, strength_value)
    mask = Image.composite(blended, mask, stroke_mask)
    if ImageChops.difference(original, mask).getbbox() is None:
        return None

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    revision = 1
    while True:
        destination = work_dir / f"{instance_id}__{op_id}__rev{revision}.png"
        if not destination.exists():
            break
        revision += 1
    mask.save(destination)

    params = copy.deepcopy(op.get("params", {}))
    params["path"] = str(destination)
    update_visual_op(document, instance_id, op_id, params=params)
    return destination

