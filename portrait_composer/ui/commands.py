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
from ..assembly import apply_recipe, harvest_instance, instance_id_for, set_draw_order
from ..bake_plan import analyze_bake_plan, apply_bake_plan as apply_logical_bake_plan, create_bake_plan
from ..donors import DonorImportResult, import_donor
from ..donor_slots import clear_donor_slot, set_donor_slot
from ..expressions import apply_expression_preset, create_expression_preset, update_expression_preset
from ..profiles import apply_candidate as _apply_bake_candidate
from ..visual_ops import add_visual_op, reset_visual_ops, update_visual_op
from ..color_match import create_color_match_op
from ..remap import apply_remap_resolution as _apply_remap_resolution
from ..external_edit import apply_ora_reimport as _apply_ora_reimport
from ..mask_ops import edit_mask_stroke
from ..derived import adopt_derived_split as _adopt_derived_split, revert_derived_split as _revert_derived_split
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


def _require_unlocked(document, instance_ids) -> None:
    """Reject an entire command when any target layer is locked."""
    locked = []
    for instance_id in dict.fromkeys(str(value) for value in instance_ids if value):
        instance = document.instances.get(instance_id)
        metadata = (document.instance_authoring or {}).get(instance_id, {})
        if instance is not None and metadata.get("locked"):
            display_name = metadata.get("display_name") or instance_id
            locked.append(display_name if display_name == instance_id else f"{display_name} [{instance_id}]")
    if locked:
        raise ValueError("Locked layer(s): " + ", ".join(locked) + ". Unlock them before editing.")


def set_instance_authoring(
    document, image_sources, instance_id: str, *, display_name: str | None = None, locked: bool | None = None
) -> bool:
    """Set Composer-only user display name or lock state in one history step."""
    _instance(document, instance_id)
    current = dict((document.instance_authoring or {}).get(instance_id, {}))
    updated = dict(current)
    if display_name is not None:
        if current.get("locked") and locked is not False:
            _require_unlocked(document, [instance_id])
        value = str(display_name).strip()
        # Empty edits restore the previous name (or the implicit ID fallback).
        if value:
            updated["display_name"] = value
    if locked is not None:
        updated["locked"] = bool(locked)
    updated = {key: value for key, value in updated.items() if key in {"display_name", "locked"}}
    if updated == current:
        return False
    with document.transaction():
        if updated:
            document.instance_authoring[instance_id] = updated
        else:
            document.instance_authoring.pop(instance_id, None)
    return True


def apply_remap_resolution(document, image_sources, new_bundle, report, manual_choices=None) -> None:
    manual_choices = manual_choices or {}
    asset_ids = {
        entry.asset_id
        for entry in report.entries
        if entry.status in {"EXACT_MATCH", "SEMANTIC_MATCH"}
        or (entry.status in {"AMBIGUOUS", "ORPHANED"} and entry.asset_id in manual_choices)
    }
    targets = [
        instance_id
        for instance_id, instance in document.instances.items()
        if instance.asset_ref in asset_ids
    ]
    _require_unlocked(document, targets)
    _apply_remap_resolution(document, new_bundle, report, manual_choices)


def apply_ora_reimport(document, image_sources, ora_path, sidecar_path, work_dir, *, instance_ids=None):
    targets = list(instance_ids) if instance_ids is not None else list(document.instances)
    _require_unlocked(document, targets)
    return _apply_ora_reimport(
        document, image_sources, ora_path, sidecar_path, work_dir, instance_ids=instance_ids
    )


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

    affected_ids = [instance_id]
    if link_id and linked:
        affected_ids.extend((document.links.get(link_id) or {}).get("members", []))
    _require_unlocked(document, affected_ids)

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
    _require_unlocked(document, [instance_id])
    recipe = {"operations": [{"op": "set_visible", "instance": instance_id, "value": bool(visible)}]}
    apply_recipe(document, recipe, image_sources)


def set_instances_visible(document, image_sources, instance_ids, visible: bool) -> None:
    ids = list(dict.fromkeys(str(instance_id) for instance_id in instance_ids))
    if not ids:
        return
    _require_unlocked(document, ids)
    ids = [instance_id for instance_id in ids if document.instances[instance_id].visible != bool(visible)]
    if not ids:
        return
    recipe = {
        "operations": [
            {"op": "set_visible", "instance": instance_id, "value": bool(visible)}
            for instance_id in ids
        ]
    }
    apply_recipe(document, recipe, image_sources)


def set_instance_opacity(document, image_sources, instance_id: str, opacity: float) -> None:
    _require_unlocked(document, [instance_id])
    recipe = {"operations": [{"op": "set_opacity", "instance": instance_id, "value": float(opacity)}]}
    apply_recipe(document, recipe, image_sources)


def set_instances_opacity(document, image_sources, instance_ids, opacity: float) -> None:
    ids = list(dict.fromkeys(str(instance_id) for instance_id in instance_ids))
    if not ids:
        return
    _require_unlocked(document, ids)
    ids = [
        instance_id for instance_id in ids
        if abs(document.instances[instance_id].opacity - float(opacity)) > 1e-9
    ]
    if not ids:
        return
    recipe = {
        "operations": [
            {"op": "set_opacity", "instance": instance_id, "value": float(opacity)}
            for instance_id in ids
        ]
    }
    apply_recipe(document, recipe, image_sources)


def selection_move_targets(document, instance_ids) -> list[str]:
    """Return selected instances and every linked member, in stable order."""
    selected = list(dict.fromkeys(str(value) for value in instance_ids if value))
    targets = list(selected)
    seen_links = set()
    for instance_id in selected:
        instance = document.instances.get(instance_id)
        link_id = instance.transform_link if instance is not None else None
        if not link_id or link_id in seen_links:
            continue
        seen_links.add(link_id)
        targets.extend((document.links.get(link_id) or {}).get("members", []))
    return list(dict.fromkeys(value for value in targets if value in document.instances))


def move_instances_relative(document, image_sources, instance_ids, *, dx: float = 0.0, dy: float = 0.0) -> None:
    """Move a multi-selection and its linked members once in one history step."""
    selected = list(dict.fromkeys(str(value) for value in instance_ids if value))
    if not selected:
        return
    missing = [instance_id for instance_id in selected if instance_id not in document.instances]
    if missing:
        raise KeyError(f"no such layer instance(s): {missing!r}")
    targets = selection_move_targets(document, selected)
    _require_unlocked(document, targets)
    dx, dy = float(dx), float(dy)
    if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
        return
    linked_ids = {
        document.instances[instance_id].transform_link
        for instance_id in selected
        if document.instances[instance_id].transform_link
    }
    linked_members = {
        member
        for link_id in linked_ids
        for member in (document.links.get(link_id) or {}).get("members", [])
    }
    with document.transaction():
        for link_id in linked_ids:
            _links.apply_delta(document, link_id, dx=dx, dy=dy)
        for instance_id in selected:
            if instance_id not in linked_members:
                transform = document.instances[instance_id].transform
                transform.x += dx
                transform.y += dy


def add_instance_mask(document, image_sources, instance_id: str, *, op_id: str, path: str) -> None:
    _require_unlocked(document, [instance_id])
    add_visual_op(document, instance_id, {"id": op_id, "type": "mask", "params": {"path": path}})


def add_instance_quad_warp(document, image_sources, instance_id: str, *, op_id: str, quad: list[float]) -> None:
    _require_unlocked(document, [instance_id])
    add_visual_op(document, instance_id, {"id": op_id, "type": "quad_warp", "params": {"quad": list(quad)}})


def add_instance_color(document, image_sources, instance_id: str, *, op_id: str, **params) -> None:
    _require_unlocked(document, [instance_id])
    add_visual_op(document, instance_id, {"id": op_id, "type": "color", "params": dict(params)})


def add_instance_color_match(
    document,
    image_sources,
    instance_id: str,
    *,
    op_id: str,
    source_image,
    target_image,
    source_point,
    target_point,
    **options,
) -> None:
    _require_unlocked(document, [instance_id])
    create_color_match_op(
        document,
        instance_id,
        source_image=source_image,
        target_image=target_image,
        source_point=source_point,
        target_point=target_point,
        op_id=op_id,
        **options,
    )


def update_instance_visual_op(document, image_sources, instance_id: str, *, op_id: str, params: dict) -> None:
    _require_unlocked(document, [instance_id])
    update_visual_op(document, instance_id, op_id, params=dict(params))


def update_instance_mask(document, image_sources, instance_id: str, *, op_id: str, **params) -> None:
    _require_unlocked(document, [instance_id])
    update_visual_op(document, instance_id, op_id, params=params)


def reset_instance_masks(document, image_sources, instance_id: str) -> None:
    _require_unlocked(document, [instance_id])
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
    _require_unlocked(document, [instance_id])
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
    _require_unlocked(document, [instance_id])
    reset_transform(document, instance_id)


def set_instance_uniform_scale(document, image_sources, instance_id: str, scale: float) -> None:
    _require_unlocked(document, [instance_id])
    set_uniform_scale(document, instance_id, scale)


def flip_instance(document, image_sources, instance_id: str, *, horizontal: bool = False, vertical: bool = False) -> None:
    _require_unlocked(document, [instance_id])
    flip_transform(document, instance_id, horizontal=horizontal, vertical=vertical)


def nudge_instance(document, image_sources, instance_id: str, *, dx: float = 0.0, dy: float = 0.0) -> None:
    _require_unlocked(document, [instance_id])
    nudge_transform(document, instance_id, dx=dx, dy=dy)


def fit_instance_to_target(document, image_sources, instance_id: str, *, mode: str, image_size: tuple[int, int], target=None) -> None:
    _require_unlocked(document, [instance_id])
    fit_instance(document, instance_id, mode=mode, image_size=image_size, target=target)


def align_instance_to_target(document, image_sources, instance_id: str, *, anchor: str, image_size: tuple[int, int], target=None) -> None:
    _require_unlocked(document, [instance_id])
    align_instance(document, instance_id, anchor=anchor, image_size=image_size, target=target)


def set_instance_slot(document, image_sources, instance_id: str, slot: str) -> None:
    _require_unlocked(document, [instance_id])
    """Commit an Inspector slot edit through the public C1 slot API."""
    with document.transaction():
        _slots.set_slot(document, instance_id, str(slot))


def set_instance_plane(document, image_sources, instance_id: str, plane: str | None) -> None:
    _require_unlocked(document, [instance_id])
    """Commit an Inspector plane edit through the public C1 plane API."""
    with document.transaction():
        _slots.set_plane(document, instance_id, plane)


def delete_instances(document, image_sources, instance_ids: list[str]) -> None:
    """Delete selected layer instances as one undoable authoring edit.

    Assets are retained while referenced by another instance.  Relationships
    owned by the deleted instances are cleaned up so this operation cannot
    leave dangling VariantSet, expression, hierarchy, RigIntent, or donor
    slot references behind.
    """
    ids = list(dict.fromkeys(str(instance_id) for instance_id in instance_ids))
    missing = [instance_id for instance_id in ids if instance_id not in document.instances]
    if missing:
        raise KeyError(f"no such layer instance(s): {missing!r}")
    _require_unlocked(document, ids)
    deleted = set(ids)
    adopted_pairs: dict[tuple[str, str, str], set[str]] = {}
    for instance in document.instances.values():
        asset = document.assets.get(instance.asset_ref)
        provenance = asset.provenance if asset is not None else {}
        if provenance.get("operation") != "adopt_producer_derivative":
            continue
        key = (
            str(provenance.get("source_bundle", "")),
            str(provenance.get("source_semantic", "")),
            str(provenance.get("canonical_instance", "")),
        )
        adopted_pairs.setdefault(key, set()).add(instance.id)

    for (source_bundle, semantic, canonical_id), pair_ids in adopted_pairs.items():
        if canonical_id in deleted:
            raise ValueError(
                f"cannot delete canonical layer {canonical_id!r} while its {semantic!r} derivative pair "
                f"from {source_bundle!r} is retained; remove the saved pair first"
            )
        deleted_pair_ids = pair_ids & deleted
        if not deleted_pair_ids:
            continue
        if deleted_pair_ids != pair_ids:
            raise ValueError(
                f"delete both sides of the {semantic!r} derivative pair together, or revert it first"
            )
        canonical = document.instances.get(canonical_id)
        if canonical is None or not canonical.visible:
            raise ValueError(
                f"revert the {semantic!r} derivative pair to canonical before deleting it"
            )
    with document.transaction():
        for vs_id, variant_set in list(document.variant_sets.items()):
            members = [member for member in variant_set.get("members", []) if member not in deleted]
            if not members:
                document.variant_sets.pop(vs_id, None)
                for preset in document.expressions.values():
                    if isinstance(preset.get("variants"), dict):
                        preset["variants"].pop(vs_id, None)
                continue
            variant_set["members"] = members
            for field in ("default", "active"):
                if variant_set.get(field) in deleted or variant_set.get(field) not in members:
                    variant_set[field] = members[0]
            if isinstance(variant_set.get("state_groups"), dict):
                variant_set["state_groups"] = {
                    state: [member for member in members_for_state if member not in deleted]
                    for state, members_for_state in variant_set["state_groups"].items()
                    if any(member not in deleted for member in members_for_state)
                }
            if isinstance(variant_set.get("state_labels"), dict):
                variant_set["state_labels"] = {
                    member: state for member, state in variant_set["state_labels"].items() if member not in deleted
                }
            for preset in document.expressions.values():
                variants = preset.get("variants") if isinstance(preset, dict) else None
                if isinstance(variants, dict) and variants.get(vs_id) in deleted:
                    variants[vs_id] = variant_set["active"]

        rig_intent = document.rig_intent or {}
        scopes = rig_intent.get("deformation_scopes", {})
        for target in ids:
            scopes.pop(target, None)
        attachments = rig_intent.get("attachments", {})
        rig_intent["attachments"] = {
            attachment_id: attachment
            for attachment_id, attachment in attachments.items()
            if attachment.get("child") not in deleted and attachment.get("target") not in deleted
        }
        regions = rig_intent.get("regions", {})
        rig_intent["regions"] = {
            region_id: region for region_id, region in regions.items() if region.get("target") not in deleted
        }

        hierarchy = document.hierarchy or {}
        nodes = hierarchy.get("nodes", {})
        removed_node_ids = {
            node_id for node_id, node in nodes.items()
            if node_id in deleted or node.get("ref") in deleted
        }
        for node_id in removed_node_ids:
            nodes.pop(node_id, None)
        if isinstance(hierarchy.get("children"), dict):
            hierarchy["children"] = {
                parent: [child for child in children if child not in removed_node_ids and child in nodes]
                for parent, children in hierarchy["children"].items()
                if parent not in removed_node_ids
            }

        for family in ("eyes", "mouth"):
            for slot, entry in document.donor_slots.get(family, {}).items():
                if entry and entry.get("source_instance") in deleted:
                    document.donor_slots[family][slot] = None

        asset_refs = {document.instances[instance_id].asset_ref for instance_id in ids}
        for instance_id in ids:
            document.remove_instance(instance_id)
        still_used = {instance.asset_ref for instance in document.instances.values()}
        for asset_id in asset_refs - still_used:
            document.remove_asset(asset_id)
        used_source_ids = {
            asset.source_binding.source_id
            for asset in document.assets.values()
            if asset.source_binding is not None
        }
        # A deleted donor must be importable again even when the replacement
        # image has the same filename.  Keep producer bundle sources, but
        # discard orphaned Composer donor source records.
        document.sources = {
            source_id: source
            for source_id, source in document.sources.items()
            if source_id in used_source_ids
            or not isinstance(source.metadata, dict)
            or source.metadata.get("kind") != "donor"
        }
    # Keep the external image mapping intact.  It is not document state and
    # retaining the paths is what lets Undo immediately re-render restored
    # instances without requiring a bundle reload.


def assign_donor_slot(document, image_sources, family: str, slot: str, instance_id: str, *, status: str = "READY") -> None:
    """Assign an existing instance to the structured face-expression board."""
    _require_unlocked(document, [instance_id])
    set_donor_slot(document, family, slot, instance_id, status=status)


def clear_assigned_donor_slot(document, image_sources, family: str, slot: str) -> None:
    entry = (document.donor_slots.get(family, {}) or {}).get(slot)
    _require_unlocked(document, [entry.get("source_instance") if entry else None])
    clear_donor_slot(document, family, slot)


def harvest_semantic(document, image_sources, bundle_pool: dict, target_tag: str, run_label: str) -> None:
    """Commits one Harvest Workbench candidate pick (C5-C, directive #8.2)."""
    _require_unlocked(document, [instance_id_for(target_tag)])
    harvest_instance(document, image_sources, bundle_pool, target_tag, run_label)


def set_variant_active(document, image_sources, vs_id: str, member_id: str) -> None:
    """Commits one VariantSet exclusive switch (C5-D, directive #9.1)."""
    _require_unlocked(document, document.variant_sets.get(vs_id, {}).get("members", []))
    with document.transaction():
        _variants.set_active(document, vs_id, member_id)


def add_variant_member(document, image_sources, vs_id: str, instance_id: str, *, default: bool = False) -> None:
    """Drag-membership add (directive #9.2). Creates ``vs_id`` as a new
    exclusive VariantSet if it doesn't exist yet, otherwise appends."""
    _require_unlocked(document, [instance_id])
    with document.transaction():
        _variants.create_or_add_member(document, vs_id, instance_id, default=default)


def remove_variant_member(document, image_sources, vs_id: str, instance_id: str) -> None:
    """Drag-out / context-menu membership remove (directive #9.2)."""
    _require_unlocked(document, [instance_id])
    with document.transaction():
        _variants.remove_member(document, vs_id, instance_id)


def save_and_apply_expression(document, image_sources, preset_id: str, variants: dict) -> None:
    """One Expression Preset "Apply" (directive #9.3): saves the current
    per-VariantSet picks into the named preset, then applies them as the
    live active selection -- one transaction, one undo step. Creating vs.
    updating the preset is decided by whether ``preset_id`` already exists.
    """
    affected = {
        member
        for vs_id in variants
        for member in (document.variant_sets.get(vs_id, {}) or {}).get("members", [])
    }
    _require_unlocked(document, affected)
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
    if target_instance_id is not None:
        _require_unlocked(document, [target_instance_id])
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
    _require_unlocked(document, [target])
    _rig_intent.set_deformation_scope(document, target, scope)


def set_rig_attachment(document, image_sources, attachment_id: str, *, child: str, target: str, mode: str) -> None:
    """Create-or-replace one attachment intent (directive #11.2)."""
    _require_unlocked(document, [child, target])
    _rig_intent.set_attachment(document, attachment_id, child=child, target=target, mode=mode)


def remove_rig_attachment(document, image_sources, attachment_id: str) -> None:
    attachment = (document.rig_intent or {}).get("attachments", {}).get(attachment_id, {})
    _require_unlocked(document, [attachment.get("child"), attachment.get("target")])
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
    _require_unlocked(document, [target])
    return _secondary_regions.add_region(
        document,
        region_id,
        target=target,
        response_profile=response_profile,
        author_strength=author_strength,
        geometry=geometry,
    )


def remove_secondary_region(document, image_sources, region_id: str) -> None:
    region = (document.rig_intent or {}).get("regions", {}).get(region_id, {})
    _require_unlocked(document, [region.get("target")])
    _secondary_regions.remove_region(document, region_id)


def update_secondary_region(document, image_sources, region_id: str, **changes) -> dict:
    """response_profile / author_strength / locks edits (directive #12.2)."""
    region = (document.rig_intent or {}).get("regions", {}).get(region_id, {})
    _require_unlocked(document, [region.get("target")])
    return _secondary_regions.update_region(document, region_id, **changes)


def set_region_geometry(document, image_sources, region_id: str, geometry: dict) -> None:
    """Commits one two_lobe canvas drag as exactly one transaction
    (directive #12.1's "one region drag = one undo step")."""
    region = (document.rig_intent or {}).get("regions", {}).get(region_id, {})
    _require_unlocked(document, [region.get("target")])
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
    _require_unlocked(document, ordered_instance_ids or getattr(candidate, "instance_ids", []))
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
    plan = (document.bake_plans or {}).get(plan_id, {})
    _require_unlocked(document, plan.get("sources", []))
    return apply_logical_bake_plan(document, image_sources, plan_id, work_dir=work_dir, profile=profile)


def reorder_draw_order(document, new_order: list) -> None:
    old_order = list(document.composition.get("draw_order", []))
    new_order = list(new_order)
    if old_order != new_order:
        new_positions = {instance_id: index for index, instance_id in enumerate(new_order)}
        old_positions = {instance_id: index for index, instance_id in enumerate(old_order)}
        changed_positions = [
            instance_id
            for instance_id in set(old_positions) | set(new_positions)
            if old_positions.get(instance_id) != new_positions.get(instance_id)
        ]
        _require_unlocked(document, changed_positions)
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


def move_draw_order_selection(
    document, instance_ids: list[str], *, direction: int = 0, to_extreme: int = 0
) -> bool:
    """Move a selected set as one stable authoring operation.

    Non-selected layers keep their relative order, and selected layers retain
    their own draw-order order even when the user's selection order differs.
    """
    order = list(document.composition.get("draw_order", []))
    selected = {instance_id for instance_id in instance_ids if instance_id in order}
    if not selected:
        return False

    if to_extreme:
        block = [instance_id for instance_id in order if instance_id in selected]
        remaining = [instance_id for instance_id in order if instance_id not in selected]
        new_order = block + remaining if to_extreme < 0 else remaining + block
    elif direction < 0:
        new_order = list(order)
        for index in range(1, len(new_order)):
            if new_order[index] in selected and new_order[index - 1] not in selected:
                new_order[index - 1], new_order[index] = new_order[index], new_order[index - 1]
    elif direction > 0:
        new_order = list(order)
        for index in range(len(new_order) - 2, -1, -1):
            if new_order[index] in selected and new_order[index + 1] not in selected:
                new_order[index], new_order[index + 1] = new_order[index + 1], new_order[index]
    else:
        return False

    if new_order == order:
        return False
    reorder_draw_order(document, new_order)
    return True


def adopt_derived_split(document, image_sources, candidates, *, canonical_instance_id: str | None = None) -> list[str]:
    targets = [canonical_instance_id]
    targets.extend(
        instance.id
        for instance in document.instances.values()
        if (asset := document.assets.get(instance.asset_ref)) is not None
        and asset.provenance.get("operation") == "adopt_producer_derivative"
        and asset.provenance.get("canonical_instance") == canonical_instance_id
    )
    _require_unlocked(document, targets)
    return _adopt_derived_split(
        document, image_sources, candidates, canonical_instance_id=canonical_instance_id
    )


def revert_derived_split(
    document, image_sources, semantic: str, *, source_bundle: str, canonical_instance_id: str
) -> None:
    targets = [canonical_instance_id]
    targets.extend(
        instance.id
        for instance in document.instances.values()
        if (asset := document.assets.get(instance.asset_ref)) is not None
        and asset.provenance.get("operation") == "adopt_producer_derivative"
        and asset.provenance.get("source_semantic") == semantic
        and asset.provenance.get("source_bundle") == source_bundle
        and asset.provenance.get("canonical_instance") == canonical_instance_id
    )
    _require_unlocked(document, targets)
    _revert_derived_split(
        document,
        image_sources,
        semantic,
        source_bundle=source_bundle,
        canonical_instance_id=canonical_instance_id,
    )
