"""Small deterministic source/target patch colour matching helper (v0.4 U2)."""
from __future__ import annotations

from colorsys import rgb_to_hsv
from math import isfinite
from statistics import median

from PIL import Image

from .visual_ops import add_visual_op


class ColorMatchError(ValueError):
    pass


def _patch_pixels(image: Image.Image, point: tuple[float, float], radius: int) -> list[tuple[int, int, int]]:
    image = image.convert("RGBA")
    cx, cy = round(float(point[0])), round(float(point[1]))
    values = []
    for y in range(max(0, cy - radius), min(image.height, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(image.width, cx + radius + 1)):
            r, g, b, a = image.getpixel((x, y))
            if a > 8:
                values.append((r, g, b))
    if not values:
        raise ColorMatchError("sample patch contains no visible pixels")
    return values


def sample_patch(image: Image.Image, point: tuple[float, float], *, radius: int = 3) -> tuple[int, int, int]:
    """Return a median RGB patch sample, avoiding single-pixel noise."""
    if radius < 0:
        raise ColorMatchError("sample radius must be non-negative")
    values = _patch_pixels(image, point, radius)
    return tuple(round(median(channel)) for channel in zip(*values))


def color_match_params(
    source_rgb: tuple[int, int, int],
    target_rgb: tuple[int, int, int],
    *,
    strength: float = 0.75,
    preserve_luminance: bool = True,
    chroma_strength: float = 0.80,
    lightness_strength: float = 0.35,
) -> dict:
    """Calculate a restrained HSL-like correction for the Color VisualOp.

    The existing VisualOp evaluator intentionally stays simple and
    deterministic.  This computes only saturation/brightness/contrast
    multipliers; it never edits source pixels.
    """
    for value, label in ((strength, "strength"), (chroma_strength, "chroma_strength"), (lightness_strength, "lightness_strength")):
        if not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
            raise ColorMatchError(f"{label} must be between 0 and 1")
    source = tuple(max(0, min(255, int(v))) / 255.0 for v in source_rgb)
    target = tuple(max(0, min(255, int(v))) / 255.0 for v in target_rgb)
    _, source_s, source_v = rgb_to_hsv(*source)
    _, target_s, target_v = rgb_to_hsv(*target)
    saturation_ratio = 1.0 if source_s < 0.02 else target_s / source_s
    value_ratio = 1.0 if source_v < 0.02 else target_v / source_v
    saturation = 1.0 + (saturation_ratio - 1.0) * strength * chroma_strength
    brightness = 1.0 if preserve_luminance else 1.0 + (value_ratio - 1.0) * strength * lightness_strength
    return {
        "saturation": max(0.0, min(4.0, saturation)),
        "brightness": max(0.0, min(4.0, brightness)),
        "contrast": 1.0,
        "color_match": {
            "source_rgb": list(source_rgb),
            "target_rgb": list(target_rgb),
            "strength": strength,
            "preserve_luminance": bool(preserve_luminance),
            "chroma_strength": chroma_strength,
            "lightness_strength": lightness_strength,
        },
    }


def create_color_match_op(
    document,
    instance_id: str,
    *,
    source_image: Image.Image,
    target_image: Image.Image,
    source_point: tuple[float, float],
    target_point: tuple[float, float],
    op_id: str = "color_match",
    radius: int = 3,
    **options,
) -> dict:
    source_rgb = sample_patch(source_image, source_point, radius=radius)
    target_rgb = sample_patch(target_image, target_point, radius=radius)
    params = color_match_params(source_rgb, target_rgb, **options)
    return add_visual_op(document, instance_id, {"id": op_id, "type": "color", "params": params})
