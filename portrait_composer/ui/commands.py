"""GUI command layer (directive #19).

Every UI gesture that mutates the document funnels through one of these
functions, and each one performs exactly one authoring transaction via the
existing public core API (assembly.apply_recipe / set_draw_order,
links.apply_delta) -- never touches AssemblyDocument fields directly.
MainWindow.run_command() is the only caller; Qt widget code never imports
core mutation primitives itself, only this module.
"""
from __future__ import annotations

from .. import links as _links
from .. import rig_intent as _rig_intent
from .. import secondary_regions as _secondary_regions
from .. import slots as _slots
from .. import variants as _variants
from ..assembly import apply_recipe, harvest_instance, set_draw_order
from ..bake_plan import analyze_bake_plan, apply_bake_plan as apply_logical_bake_plan, create_bake_plan
from ..donors import DonorImportResult, import_donor
from ..expressions import apply_expression_preset, create_expression_preset, update_expression_preset
from ..profiles import apply_candidate as _apply_bake_candidate
from ..visual_ops import add_visual_op, reset_visual_ops, update_visual_op
from ..mask_ops import edit_mask_stroke
from ..transform_ops import (
    align_instance,
    fit_instance,
    flip_transform,
    nudge_transform,
    reset_transform,
    set_uniform_scale,
)


def _instance(document, instance_id: str):
    instance = document.instances.get(instance_id)
    if instance is None:
        raise KeyError(f"no such instance: {instance_id!r}")
    return instance


def set_instance_transform(document, image_sources, instance_id: str, **fields) -> None:
    """Commits one transaction for a Transform field change.

    x/y/rotation route through the instance's TransformLink group when it
    has one, so linked members keep moving together -- the same behaviour
    every other Composer TransformLink caller gets from links.apply_delta.
    scale_x/scale_y are always per-instance; links have no scale semantics.
    """
    instance = _instance(document, instance_id)
    link_id = instance.transform_link
    linked = {k: v for k, v in fields.items() if k in ("x", "y", "rotation")}
    direct = {k: v for k, v in fields.items() if k not in linked}

    if link_id and linked:
        with document.transaction():
            dx = linked.get("x", instance.transform.x) - instance.transform.x
            dy = linked.get("y", instance.transform.y) - instance.transform.y
            drotation = linked.get("rotation", instance.transform.rotation) - instance.transform.rotation
            _links.apply_delta(document, link_id, dx=dx, dy=dy, drotation=drotation)
            for name, value in direct.items():
                setattr(instance.transform, name, value)
    else:
        recipe = {"operations": [{"op": "set_transform", "instance": instance_id, "transform": fields}]}
        apply_recipe(document, recipe, image_sources)


def set_instance_visible(document, image_sources, instance_id: str, visible: bool) -> None:
    recipe = {"operations": [{"op": "set_visible", "instance": instance_id, "value": bool(visible)}]}
    apply_recipe(document, recipe, image_sources)


def set_instance_opacity(document, image_sources, instance_id: str, opacity: float) -> None:
    recipe = {"operations": [{"op": "set_opacity", "instance": instance_id, "value": float(opacity)}]}
    apply_recipe(document, recipe, image_sources)


def add_instance_mask(document, image_sources, instance_id: str, *, op_id: str, path: str) -> None:
    add_visual_op(document, instance_id, {"id": op_id, "type": "mask", "params": {"path": path}})


def add_instance_quad_warp(document, image_sources, instance_id: str, *, op_id: str, quad: list[float]) -> None:
    add_visual_op(document, instance_id, {"id": op_id, "type": "quad_warp", "params": {"quad": list(quad)}})


def add_instance_color(document, image_sources, instance_id: str, *, op_id: str, **params) -> None:
    add_visual_op(document, instance_id, {"id": op_id, "type": "color", "params": dict(params)})


def update_instance_visual_op(document, image_sources, instance_id: str, *, op_id: str, params: dict) -> None:
    update_visual_op(document, instance_id, op_id, params=dict(params))


def update_instance_mask(document, image_sources, instance_id: str, *, op_id: str, **params) -> None:
    update_visual_op(document, instance_id, op_id, params=params)


def reset_instance_masks(document, image_sources, instance_id: str) -> None:
    reset_visual_ops(document, instance_id)


def paint_instance_mask(
    document,
    image_sources,
    instance_id: str,
    *,
    op_id: str,
    points: list[tuple[float, float]],
    radius: float,
    mode: str,
    work_dir,
    base_dir=None,
) -> None:
    edit_mask_stroke(
        document,
        instance_id,
        op_id,
        points=points,
        radius=radius,
        mode=mode,
        work_dir=work_dir,
        base_dir=base_dir,
    )


def reset_instance_transform(document, image_sources, instance_id: str) -> None:
    reset_transform(document, instance_id)


def set_instance_uniform_scale(document, image_sources, instance_id: str, scale: float) -> None:
    set_uniform_scale(document, instance_id, scale)


def flip_instance(document, image_sources, instance_id: str, *, horizontal: bool = False, vertical: bool = False) -> None:
    flip_transform(document, instance_id, horizontal=horizontal, vertical=vertical)


def nudge_instance(document, image_sources, instance_id: str, *, dx: float = 0.0, dy: float = 0.0) -> None:
    nudge_transform(document, instance_id, dx=dx, dy=dy)


def fit_instance_to_target(document, image_sources, instance_id: str, *, mode: str, image_size: tuple[int, int], target=None) -> None:
    fit_instance(document, instance_id, mode=mode, image_size=image_size, target=target)


def align_instance_to_target(document, image_sources, instance_id: str, *, anchor: str, image_size: tuple[int, int], target=None) -> None:
    align_instance(document, instance_id, anchor=anchor, image_size=image_size, target=target)


def set_instance_slot(document, image_sources, instance_id: str, slot: str) -> None:
    """Commit an Inspector slot edit through the public C1 slot API."""
    with document.transaction():
        _slots.set_slot(document, instance_id, str(slot))


def set_instance_plane(document, image_sources, instance_id: str, plane: str | None) -> None:
    """Commit an Inspector plane edit through the public C1 plane API."""
    with document.transaction():
        _slots.set_plane(document, instance_id, plane)


def harvest_semantic(document, image_sources, bundle_pool: dict, target_tag: str, run_label: str) -> None:
    """Commits one Harvest Workbench candidate pick (C5-C, directive #8.2)."""
    harvest_instance(document, image_sources, bundle_pool, target_tag, run_label)


def set_variant_active(document, image_sources, vs_id: str, member_id: str) -> None:
    """Commits one VariantSet exclusive switch (C5-D, directive #9.1)."""
    with document.transaction():
        _variants.set_active(document, vs_id, member_id)


def add_variant_member(document, image_sources, vs_id: str, instance_id: str, *, default: bool = False) -> None:
    """Drag-membership add (directive #9.2). Creates ``vs_id`` as a new
    exclusive VariantSet if it doesn't exist yet, otherwise appends."""
    with document.transaction():
        _variants.create_or_add_member(document, vs_id, instance_id, default=default)


def remove_variant_member(document, image_sources, vs_id: str, instance_id: str) -> None:
    """Drag-out / context-menu membership remove (directive #9.2)."""
    with document.transaction():
        _variants.remove_member(document, vs_id, instance_id)


def save_and_apply_expression(document, image_sources, preset_id: str, variants: dict) -> None:
    """One Expression Preset "Apply" (directive #9.3): saves the current
    per-VariantSet picks into the named preset, then applies them as the
    live active selection -- one transaction, one undo step. Creating vs.
    updating the preset is decided by whether ``preset_id`` already exists.
    """
    with document.transaction():
        if preset_id in document.expressions:
            update_expression_preset(document, preset_id, variants)
        else:
            create_expression_preset(document, preset_id, variants)
        apply_expression_preset(document, preset_id)


def save_expression(document, image_sources, preset_id: str, variants: dict) -> None:
    """Saves the preset's per-VariantSet picks without touching the live
    active selection (directive #9.3's "Preview는 transient" -- the picks
    the Preview button rendered only become real once this or Apply runs)."""
    with document.transaction():
        if preset_id in document.expressions:
            update_expression_preset(document, preset_id, variants)
        else:
            create_expression_preset(document, preset_id, variants)


def import_donor_asset(
    document,
    image_sources,
    donor_path,
    *,
    semantic: str,
    donor_size: tuple,
    alignment: dict,
    target_roi: dict | None,
    target_size: tuple | None,
    target_rotation: float,
    allow_drift: bool,
    variant_set_id: str | None = None,
    import_mode: str | None = None,
    target_instance_id: str | None = None,
    target_anchor: tuple[float, float] | None = None,
) -> DonorImportResult:
    """Commits one Donor Align import (C5-E, directive #10.4).

    A single call to the existing donors.import_donor: it already wraps
    asset+instance+variant-membership+provenance in one transaction, so one
    Apply is one undo step and undo removes the donor cleanly. Raises
    DonorDriftError (uncaught here -- MainWindow.run_command reports it
    non-modally) when drift fails and allow_drift is False, which is the
    "hard drift prevents commit by default" gate. ``roi`` is always the
    donor's whole image -- this workspace doesn't offer a separate
    donor-side crop tool, only alignment (move/scale/rotate).
    """
    donor_width, donor_height = donor_size
    roi = {"x": 0, "y": 0, "width": donor_width, "height": donor_height}
    return import_donor(
        document,
        donor_path,
        semantic=semantic,
        alignment=alignment,
        roi=roi,
        target_roi=target_roi,
        target_size=target_size,
        target_rotation=target_rotation,
        allow_drift=allow_drift,
        variant_set_id=variant_set_id,
        import_mode=import_mode,
        target_instance_id=target_instance_id,
        target_anchor=target_anchor,
        image_sources=image_sources,
    )


def set_deformation_scope(document, image_sources, target: str, scope: str) -> None:
    """Commits one Motion Permission change (C5-F, directive #11.1).
    rig_intent.set_deformation_scope already self-transacts."""
    _rig_intent.set_deformation_scope(document, target, scope)


def set_rig_attachment(document, image_sources, attachment_id: str, *, child: str, target: str, mode: str) -> None:
    """Create-or-replace one attachment intent (directive #11.2)."""
    _rig_intent.set_attachment(document, attachment_id, child=child, target=target, mode=mode)


def remove_rig_attachment(document, image_sources, attachment_id: str) -> None:
    _rig_intent.remove_attachment(document, attachment_id)


def add_secondary_region(
    document,
    image_sources,
    region_id: str,
    *,
    target: str,
    response_profile: str = "soft",
    author_strength: float = 0.9,
    geometry: dict | None = None,
) -> dict:
    """Adds the region with the deterministic default two_lobe geometry
    (directive #12); its shape is then edited directly on Canvas."""
    return _secondary_regions.add_region(
        document,
        region_id,
        target=target,
        response_profile=response_profile,
        author_strength=author_strength,
        geometry=geometry,
    )


def remove_secondary_region(document, image_sources, region_id: str) -> None:
    _secondary_regions.remove_region(document, region_id)


def update_secondary_region(document, image_sources, region_id: str, **changes) -> dict:
    """response_profile / author_strength / locks edits (directive #12.2)."""
    return _secondary_regions.update_region(document, region_id, **changes)


def set_region_geometry(document, image_sources, region_id: str, geometry: dict) -> None:
    """Commits one two_lobe canvas drag as exactly one transaction
    (directive #12.1's "one region drag = one undo step")."""
    _secondary_regions.set_geometry(document, region_id, geometry)


def bake_candidate(
    document,
    image_sources,
    candidate,
    *,
    derived_id: str,
    semantic: str,
    work_dir,
    profile: str | None = None,
    ordered_instance_ids: list | None = None,
    transform_overrides: dict | None = None,
    mode: str | None = None,
    seam_policy: dict | None = None,
):
    """Commits one Bake Apply (C5-G, directive #13.4).

    profiles.apply_candidate -> bake.apply_bake_plan already wraps
    asset+instance+visibility+draw_order+provenance in one transaction, so
    Apply is one undo step and undo restores every source instance exactly
    (bake only hides them, never deletes -- see bake.py's module docstring).
    Raises BakeBlockedError if the candidate's own dry-run verdict is
    BLOCK; the UI disables Apply for that case, but this is the actual
    enforcement, not the button state.
    """
    return _apply_bake_candidate(
        document,
        image_sources,
        candidate,
        derived_id=derived_id,
        semantic=semantic,
        work_dir=work_dir,
        profile=profile,
        ordered_instance_ids=ordered_instance_ids,
        transform_overrides=transform_overrides,
        mode=mode,
        seam_policy=seam_policy,
    )


def create_logical_bake_plan(
    document,
    image_sources,
    plan_id: str,
    *,
    sources: list[str],
    result_semantic: str,
    result_slot: str,
    mode: str | None = None,
    seam_policy: dict | None = None,
) -> dict:
    return create_bake_plan(
        document,
        plan_id,
        sources=sources,
        result_semantic=result_semantic,
        result_slot=result_slot,
        mode=mode,
        seam_policy=seam_policy,
    )


def analyze_logical_bake_plan(document, image_sources, plan_id: str):
    return analyze_bake_plan(document, plan_id)


def apply_logical_plan(document, image_sources, plan_id: str, *, work_dir, profile: str | None = None):
    return apply_logical_bake_plan(document, image_sources, plan_id, work_dir=work_dir, profile=profile)


def reorder_draw_order(document, new_order: list) -> None:
    set_draw_order(document, list(new_order))


def nudge_draw_order(document, instance_id: str, *, direction: int = 0, to_extreme: int = 0) -> bool:
    """direction: -1 send backward one step, +1 bring forward one step.
    to_extreme: -1 send to back, +1 bring to front. Returns False (nothing
    committed) when the instance isn't in draw_order or the move is a
    no-op, so callers never record a spurious identity undo step.
    """
    order = list(document.composition.get("draw_order", []))
    if instance_id not in order:
        return False
    index = order.index(instance_id)
    order.pop(index)
    if to_extreme > 0:
        order.append(instance_id)
    elif to_extreme < 0:
        order.insert(0, instance_id)
    elif direction > 0:
        order.insert(min(index + 1, len(order)), instance_id)
    elif direction < 0:
        order.insert(max(index - 1, 0), instance_id)
    else:
        return False
    if order == document.composition.get("draw_order", []):
        return False
    reorder_draw_order(document, order)
    return True
