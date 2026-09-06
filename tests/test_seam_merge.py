from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake import apply_bake_plan
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.seam_repair import normalize_seam_policy, repair_semantic_merge

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait", size=(24, 20)))
    document, image_sources, _ = identity_assembly(bundle)
    document.rig_intent["deformation_scopes"]["neck__instance"] = "rigid"
    document.rig_intent["deformation_scopes"]["topwear__instance"] = "rigid"

    left = Image.new("RGBA", (24, 20), (0, 0, 0, 0))
    ImageDraw.Draw(left).rectangle((2, 4, 10, 16), fill=(240, 240, 240, 255))
    right = Image.new("RGBA", (24, 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(right)
    draw.rectangle((11, 4, 20, 16), fill=(240, 240, 240, 255))
    draw.line((11, 4, 11, 16), fill=(10, 10, 10, 255), width=1)
    left_path = tmp_path / "left.png"
    right_path = tmp_path / "right.png"
    left.save(left_path)
    right.save(right_path)
    image_sources["neck__instance"] = left_path
    image_sources["topwear__instance"] = right_path
    return document, image_sources, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (left_path, right_path)}


def _policy(**changes):
    return normalize_seam_policy(
        {"cleanup": "auto", "expand_under": 1, "remove_internal_lines": True, "contact_band_px": 1, **changes},
        result_semantic="topwear_with_arms",
        mode="semantic_merge",
    )


def test_named_profile_uses_boundary_aware_defaults():
    policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")
    assert policy["expand_under"] == 3
    assert policy["contact_band_px"] == 2
    assert policy["tone_blend_width"] == 1
    assert policy["alpha_blend_width"] == 1
    assert policy["ownership_rule"] == "topwear_with_arms"


def test_boundary_repair_reduces_internal_dark_line_and_fills_gap():
    size = (28, 20)
    handwear = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(handwear).rectangle((2, 4, 10, 16), fill=(220, 220, 220, 255))
    topwear = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(topwear)
    draw.rectangle((12, 4, 22, 16), fill=(220, 220, 220, 255))
    draw.line((12, 4, 12, 16), fill=(8, 8, 8, 255), width=1)

    composite = Image.new("RGBA", size, (0, 0, 0, 0))
    composite.alpha_composite(handwear)
    composite.alpha_composite(topwear)
    policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")
    repaired, report = repair_semantic_merge(
        composite,
        [("handwear", "handwear", handwear), ("topwear", "topwear", topwear)],
        policy,
    )

    before_dark = sum(1 for y in range(4, 17) if composite.getpixel((12, y))[0] < 32)
    after_dark = sum(1 for y in range(4, 17) if repaired.getpixel((12, y))[0] < 32)
    assert report["join_pixels"] > 0
    assert report["removed_edge_pixels"] > 0
    assert report["tone_blended_pixels"] > 0
    assert report["alpha_blended_pixels"] > 0
    assert after_dark < before_dark
    assert repaired.getpixel((11, 10))[3] > 0  # the one-pixel gap is under-filled
    assert repaired.getpixel((0, 0))[3] == composite.getpixel((0, 0))[3]


def test_boundary_repair_follows_reordered_stacking_not_just_named_rank():
    # ``topwear_with_arms`` always ranks topwear above handwear, but that
    # rank must never license overwriting a pixel that is actually visible
    # from the *other* source once the caller reorders the bake -- doing so
    # paints a mismatched-color seam back in exactly where the reorder was
    # meant to remove one (reported regression: reordering topwear/handwear
    # left a seam at their shared boundary in the After preview).
    size = (28, 20)
    handwear = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(handwear).rectangle((2, 4, 11, 16), fill=(60, 90, 160, 255))
    topwear = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(topwear).rectangle((11, 4, 22, 16), fill=(210, 120, 70, 255))
    policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")

    # Reordered: handwear is listed (and drawn) last, so it is the source
    # actually visible at the shared edge, even though the named rule would
    # otherwise treat topwear as the semantic "owner".
    composite = Image.new("RGBA", size, (0, 0, 0, 0))
    composite.alpha_composite(topwear)
    composite.alpha_composite(handwear)
    repaired, _ = repair_semantic_merge(
        composite,
        [("topwear", "topwear", topwear), ("handwear", "handwear", handwear)],
        policy,
    )

    def distance(pixel, color):
        return sum((a - b) ** 2 for a, b in zip(pixel, color))

    handwear_rgb = handwear.getpixel((5, 10))[:3]
    topwear_rgb = topwear.getpixel((18, 10))[:3]
    # x=11 is handwear's own visible pixel (it is drawn last / on top there);
    # a rank-only repair instead samples topwear's interior there, pulling
    # the pixel far closer to topwear's color than to handwear's own -- the
    # mismatched-color seam the reorder was meant to eliminate.
    boundary_pixel = repaired.getpixel((11, 10))[:3]
    assert distance(boundary_pixel, handwear_rgb) < distance(boundary_pixel, topwear_rgb), (
        f"boundary pixel {boundary_pixel} was pulled toward the hidden source's color "
        f"(handwear={handwear_rgb}, topwear={topwear_rgb})"
    )


def test_gap_fill_favors_the_nearer_source_not_a_fixed_rank():
    # A genuine transparent gap (not an overlap) between two sources -- e.g.
    # a shoulder strap (topwear) that doesn't quite touch a sleeve
    # (handwear) -- must be filled from whichever source is physically
    # nearer at each pixel. A rank-only fill lets the named rule's lower-
    # priority source (handwear) claim the *entire* gap regardless of
    # geometry, leaving a flat mismatched-color band on the topwear side
    # that a reorder can never fix (reported regression: seam persisted at
    # the shoulder strap even after reordering).
    size = (40, 30)
    handwear = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(handwear).rectangle((2, 4, 17, 26), fill=(235, 200, 175, 255))
    topwear = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(topwear).rectangle((20, 4, 36, 26), fill=(150, 110, 120, 255))
    composite = Image.new("RGBA", size, (0, 0, 0, 0))
    composite.alpha_composite(handwear)
    composite.alpha_composite(topwear)
    policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")

    repaired, _ = repair_semantic_merge(
        composite,
        [("handwear", "handwear", handwear), ("topwear", "topwear", topwear)],
        policy,
    )

    def distance(pixel, color):
        return sum((a - b) ** 2 for a, b in zip(pixel, color))

    handwear_rgb = handwear.getpixel((5, 10))[:3]
    topwear_rgb = topwear.getpixel((30, 10))[:3]
    # The gap runs from x=18 to x=19; the half nearer topwear must read
    # closer to topwear's own color, not be swallowed by handwear's rank.
    near_topwear = repaired.getpixel((19, 10))[:3]
    assert distance(near_topwear, topwear_rgb) < distance(near_topwear, handwear_rgb), (
        f"gap pixel nearer topwear ({near_topwear}) was filled with the farther "
        f"source's color instead (handwear={handwear_rgb}, topwear={topwear_rgb})"
    )


def test_front_source_edge_fringe_over_back_source_interior_is_cleaned():
    # A front garment's own anti-aliased silhouette edge -- which fades
    # through its drawn ink-outline color as alpha ramps to zero -- can sit
    # well inside a back source's broad opaque fill, far from the back
    # source's own edge (e.g. a strap's soft boundary resting deep inside an
    # arm, nowhere near the arm's silhouette). Alpha-compositing always
    # blends the front source's own RGB in at that partial weight, so the
    # ink tint bleeds into the arm's color underneath -- a dark line with no
    # source-vs-source "seam" at all, invisible to contact/join (the arm's
    # edge is nowhere close) and to ownership (only one source is even
    # partially present). Reported regression: reordering topwear in front
    # of handwear left a clean-looking strap but a persistent dark line
    # further down, exactly at topwear's own (now front) edge.
    size = (30, 20)
    back = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(back).rectangle((2, 2, 27, 17), fill=(240, 200, 180, 255))  # opaque arm

    front = Image.new("RGBA", size, (0, 0, 0, 0))
    front_px = front.load()
    solid = (150, 110, 120)
    ink = (40, 30, 35)
    for y in range(2, 17):
        for x in range(8, 20):
            front_px[x, y] = (*solid, 255)
        # a soft, ink-tinted anti-aliased ramp on the right edge of the
        # front shape, entirely inside the back shape's opaque interior --
        # not near the back shape's own boundary at x=27. Steep (over just
        # 2px), like a real renderer's anti-aliasing, not a wide gradient.
        for step, alpha in enumerate((220, 90, 0)):
            x = 20 + step
            weight = alpha / 255
            blended = tuple(round(s * weight + i * (1 - weight)) for s, i in zip(solid, ink))
            front_px[x, y] = (*blended, alpha)

    composite = Image.new("RGBA", size, (0, 0, 0, 0))
    composite.alpha_composite(back)
    composite.alpha_composite(front)
    policy = normalize_seam_policy(None, result_semantic="topwear_with_arms")

    repaired, report = repair_semantic_merge(
        composite,
        [("back", "handwear", back), ("front", "topwear", front)],
        policy,
    )

    skin_r = back.getpixel((25, 9))[0]  # the arm's own clean color, well clear of the ramp
    before_dip = composite.getpixel((21, 9))[0]
    after_dip = repaired.getpixel((21, 9))[0]
    assert report["fringe_pixels"] > 0
    assert before_dip < skin_r - 40  # the un-repaired ramp really does darken the arm
    assert after_dip > before_dip + 15  # repaired: substantially lighter, ink tint cleaned


def test_semantic_merge_repairs_contact_and_preserves_sources(tmp_path: Path):
    document, image_sources, hashes = _doc(tmp_path)
    derived_id, _ = apply_bake_plan(
        document,
        image_sources,
        ["neck__instance", "topwear__instance"],
        derived_id="merged",
        semantic="topwear_with_arms",
        work_dir=tmp_path / "work",
        mode="semantic_merge",
        seam_policy=_policy(),
    )

    provenance = document.assets["merged"].provenance
    assert provenance["operation"] == "semantic_merge"
    assert provenance["bake_mode"] == "semantic_merge"
    assert provenance["seam_policy"]["expand_under"] == 1
    assert provenance["seam_report"]["contact_pixels"] > 0
    assert provenance["seam_report"]["expanded_pixels"] > 0
    assert provenance["seam_report"]["internal_lines_removed"] is True
    assert derived_id in image_sources
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in hashes.items())


def test_semantic_merge_policy_changes_output_and_round_trips(tmp_path: Path):
    document_a, sources_a, _ = _doc(tmp_path / "a")
    document_b, sources_b, _ = _doc(tmp_path / "b")
    apply_bake_plan(
        document_a, sources_a, ["neck__instance", "topwear__instance"],
        derived_id="merged", semantic="topwear_with_arms", work_dir=tmp_path / "work-a",
        mode="semantic_merge", seam_policy=_policy(expand_under=0, remove_internal_lines=False),
    )
    apply_bake_plan(
        document_b, sources_b, ["neck__instance", "topwear__instance"],
        derived_id="merged", semantic="topwear_with_arms", work_dir=tmp_path / "work-b",
        mode="semantic_merge", seam_policy=_policy(expand_under=2, remove_internal_lines=True),
    )
    assert sources_a["merged__instance"].read_bytes() != sources_b["merged__instance"].read_bytes()
    restored = type(document_b).from_dict(document_b.to_dict())
    assert restored.assets["merged"].provenance["seam_policy"]["expand_under"] == 2
