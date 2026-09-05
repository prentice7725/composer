"""Transactional transform authoring helpers (C6-E/C6-G).

These are document operations, not preview state.  A caller can calculate a
transient candidate transform during a drag and commit the final values once
on release, preserving the one-gesture/one-undo invariant.
"""
from __future__ import annotations

from .instances import Transform


class TransformOpError(ValueError):
    pass


def _run_authoring(document, operation):
    if document.in_transaction:
        return operation()
    with document.transaction():
        return operation()


def _instance(document, instance_id: str):
    instance = document.instances.get(instance_id)
    if instance is None:
        raise TransformOpError(f"no such instance: {instance_id!r}")
    return instance


def reset_transform(document, instance_id: str) -> None:
    _run_authoring(document, lambda: setattr(_instance(document, instance_id), "transform", Transform()))


def set_uniform_scale(document, instance_id: str, scale: float) -> Transform:
    if not isinstance(scale, (int, float)) or scale == 0:
        raise TransformOpError("uniform scale must be a non-zero number")

    def mutate():
        transform = _instance(document, instance_id).transform
        transform.scale_x = float(scale)
        transform.scale_y = float(scale)
        return transform

    return _run_authoring(document, mutate)


def flip_transform(document, instance_id: str, *, horizontal: bool = False, vertical: bool = False) -> Transform:
    if not horizontal and not vertical:
        raise TransformOpError("flip needs horizontal and/or vertical")

    def mutate():
        transform = _instance(document, instance_id).transform
        if horizontal:
            transform.scale_x *= -1
        if vertical:
            transform.scale_y *= -1
        return transform

    return _run_authoring(document, mutate)


def nudge_transform(document, instance_id: str, *, dx: float = 0.0, dy: float = 0.0) -> Transform:
    def mutate():
        transform = _instance(document, instance_id).transform
        transform.x += float(dx)
        transform.y += float(dy)
        return transform

    return _run_authoring(document, mutate)


def align_instance(
    document,
    instance_id: str,
    *,
    anchor: str = "center",
    target: tuple[float, float, float, float] | None = None,
    image_size: tuple[int, int] | None = None,
) -> Transform:
    """Align an instance's visual rectangle to ``target``.

    ``target`` is ``(x, y, width, height)`` in canvas coordinates.  If it is
    omitted, the document canvas is used.  This operates on placement only;
    no pixels or VisualOps are changed.
    """
    if target is None:
        canvas = document.composition.get("canvas") or {}
        target = (0.0, 0.0, float(canvas.get("width", 0)), float(canvas.get("height", 0)))
    if image_size is None:
        raise TransformOpError("image_size is required for alignment")
    width, height = image_size
    tx, ty, tw, th = target
    if width <= 0 or height <= 0 or tw <= 0 or th <= 0:
        raise TransformOpError("image and target bounds must be positive")

    def mutate():
        transform = _instance(document, instance_id).transform
        scaled_w = width * abs(transform.scale_x)
        scaled_h = height * abs(transform.scale_y)
        if anchor in {"left", "top_left", "bottom_left"}:
            transform.x = tx
        elif anchor in {"right", "top_right", "bottom_right"}:
            transform.x = tx + tw - scaled_w
        else:
            transform.x = tx + (tw - scaled_w) / 2
        if anchor in {"top", "top_left", "top_right"}:
            transform.y = ty
        elif anchor in {"bottom", "bottom_left", "bottom_right"}:
            transform.y = ty + th - scaled_h
        else:
            transform.y = ty + (th - scaled_h) / 2
        return transform

    return _run_authoring(document, mutate)


def fit_instance(
    document,
    instance_id: str,
    *,
    mode: str,
    image_size: tuple[int, int],
    target: tuple[float, float, float, float] | None = None,
) -> Transform:
    """Fit width, height, or bounding box while preserving aspect ratio."""
    if mode not in {"width", "height", "bbox"}:
        raise TransformOpError("fit mode must be 'width', 'height', or 'bbox'")
    if target is None:
        canvas = document.composition.get("canvas") or {}
        target = (0.0, 0.0, float(canvas.get("width", 0)), float(canvas.get("height", 0)))
    _, _, tw, th = target
    width, height = image_size
    if min(width, height, tw, th) <= 0:
        raise TransformOpError("image and target bounds must be positive")
    if mode == "width":
        scale = tw / width
    elif mode == "height":
        scale = th / height
    else:
        scale = min(tw / width, th / height)

    def mutate():
        transform = _instance(document, instance_id).transform
        sign_x = -1 if transform.scale_x < 0 else 1
        sign_y = -1 if transform.scale_y < 0 else 1
        transform.scale_x = sign_x * scale
        transform.scale_y = sign_y * scale
        return transform

    return _run_authoring(document, mutate)
