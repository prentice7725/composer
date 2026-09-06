"""Boundary-aware seam repair for semantic merge bakes.

The repair stage is deterministic and local. It never writes to a source PNG;
it only returns a derived raster and a serializable report. AutoRig remains
responsible for mesh/deformer quality checks.
"""
from __future__ import annotations

import copy

from PIL import Image, ImageChops, ImageFilter

BAKE_MODES = ("flatten", "semantic_merge")
SEAM_CLEANUP_MODES = ("off", "auto", "aggressive")

_DEFAULT_SEAM_POLICY = {
    "cleanup": "auto",
    "expand_under": 3,
    "remove_internal_lines": True,
    "contact_band_px": 2,
    "tone_blend_width": 1,
    "alpha_blend_width": 1,
    "ownership_rule": None,
}

BAKE_PROFILES = {
    "topwear_with_arms": {
        "mode": "semantic_merge",
        "seam_policy": {**_DEFAULT_SEAM_POLICY, "ownership_rule": "topwear_with_arms"},
    },
    "body_with_sleeves": {
        "mode": "semantic_merge",
        "seam_policy": {**_DEFAULT_SEAM_POLICY, "ownership_rule": "body_with_sleeves"},
    },
    "coat_full": {
        "mode": "semantic_merge",
        "seam_policy": {**_DEFAULT_SEAM_POLICY, "ownership_rule": "coat_full"},
    },
}


def resolve_bake_mode(result_semantic: str, mode: str | None = None) -> str:
    """Resolve an explicit mode or a known semantic merge profile default."""
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
    """Return a validated, JSON-safe seam policy."""
    resolved_mode = resolve_bake_mode(result_semantic, mode)
    if policy is not None and not isinstance(policy, dict):
        raise ValueError("seam_policy must be an object")
    unknown = set(policy or {}) - set(_DEFAULT_SEAM_POLICY)
    if unknown:
        raise ValueError(f"unsupported seam_policy fields: {sorted(unknown)!r}")
    named = BAKE_PROFILES.get(result_semantic, {}).get("seam_policy", {})
    merged = {**_DEFAULT_SEAM_POLICY, **copy.deepcopy(named), **copy.deepcopy(policy or {})}
    if merged["cleanup"] not in SEAM_CLEANUP_MODES:
        raise ValueError(f"seam_policy.cleanup must be one of {SEAM_CLEANUP_MODES!r}")
    expand_under = merged["expand_under"]
    if isinstance(expand_under, bool) or not isinstance(expand_under, int) or not 0 <= expand_under <= 4:
        raise ValueError("seam_policy.expand_under must be an integer in [0, 4]")
    contact_band = merged["contact_band_px"]
    if isinstance(contact_band, bool) or not isinstance(contact_band, int) or not 1 <= contact_band <= 4:
        raise ValueError("seam_policy.contact_band_px must be an integer in [1, 4]")
    for name in ("tone_blend_width", "alpha_blend_width"):
        value = merged[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2:
            raise ValueError(f"seam_policy.{name} must be an integer in [0, 2]")
    if not isinstance(merged["remove_internal_lines"], bool):
        raise ValueError("seam_policy.remove_internal_lines must be boolean")
    ownership = merged["ownership_rule"]
    if ownership is not None and (not isinstance(ownership, str) or not ownership):
        raise ValueError("seam_policy.ownership_rule must be null or a non-empty string")
    if resolved_mode == "flatten" and policy is None:
        merged.update(
            cleanup="off",
            expand_under=0,
            remove_internal_lines=False,
            tone_blend_width=0,
            alpha_blend_width=0,
        )
    return merged


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    return mask if radius <= 0 else mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))


def _erode(mask: Image.Image, radius: int) -> Image.Image:
    return mask if radius <= 0 else mask.filter(ImageFilter.MinFilter(radius * 2 + 1))


def _mask_or(left: Image.Image, right: Image.Image) -> Image.Image:
    return ImageChops.lighter(left, right)


def _count(mask: Image.Image) -> int:
    return mask.convert("1").histogram()[255]


def _edge(mask: Image.Image) -> Image.Image:
    """Return a one-pixel boundary band around an alpha surface."""
    return ImageChops.subtract(_dilate(mask, 1), _erode(mask, 1))


def _contact_and_join_masks(
    layers: list[tuple[str, str, Image.Image]], band: int
) -> tuple[Image.Image, Image.Image, list[Image.Image]]:
    if not layers:
        blank = Image.new("L", (1, 1), 0)
        return blank, blank, []
    size = layers[0][2].size
    contact = Image.new("L", size, 0)
    join = Image.new("L", size, 0)
    per_source = [Image.new("L", size, 0) for _ in layers]
    alphas = [image.getchannel("A") for _, _, image in layers]
    edges = [_edge(alpha) for alpha in alphas]
    for index, left in enumerate(alphas):
        left_near = _dilate(left, band)
        for right_index in range(index + 1, len(alphas)):
            right = alphas[right_index]
            right_near = _dilate(right, band)
            near = ImageChops.multiply(left_near, right_near)
            contact = _mask_or(contact, near)
            left_join = ImageChops.multiply(edges[index], right_near)
            right_join = ImageChops.multiply(edges[right_index], left_near)
            per_source[index] = _mask_or(per_source[index], left_join)
            per_source[right_index] = _mask_or(per_source[right_index], right_join)
            join = _mask_or(join, _mask_or(left_join, right_join))
    return contact, join, per_source


def _clean_interior_fill(source: Image.Image, erode_radius: int = 3, bleed_radius: int = 8) -> Image.Image:
    """An edge-bled sample of a source's own solid interior, safe to paint
    over its own ink outline. The alpha ramp of a drawn silhouette's
    anti-aliased edge is itself graded (0-255); eroding/bleeding those raw
    values only partially shrinks the ramp, so a fill built from it still
    carries a partial tint of the ink outline instead of replacing it.
    Binarizing first (then eroding well past the ramp's width) gives a
    properly ink-free core to bleed back out from.
    """
    binary_alpha = source.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    interior = _erode(binary_alpha, erode_radius)
    if interior.getbbox() is None:
        interior = binary_alpha
    interior_source = source.copy()
    interior_source.putalpha(interior)
    return _edge_bleed(interior_source, bleed_radius)


def _defringe_composite(
    layers: list[tuple[str, str, Image.Image]], composite: Image.Image
) -> tuple[Image.Image, "Image.Image"]:
    """Clean a source's own edge fringe wherever it was alpha-composited
    over ANOTHER source's opaque fill, far from that other source's own
    edge (e.g. a front garment's soft, anti-aliased silhouette resting deep
    inside an arm's flat interior, nowhere near the arm's own boundary).
    That case is invisible to ownership -- the front source's own drawn ink
    outline fades through partial alpha there, and alpha-compositing always
    blends *its own* RGB in at that weight regardless of who "owns" the
    pixel, tinting whatever sits behind it. It is also outside what the
    near-band contact/join above can flag, since the other source's edge is
    nowhere close. Ownership never applies here: whichever source is drawn
    later already deterministically wins by definition of compositing; only
    its own ink tint needs replacing before it bleeds into the other's
    color. Fixed by rebuilding just those pixels from a version of every
    source with its own edge pre-cleaned (RGB replaced by an interior
    sample of itself), recomposited in the same order.
    """
    if len(layers) < 2:
        return composite, Image.new("L", composite.size, 0)
    alphas = [image.getchannel("A") for _, _, image in layers]
    edges = [_edge(alpha) for alpha in alphas]
    fringe_union = Image.new("L", composite.size, 0)
    cleaned_layers = []
    for index, (_, _, source) in enumerate(layers):
        others = None
        for other_index, alpha in enumerate(alphas):
            if other_index == index:
                continue
            others = alpha if others is None else _mask_or(others, alpha)
        mask = ImageChops.multiply(edges[index], others)
        fringe_union = _mask_or(fringe_union, mask)
        if mask.getbbox() is None:
            cleaned_layers.append(source)
            continue
        fill = _clean_interior_fill(source)
        cleaned_layers.append(_replace_rgb(source, fill, mask))
    if fringe_union.getbbox() is None:
        return composite, fringe_union
    cleaned_composite = Image.new("RGBA", composite.size, (0, 0, 0, 0))
    for cleaned in cleaned_layers:
        cleaned_composite.alpha_composite(cleaned)
    return Image.composite(cleaned_composite, composite, fringe_union), fringe_union


def _shift(image: Image.Image, dx: int, dy: int) -> Image.Image:
    """Shift without PIL's wrapping ``ImageChops.offset`` behavior."""
    width, height = image.size
    result = Image.new(image.mode, image.size, 0)
    src_left = max(0, -dx)
    src_top = max(0, -dy)
    src_right = min(width, width - dx) if dx >= 0 else width
    src_bottom = min(height, height - dy) if dy >= 0 else height
    if src_right <= src_left or src_bottom <= src_top:
        return result
    crop = image.crop((src_left, src_top, src_right, src_bottom))
    result.paste(crop, (src_left + dx, src_top + dy))
    return result


def _edge_bleed(source: Image.Image, radius: int) -> Image.Image:
    """Extend edge RGB together with alpha, never sampling transparent RGB."""
    result = source.convert("RGBA")
    current_alpha = result.getchannel("A")
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))
    for _ in range(max(0, radius)):
        next_alpha = _dilate(current_alpha, 1)
        newly = ImageChops.subtract(next_alpha, current_alpha)
        for dx, dy in directions:
            shifted = _shift(result, dx, dy)
            candidate = ImageChops.multiply(newly, shifted.getchannel("A"))
            result = Image.composite(shifted, result, candidate)
            newly = ImageChops.subtract(newly, candidate)
        result.putalpha(next_alpha)
        current_alpha = next_alpha
    return result


def _shared_edge_bleed(
    layers: list[tuple[str, str, Image.Image]], radius: int, priority
) -> list[Image.Image]:
    """Grow every source's own edge outward together, one pixel-step at a
    time, so a genuine transparent gap between two sources is filled from
    whichever source's silhouette is physically nearer -- never from a
    fixed rank alone. A pixel is permanently claimed the round some source
    first reaches it; ``priority`` only breaks an exact tie (both sources
    reach it in the same round). This keeps a reordered bake from having a
    gap-fill seam that stays put no matter which source is put on top.
    """
    results = [source.convert("RGBA").copy() for _, _, source in layers]
    if not results:
        return results
    claimed = results[0].getchannel("A")
    for other in results[1:]:
        claimed = _mask_or(claimed, other.getchannel("A"))
    order = sorted(range(len(results)), key=priority, reverse=True)
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))
    for _ in range(max(0, radius)):
        for index in order:
            current_alpha = results[index].getchannel("A")
            gained = ImageChops.subtract(_dilate(current_alpha, 1), current_alpha)
            gained = ImageChops.subtract(gained, claimed)
            if gained.getbbox() is None:
                continue
            claimed = _mask_or(claimed, gained)
            grown = results[index]
            remaining = gained
            for dx, dy in directions:
                shifted = _shift(grown, dx, dy)
                candidate = ImageChops.multiply(remaining, shifted.getchannel("A"))
                grown = Image.composite(shifted, grown, candidate)
                remaining = ImageChops.subtract(remaining, candidate)
            grown.putalpha(_mask_or(current_alpha, gained))
            results[index] = grown
    return results


def _ownership_rank(semantic: str, rule: str | None) -> int:
    semantic = semantic.lower()
    if rule == "topwear_with_arms":
        return 20 if any(token in semantic for token in ("topwear", "sleeve", "cloth", "coat")) else 10
    if rule == "body_with_sleeves":
        return 20 if any(token in semantic for token in ("body", "skin")) else 10
    if rule == "coat_full":
        return 20 if any(token in semantic for token in ("coat", "cloth", "topwear")) else 10
    return 0


def _resolve_owners(
    layers: list[tuple[str, str, Image.Image]], contact: Image.Image, rule: str | None
) -> list[Image.Image]:
    """Assign contact pixels to a source, honoring rule then draw order."""
    owners = [Image.new("L", contact.size, 0) for _ in layers]
    assigned = Image.new("L", contact.size, 0)
    ordered = sorted(
        range(len(layers)),
        key=lambda index: (_ownership_rank(layers[index][1], rule), index),
        reverse=True,
    )
    for index in ordered:
        candidate = ImageChops.multiply(contact, layers[index][2].getchannel("A"))
        available = ImageChops.invert(assigned)
        owners[index] = ImageChops.multiply(candidate, available)
        assigned = _mask_or(assigned, owners[index])
    return owners


def _replace_rgb(base: Image.Image, fill: Image.Image, mask: Image.Image) -> Image.Image:
    """Replace RGB in a mask while preserving the repaired alpha."""
    fill = fill.convert("RGBA").copy()
    fill.putalpha(base.getchannel("A"))
    return Image.composite(fill, base, mask)


def repair_semantic_merge(
    composite: Image.Image,
    layers: list[tuple[str, str, Image.Image]],
    seam_policy: dict | None,
) -> tuple[Image.Image, dict]:
    """Repair shared boundaries and return ``(image, deterministic report)``."""
    policy = normalize_seam_policy(seam_policy, mode="semantic_merge")
    report = {
        "mode": "semantic_merge",
        "cleanup": policy["cleanup"],
        "contact_pixels": 0,
        "join_pixels": 0,
        "ownership_pixels": 0,
        "expanded_pixels": 0,
        "internal_lines_removed": False,
        "removed_edge_pixels": 0,
        "tone_blended_pixels": 0,
        "alpha_blended_pixels": 0,
        "fringe_pixels": 0,
    }
    repaired = composite.convert("RGBA")
    if policy["cleanup"] == "off" or len(layers) < 2:
        return repaired, report

    repaired, fringe_mask = _defringe_composite(layers, repaired)
    report["fringe_pixels"] = _count(fringe_mask)

    contact, join, per_source_join = _contact_and_join_masks(layers, policy["contact_band_px"])
    report["contact_pixels"] = _count(contact)
    report["join_pixels"] = _count(join)
    owners = _resolve_owners(layers, contact, policy.get("ownership_rule"))
    if owners:
        owner_union = owners[0]
        for owner in owners[1:]:
            owner_union = _mask_or(owner_union, owner)
        report["ownership_pixels"] = _count(owner_union)

    # The named ownership_rule says nothing about which source is actually
    # visible where both already have opaque pixels. Overwriting RGB there
    # must instead follow the real stacking order (whichever source is
    # later in ``layers`` paints over the other), or a reordered bake would
    # replace a now-visible source's edge with a hidden source's color and
    # paint a mismatched seam back in.
    visible_owners = _resolve_owners(layers, contact, None)

    # Fill only contact holes, using RGB sampled from real source edges. This
    # prevents transparent fringe RGB from becoming a black matte halo. Both
    # sources grow into a shared gap together (nearest silhouette wins, the
    # named rule only breaks an exact-distance tie) -- a fixed rank alone
    # would let one source's texture claim the whole gap regardless of
    # which one the caller's reordering put closer to it.
    if policy["expand_under"] > 0:
        bled = _shared_edge_bleed(
            layers,
            policy["expand_under"],
            lambda index: _ownership_rank(layers[index][1], policy.get("ownership_rule")),
        )
        for index in range(len(layers)):
            available = ImageChops.invert(repaired.getchannel("A"))
            patch_alpha = ImageChops.multiply(contact, bled[index].getchannel("A"))
            patch_alpha = ImageChops.multiply(patch_alpha, available)
            if patch_alpha.getbbox() is None:
                continue
            patch = bled[index].copy()
            patch.putalpha(patch_alpha)
            repaired.alpha_composite(patch)
            report["expanded_pixels"] += _count(patch_alpha)

    # Replace only a source's shared join edge with an interior sample. This
    # suppresses the internal line without blurring an external silhouette.
    if policy["remove_internal_lines"] and report["join_pixels"]:
        radius = 2 if policy["cleanup"] == "aggressive" else 1
        for index, (_, _, source) in enumerate(layers):
            mask = ImageChops.multiply(per_source_join[index], visible_owners[index])
            if radius > 1:
                mask = ImageChops.multiply(mask, _dilate(contact, radius))
            # Only where this source is itself already substantially opaque:
            # replacing with its own solid interior color assumes it already
            # dominates the pixel (the classic case -- a fully opaque drawn
            # line right at a hard boundary between two opaque fills). On a
            # genuinely fractional alpha ramp (this source's own soft,
            # anti-aliased edge), that assumption is wrong -- _defringe_
            # composite above already produced the correct alpha-weighted
            # blend there, and overwriting toward this source's full color
            # regardless of its actual (low) coverage would undo it.
            own_alpha_high = source.getchannel("A").point(lambda v: 255 if v >= 200 else 0)
            mask = ImageChops.multiply(mask, own_alpha_high)
            fill = _clean_interior_fill(source)
            repaired = _replace_rgb(repaired, fill, mask)
            report["removed_edge_pixels"] += _count(mask)
        report["internal_lines_removed"] = report["removed_edge_pixels"] > 0

    # Narrow-band tone/alpha blend. It is masked to the shared join edge and
    # is never a whole-image smoothing pass.
    blend_band = ImageChops.multiply(_dilate(join, policy["tone_blend_width"]), contact)
    if policy["tone_blend_width"] > 0 and blend_band.getbbox() is not None:
        softened = repaired.filter(ImageFilter.BoxBlur(policy["tone_blend_width"]))
        original = repaired
        repaired = Image.composite(Image.blend(original, softened, 0.35), original, blend_band)
        report["tone_blended_pixels"] = _count(blend_band)
    if policy["alpha_blend_width"] > 0 and blend_band.getbbox() is not None:
        alpha = repaired.getchannel("A")
        softened_alpha = alpha.filter(ImageFilter.BoxBlur(policy["alpha_blend_width"]))
        repaired.putalpha(Image.composite(softened_alpha, alpha, blend_band))
        report["alpha_blended_pixels"] = _count(blend_band)
    return repaired, report
