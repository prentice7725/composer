"""Ordered, non-destructive VisualOps (C6-A foundation).

VisualOps belong to a LayerInstance, are evaluated in serialized order, and
never modify the source PNG.  This module owns the small canonical operation
set used by v0.3's first implementation slice; GUI gestures can use the
transactional helpers while drag/slider previews stay outside the document.
"""
from __future__ import annotations

import copy
from math import isfinite
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

VISUAL_OP_TYPES = ("color", "mask", "quad_warp")


class VisualOpError(ValueError):
    pass


def _run_authoring(document, operation):
    if document.in_transaction:
        return operation()
    with document.transaction():
        return operation()


def _normalise_op(op: dict) -> dict:
    if not isinstance(op, dict):
        raise VisualOpError("visual op must be an object")
    op_id = op.get("id")
    op_type = op.get("type")
    if not isinstance(op_id, str) or not op_id:
        raise VisualOpError("visual op id must be non-empty")
    if op_type not in VISUAL_OP_TYPES:
        raise VisualOpError(f"unknown visual op type {op_type!r}; expected {VISUAL_OP_TYPES!r}")
    params = op.get("params", {})
    if not isinstance(params, dict):
        raise VisualOpError("visual op params must be an object")
    result = {"id": op_id, "type": op_type, "enabled": bool(op.get("enabled", True)), "params": copy.deepcopy(params)}
    _validate_params(result)
    return result


def _finite_number(value, label: str) -> None:
    if not isinstance(value, (int, float)) or not isfinite(value):
        raise VisualOpError(f"{label} must be a finite number")


def _validate_params(op: dict) -> None:
    params = op["params"]
    if op["type"] == "color":
        for name in ("saturation", "brightness", "contrast"):
            if name in params:
                _finite_number(params[name], f"color.{name}")
    elif op["type"] == "mask":
        path = params.get("path")
        if not isinstance(path, str) or not path:
            raise VisualOpError("mask.path must be a non-empty path")
        if "feather" in params:
            _finite_number(params["feather"], "mask.feather")
            if params["feather"] < 0:
                raise VisualOpError("mask.feather must be non-negative")
    elif op["type"] == "quad_warp":
        quad = params.get("quad")
        if not isinstance(quad, list) or len(quad) != 8:
            raise VisualOpError("quad_warp.quad must contain 8 numbers")
        for index, value in enumerate(quad):
            _finite_number(value, f"quad_warp.quad[{index}]")


def validate_stack(ops: list) -> list[dict]:
    if not isinstance(ops, list):
        raise VisualOpError("visual_ops must be a list")
    normalised = [_normalise_op(op) for op in ops]
    ids = [op["id"] for op in normalised]
    if len(ids) != len(set(ids)):
        raise VisualOpError("visual op ids must be unique within one layer")
    return normalised


def _instance(document, instance_id: str):
    instance = document.instances.get(instance_id)
    if instance is None:
        raise VisualOpError(f"no such instance: {instance_id!r}")
    return instance


def _stack(document, instance_id: str) -> list:
    return _instance(document, instance_id).visual_ops


def add_visual_op(document, instance_id: str, op: dict, *, index: int | None = None) -> dict:
    normalised = _normalise_op(op)

    def mutate():
        stack = _stack(document, instance_id)
        if any(existing.get("id") == normalised["id"] for existing in stack):
            raise VisualOpError(f"visual op id already exists: {normalised['id']!r}")
        position = len(stack) if index is None else index
        if not 0 <= position <= len(stack):
            raise VisualOpError("visual op index out of range")
        stack.insert(position, copy.deepcopy(normalised))
        return copy.deepcopy(normalised)

    return _run_authoring(document, mutate)


def update_visual_op(document, instance_id: str, op_id: str, **changes) -> dict:
    def mutate():
        stack = _stack(document, instance_id)
        for index, current in enumerate(stack):
            if current.get("id") == op_id:
                updated = dict(current)
                updated.update(copy.deepcopy(changes))
                updated["id"] = op_id
                stack[index] = _normalise_op(updated)
                return copy.deepcopy(stack[index])
        raise VisualOpError(f"no such visual op: {op_id!r}")

    return _run_authoring(document, mutate)


def remove_visual_op(document, instance_id: str, op_id: str) -> None:
    def mutate():
        stack = _stack(document, instance_id)
        for index, current in enumerate(stack):
            if current.get("id") == op_id:
                del stack[index]
                return
        raise VisualOpError(f"no such visual op: {op_id!r}")

    _run_authoring(document, mutate)


def reorder_visual_op(document, instance_id: str, op_id: str, new_index: int) -> None:
    def mutate():
        stack = _stack(document, instance_id)
        if not 0 <= new_index < len(stack):
            raise VisualOpError("visual op index out of range")
        old_index = next((index for index, op in enumerate(stack) if op.get("id") == op_id), None)
        if old_index is None:
            raise VisualOpError(f"no such visual op: {op_id!r}")
        op = stack.pop(old_index)
        stack.insert(new_index, op)

    _run_authoring(document, mutate)


def set_visual_op_enabled(document, instance_id: str, op_id: str, enabled: bool) -> dict:
    return update_visual_op(document, instance_id, op_id, enabled=bool(enabled))


def duplicate_visual_op(document, instance_id: str, op_id: str, new_id: str) -> dict:
    stack = _stack(document, instance_id)
    original_index = next((index for index, op in enumerate(stack) if op.get("id") == op_id), None)
    if original_index is None:
        raise VisualOpError(f"no such visual op: {op_id!r}")
    if any(op.get("id") == new_id for op in stack):
        raise VisualOpError(f"visual op id already exists: {new_id!r}")
    duplicate = copy.deepcopy(stack[original_index])
    duplicate["id"] = new_id
    return add_visual_op(document, instance_id, duplicate, index=original_index + 1)


def reset_visual_ops(document, instance_id: str) -> None:
    _run_authoring(document, lambda: setattr(_instance(document, instance_id), "visual_ops", []))


def _resolve_mask_path(path: str, base_dir: Path | None) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    return candidate


def apply_visual_ops(image: Image.Image, ops: list, *, base_dir: Path | None = None) -> Image.Image:
    """Evaluate a serialized stack for canonical rendering.

    The input image is copied/converted; its source file is never touched.
    """
    result = image.convert("RGBA").copy()
    for op in validate_stack(ops):
        if not op["enabled"]:
            continue
        params = op["params"]
        if op["type"] == "color":
            result = ImageEnhance.Color(result).enhance(float(params.get("saturation", 1.0)))
            result = ImageEnhance.Brightness(result).enhance(float(params.get("brightness", 1.0)))
            result = ImageEnhance.Contrast(result).enhance(float(params.get("contrast", 1.0)))
        elif op["type"] == "mask":
            mask_path = _resolve_mask_path(params["path"], base_dir)
            with Image.open(mask_path) as mask_image:
                mask = mask_image.convert("L")
                if mask.size != result.size:
                    mask = mask.resize(result.size, Image.Resampling.LANCZOS)
                feather = float(params.get("feather", 0.0))
                if feather > 0:
                    mask = mask.filter(ImageFilter.GaussianBlur(feather))
                if params.get("invert", False):
                    mask = ImageOps.invert(mask)
                red, green, blue, alpha = result.split()
                result = Image.merge("RGBA", (red, green, blue, ImageChops.multiply(alpha, mask)))
        elif op["type"] == "quad_warp":
            result = result.transform(result.size, Image.Transform.QUAD, tuple(params["quad"]), resample=Image.Resampling.BICUBIC)
    return result
