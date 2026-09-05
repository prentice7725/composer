"""Deterministic seam repair for semantic merge bakes.

This is deliberately a small raster post-process, not a general image editor.
It only runs for ``semantic_merge`` bakes and never mutates source images or
source masks.  AutoRig remains responsible for mesh/deformer quality checks.
"""
from __future__ import annotations

import copy

from PIL import Image, ImageChops, ImageFilter

BAKE_MODES = ("flatten", "semantic_merge")
SEAM_CLEANUP_MODES = ("off", "auto", "aggressive")

_DEFAULT_SEAM_POLICY = {
    "cleanup": "auto",
    "expand_under": 1,
    "remove_internal_lines": True,
    "contact_band_px": 1,
    "ownership_rule": None,
}

BAKE_PROFILES = {
    "topwear_with_arms": {
        "mode": "semantic_merge",
        "seam_policy": {
            **_DEFAULT_SEAM_POLICY,
            "ownership_rule": "topwear_with_arms",
        },
    },
    "body_with_sleeves": {
        "mode": "semantic_merge",
        "seam_policy": {
            **_DEFAULT_SEAM_POLICY,
            "ownership_rule": "body_with_sleeves",
        },
    },
    "coat_full": {
        "mode": "semantic_merge",
        "seam_policy": {
            **_DEFAULT_SEAM_POLICY,
            "ownership_rule": "coat_full",
        },
    },
}


def resolve_bake_mode(result_semantic: str, mode: str | None = None) -> str:
    """Resolve an explicit mode or the known semantic merge profile default."""
    resolved = mode or BAKE_PROFILES.get(result_semantic, {}).get("mode", "flatten")
    if resolved not in BAKE_MODES:
        raise ValueError(f"unknown bake mode {resolved!r}; expected one of {BAKE_MODES!r}")
    return resolved


def normalize_seam_policy(
    policy: dict | None = None,
    *,
    result_semantic: str = "",
    mode: str | None = None,
) -> dict:
    """Return a validated, JSON-safe seam policy.

    A named semantic profile supplies defaults when no policy is provided.
    ``flatten`` still serializes a policy for deterministic round-tripping,
    but its cleanup settings are not evaluated by the renderer.
    """
    resolved_mode = resolve_bake_mode(result_semantic, mode)
    if policy is not None and not isinstance(policy, dict):
        raise ValueError("seam_policy must be an object")
    unknown = set(policy or {}) - set(_DEFAULT_SEAM_POLICY)
    if unknown:
        raise ValueError(f"unsupported seam_policy fields: {sorted(unknown)!r}")
    named = BAKE_PROFILES.get(result_semantic, {}).get("seam_policy", {})
    merged = {**_DEFAULT_SEAM_POLICY, **copy.deepcopy(named), **copy.deepcopy(policy or {})}
    cleanup = merged.get("cleanup")
    if cleanup not in SEAM_CLEANUP_MODES:
        raise ValueError(f"seam_policy.cleanup must be one of {SEAM_CLEANUP_MODES!r}")
    expand_under = merged.get("expand_under")
    if isinstance(expand_under, bool) or not isinstance(expand_under, int) or not 0 <= expand_under <= 2:
        raise ValueError("seam_policy.expand_under must be an integer in [0, 2]")
    contact_band = merged.get("contact_band_px")
    if isinstance(contact_band, bool) or not isinstance(contact_band, int) or not 1 <= contact_band <= 2:
        raise ValueError("seam_policy.contact_band_px must be an integer in [1, 2]")
    if not isinstance(merged.get("remove_internal_lines"), bool):
        raise ValueError("seam_policy.remove_internal_lines must be boolean")
    ownership = merged.get("ownership_rule")
    if ownership is not None and (not isinstance(ownership, str) or not ownership):
        raise ValueError("seam_policy.ownership_rule must be null or a non-empty string")
    if resolved_mode == "flatten" and policy is None:
        merged["cleanup"] = "off"
        merged["expand_under"] = 0
        merged["remove_internal_lines"] = False
    return merged


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    return mask if radius <= 0 else mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))


def _erode(mask: Image.Image, radius: int) -> Image.Image:
    return mask if radius <= 0 else mask.filter(ImageFilter.MinFilter(radius * 2 + 1))


def _mask_or(left: Image.Image, right: Image.Image) -> Image.Image:
    return ImageChops.lighter(left, right)


def _contact_mask(layers: list[tuple[str, str, Image.Image]], band: int) -> Image.Image:
    if not layers:
        return Image.new("L", (1, 1), 0)
    size = layers[0][2].size
    result = Image.new("L", size, 0)
    alphas = [image.getchannel("A") for _, _, image in layers]
    for index, left in enumerate(alphas):
        left_near = _dilate(left, band)
        left_edge = ImageChops.subtract(left_near, _erode(left, band))
        for right in alphas[index + 1 :]:
            right_near = _dilate(right, band)
            right_edge = ImageChops.subtract(right_near, _erode(right, band))
            near = ImageChops.multiply(left_near, right_near)
            edges = _mask_or(left_edge, right_edge)
            result = _mask_or(result, ImageChops.multiply(near, edges))
    return result


def _ownership_rank(semantic: str, rule: str | None) -> int:
    semantic = semantic.lower()
    if rule == "topwear_with_arms":
        return 20 if any(token in semantic for token in ("topwear", "sleeve", "cloth", "coat")) else 10
    if rule == "body_with_sleeves":
        return 20 if any(token in semantic for token in ("body", "skin")) else 10
    if rule == "coat_full":
        return 20 if any(token in semantic for token in ("coat", "cloth", "topwear")) else 10
    return 0


def repair_semantic_merge(
    composite: Image.Image,
    layers: list[tuple[str, str, Image.Image]],
    seam_policy: dict,
) -> tuple[Image.Image, dict]:
    """Repair contact seams and return ``(image, deterministic report)``."""
    policy = normalize_seam_policy(seam_policy, mode="semantic_merge")
    report = {
        "cleanup": policy["cleanup"],
        "contact_pixels": 0,
        "expanded_pixels": 0,
        "internal_lines_removed": False,
    }
    if policy["cleanup"] == "off" or len(layers) < 2:
        return composite, report

    contact = _contact_mask(layers, policy["contact_band_px"])
    report["contact_pixels"] = contact.convert("1").histogram()[255]
    repaired = composite.convert("RGBA")

    # Fill only transparent/partially transparent contact pixels.  Candidate
    # owners are applied from low to high semantic priority, so a named
    # surface profile deterministically wins where two expanded edges meet.
    candidates = sorted(
        layers,
        key=lambda item: _ownership_rank(item[1], policy.get("ownership_rule")),
    )
    for _, _, source in candidates:
        if policy["expand_under"] <= 0:
            break
        expanded = _dilate(source.getchannel("A"), policy["expand_under"])
        current_alpha = repaired.getchannel("A")
        available = ImageChops.invert(current_alpha)
        patch_alpha = ImageChops.multiply(contact, expanded)
        patch_alpha = ImageChops.multiply(patch_alpha, available)
        if patch_alpha.getbbox() is None:
            continue
        patch = source.copy()
        patch.putalpha(patch_alpha)
        repaired.alpha_composite(patch)
        report["expanded_pixels"] += patch_alpha.convert("1").histogram()[255]

    if policy["remove_internal_lines"]:
        filter_size = 5 if policy["cleanup"] == "aggressive" else 3
        smoothed = repaired.filter(ImageFilter.MedianFilter(filter_size))
        repaired = Image.composite(smoothed, repaired, contact)
        report["internal_lines_removed"] = report["contact_pixels"] > 0
    return repaired, report
