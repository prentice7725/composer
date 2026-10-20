"""AutoRig-facing Rig Bundle export (C6-I).

Rig Bundle is deliberately separate from an Assembly Bundle.  It contains
canonical rendered layers and the authored rig-facing contracts, but not UI
session state, transient previews, or Bake Plan recipes that were not baked.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from .bundle import ASSEMBLY_FORMAT
from .render import render_subset
from .visual_ops import apply_visual_ops
from .expressions import build_expression_intent

RIG_BUNDLE_FORMAT = "portrait-rig-bundle"
RIG_BUNDLE_VERSION = "0.4"


class RigBundleError(ValueError):
    pass


_BUNDLE_ID = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')


def _safe_bundle_id(value: object) -> bool:
    """Whether an authored ID is safe to use as one bundle path component."""
    if not isinstance(value, str) or value in {".", ".."} or value != value.strip():
        return False
    if value.endswith(".") or not _BUNDLE_ID.fullmatch(value):
        return False
    device_name = value.split(".", 1)[0].upper()
    return device_name not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _visual_ops_root(source_path: Path) -> Path:
    """Return the bundle/source root used for relative mask paths."""
    return source_path.parent.parent if source_path.parent.name == "layers" else source_path.parent


def _resolve_visual_op_path(source_path: Path, raw_path: str) -> Path:
    """Resolve a VisualOp artifact using the same roots as canonical render."""
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    root = _visual_ops_root(source_path)
    for resolved in (root / candidate, source_path.parent / candidate, candidate):
        if resolved.exists():
            return resolved
    return root / candidate


def _canonical_layer_image(document, image_sources: dict, instance_id: str) -> Image.Image:
    """Evaluate one layer's authored pixel operations for Rig Bundle output.

    Instance transform and draw order remain metadata consumed by AutoRig;
    the exported PNG contains the source pixels after the serialized
    non-destructive VisualOps stack (and instance opacity) has been evaluated.
    """
    source_path = Path(image_sources[instance_id])
    instance = document.instances[instance_id]
    with Image.open(source_path) as source:
        image = source.convert("RGBA")
    image = apply_visual_ops(image, instance.visual_ops, base_dir=_visual_ops_root(source_path))
    if instance.opacity < 1.0:
        red, green, blue, alpha = image.split()
        alpha = alpha.point(lambda value, opacity=instance.opacity: round(value * opacity))
        image = Image.merge("RGBA", (red, green, blue, alpha))
    return image


def validate_rig_export(document, image_sources: dict) -> list[str]:
    errors = []
    result = document.validate(production=True)
    errors.extend(result.errors)
    variant_members: set[str] = set()
    variant_sets = document.variant_sets if isinstance(document.variant_sets, dict) else {}
    if not isinstance(document.variant_sets, dict):
        errors.append("variant_sets must be an object")
    for set_id, spec in variant_sets.items():
        if not _safe_bundle_id(set_id):
            errors.append(f"VariantSet id {set_id!r} is not a safe bundle identifier")
        if not isinstance(spec, dict):
            errors.append(f"VariantSet {set_id!r} must be an object")
            continue
        members = spec.get("members", [])
        if not isinstance(members, list):
            errors.append(f"VariantSet {set_id!r}.members must be an array")
            continue
        for member_id in members:
            if not isinstance(member_id, str) or member_id not in document.instances:
                errors.append(f"VariantSet {set_id!r} references unknown member {member_id!r}")
                continue
            variant_members.add(member_id)
    review = getattr(document, "remap_review", None) or {}
    if review.get("status") == "REVIEW_REQUIRED":
        unresolved = review.get("unresolved_assets", [])
        errors.append(
            "source remap review is unresolved"
            + (f" for {unresolved!r}" if unresolved else "")
        )
    for plan_id, plan in document.bake_plans.items():
        if plan.get("status") != "BAKED":
            errors.append(f"bake plan {plan_id!r} is not BAKED (status={plan.get('status')!r})")
    for instance_id, instance in document.instances.items():
        if not _safe_bundle_id(instance_id):
            errors.append(f"instance id {instance_id!r} is not a safe bundle identifier")
        is_variant = instance_id in variant_members
        if not instance.visible and not is_variant:
            continue
        role = "variant" if is_variant and not instance.visible else "canonical"
        if instance_id not in image_sources or not Path(image_sources[instance_id]).exists():
            errors.append(f"{role} layer output missing for instance {instance_id!r}")
        asset = document.assets.get(instance.asset_ref)
        if asset is None:
            continue
        if asset.source_binding is None and not asset.provenance.get("derived_from"):
            errors.append(f"{role} instance {instance_id!r} has no resolved source or derived provenance")
        try:
            _canonical_layer_image(document, image_sources, instance_id)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"{role} instance {instance_id!r} cannot be canonically evaluated: {exc}")

    expression_intent = build_expression_intent(document)
    for channel, mapping in expression_intent.get("articulation", {}).items():
        set_id = mapping.get("variant_set")
        variant_spec = variant_sets.get(set_id) if _safe_bundle_id(set_id) else None
        members = variant_spec.get("members", []) if isinstance(variant_spec, dict) else []
        for state, instance_id in mapping.get("states", {}).items():
            if not set_id or instance_id not in members:
                errors.append(
                    f"expression articulation {channel}.{state} must reference a member of its VariantSet"
                )
    for preset_id, mapping in expression_intent.get("presets", {}).items():
        for channel, member_id in mapping.items():
            if channel == "preserve":
                continue
            variant_spec = variant_sets.get(channel) if _safe_bundle_id(channel) else None
            members = variant_spec.get("members", []) if isinstance(variant_spec, dict) else []
            if member_id not in members:
                errors.append(
                    f"expression preset {preset_id!r} references unknown member {member_id!r} "
                    f"in VariantSet {channel!r}"
                )
    for attachment_id, attachment in document.rig_intent.get("attachments", {}).items():
        if not isinstance(attachment, dict) or attachment.get("child") not in document.instances:
            errors.append(f"attachment {attachment_id!r} has an unknown child")
        if not isinstance(attachment, dict) or attachment.get("target") not in document.instances:
            errors.append(f"attachment {attachment_id!r} has an unknown target")
    for instance_id, instance in document.instances.items():
        for op in getattr(instance, "visual_ops", []):
            if not isinstance(op, dict) or op.get("type") != "mask":
                continue
            if not _safe_bundle_id(op.get("id", "mask")):
                errors.append(f"mask operation on {instance_id!r} has an unsafe id")
    return errors


def validate_exported_rig_bundle(out_dir: Path) -> list[str]:
    """Validate the on-disk Rig Bundle contract without touching Composer state."""
    out_dir = Path(out_dir)
    errors: list[str] = []
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"missing Rig Bundle manifest: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid Rig Bundle manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["invalid Rig Bundle manifest: top-level JSON value must be an object"]
    if manifest.get("format") != RIG_BUNDLE_FORMAT:
        errors.append(f"unexpected Rig Bundle format: {manifest.get('format')!r}")
    if manifest.get("version") != RIG_BUNDLE_VERSION:
        errors.append(f"unexpected Rig Bundle version: {manifest.get('version')!r}")
    required = (
        "canvas", "layers", "draw_order", "instance_draw_order", "variant_layers", "instances", "assets",
        "variant_sets", "expressions", "rig_intent", "donors", "source_metadata",
        "expression_intent",
    )
    for key in required:
        if key not in manifest:
            errors.append(f"manifest missing required field {key!r}")
    visible_ids = manifest.get("layers", [])
    draw_order = manifest.get("draw_order", [])
    instance_draw_order = manifest.get("instance_draw_order", [])
    instances = manifest.get("instances", {})
    assets = manifest.get("assets", {})
    variant_sets = manifest.get("variant_sets", {})
    variant_layers = manifest.get("variant_layers", {})
    if not isinstance(visible_ids, list) or any(not _safe_bundle_id(item) for item in visible_ids):
        errors.append("manifest.layers must be an array of instance ids")
        visible_ids = []
    if not isinstance(draw_order, list) or draw_order != visible_ids:
        errors.append("manifest.draw_order must match manifest.layers in visible draw order")
    if (
        not isinstance(instance_draw_order, list)
        or any(not _safe_bundle_id(item) for item in instance_draw_order)
        or len(set(instance_draw_order)) != len(instance_draw_order)
    ):
        errors.append("manifest.instance_draw_order must be an array of unique instance ids")
        instance_draw_order = []
    if len(set(visible_ids)) != len(visible_ids):
        errors.append("manifest.layers must not contain duplicate instance ids")
    if not isinstance(instances, dict):
        errors.append("manifest.instances must be an object")
        instances = {}
    if not isinstance(assets, dict):
        errors.append("manifest.assets must be an object")
        assets = {}
    if not isinstance(variant_sets, dict):
        errors.append("manifest.variant_sets must be an object")
        variant_sets = {}
    if not isinstance(variant_layers, dict):
        errors.append("manifest.variant_layers must be an object")
        variant_layers = {}
    variant_members: set[str] = set()
    for set_id, spec in variant_sets.items():
        if not _safe_bundle_id(set_id):
            errors.append(f"manifest.variant_sets id {set_id!r} is unsafe")
        if not isinstance(spec, dict) or not isinstance(spec.get("members", []), list):
            errors.append(f"manifest.variant_sets[{set_id!r}].members must be an array")
            continue
        for member_id in spec.get("members", []):
            if not _safe_bundle_id(member_id):
                errors.append(f"manifest.variant_sets[{set_id!r}] contains a non-string member")
            else:
                variant_members.add(member_id)
    for instance_id in instances:
        if not _safe_bundle_id(instance_id):
            errors.append(f"manifest.instances id {instance_id!r} is unsafe")
    for asset_id in assets:
        if not _safe_bundle_id(asset_id):
            errors.append(f"manifest.assets id {asset_id!r} is unsafe")
    for instance_id in visible_ids:
        if instance_id not in instances:
            errors.append(f"manifest.instances missing visible layer {instance_id!r}")
        if not (out_dir / "layers" / f"{instance_id}.png").exists():
            errors.append(f"missing canonical layer artifact for {instance_id!r}")
    for instance_id, relative in variant_layers.items():
        if instance_id not in variant_members:
            errors.append(f"variant layer {instance_id!r} is not referenced by any VariantSet")
        if instance_id in visible_ids:
            errors.append(f"visible variant member {instance_id!r} must use its canonical layer artifact")
        if not _safe_bundle_id(instance_id):
            errors.append(f"variant layer id {instance_id!r} is unsafe")
            continue
        expected = f"variants/{instance_id}.png"
        if relative != expected:
            errors.append(f"variant layer for {instance_id!r} must use bundle-relative path {expected!r}")
            continue
        if not (out_dir / expected).is_file():
            errors.append(f"variant layer artifact missing for {instance_id!r}: {relative!r}")
    exported_ids = set(visible_ids) | set(variant_layers)
    if set(instance_draw_order) != exported_ids:
        errors.append("manifest.instance_draw_order must contain every and only exported instance")
    if [item for item in instance_draw_order if item in visible_ids] != visible_ids:
        errors.append("manifest.instance_draw_order must preserve visible draw_order")
    for instance_id in sorted(variant_members - exported_ids):
        errors.append(f"VariantSet member {instance_id!r} has no exported layer artifact")
    for instance_id, instance in instances.items():
        if not isinstance(instance, dict):
            errors.append(f"manifest.instances[{instance_id!r}] must be an object")
            continue
        asset_ref = instance.get("asset_ref")
        if not isinstance(asset_ref, str) or asset_ref not in assets:
            errors.append(f"manifest.instances[{instance_id!r}] references unknown asset {asset_ref!r}")
    expression_intent = manifest.get("expression_intent")
    if not isinstance(expression_intent, dict):
        errors.append("manifest.expression_intent must be an object")
    elif expression_intent.get("profile") != "face_expression_core_v2":
        errors.append("manifest.expression_intent.profile must be 'face_expression_core_v2'")
    else:
        articulation = expression_intent.get("articulation", {})
        if not isinstance(articulation, dict):
            errors.append("manifest.expression_intent.articulation must be an object")
            articulation = {}
        for channel, mapping in articulation.items():
            if not isinstance(mapping, dict):
                errors.append(f"expression_intent.articulation[{channel!r}] must be an object")
                continue
            set_id = mapping.get("variant_set")
            variant_spec = variant_sets.get(set_id) if _safe_bundle_id(set_id) else None
            set_members = variant_spec.get("members", []) if isinstance(variant_spec, dict) else []
            states = mapping.get("states", {})
            if not isinstance(states, dict):
                errors.append(f"expression_intent.articulation[{channel!r}].states must be an object")
                continue
            for state, instance_id in states.items():
                if not isinstance(instance_id, str) or instance_id not in set_members or instance_id not in exported_ids:
                    errors.append(
                        f"expression articulation {channel}.{state} references an unexported VariantSet member"
                    )
        presets = expression_intent.get("presets", {})
        if not isinstance(presets, dict):
            errors.append("manifest.expression_intent.presets must be an object")
            presets = {}
        for preset_id, mapping in presets.items():
            if not isinstance(mapping, dict):
                errors.append(f"expression_intent.presets[{preset_id!r}] must be an object")
                continue
            for channel, member_id in mapping.items():
                if channel == "preserve":
                    continue
                variant_spec = variant_sets.get(channel) if _safe_bundle_id(channel) else None
                members = variant_spec.get("members", []) if isinstance(variant_spec, dict) else []
                if not isinstance(member_id, str) or member_id not in members:
                    errors.append(
                        f"expression preset {preset_id!r} references unknown member {member_id!r} "
                        f"in VariantSet {channel!r}"
                    )
    for instance_id, instance in instances.items():
        if not isinstance(instance, dict):
            continue
        visual_ops = instance.get("visual_ops", [])
        if not isinstance(visual_ops, list):
            errors.append(f"manifest.instances[{instance_id!r}].visual_ops must be an array")
            continue
        for op in visual_ops:
            if not isinstance(op, dict):
                errors.append(f"VisualOp for {instance_id!r} must be an object")
                continue
            if op.get("type") != "mask":
                continue
            params = op.get("params", {})
            raw_path = params.get("path") if isinstance(params, dict) else None
            path_parts = raw_path.split("/") if isinstance(raw_path, str) else []
            if (
                not isinstance(raw_path, str)
                or len(path_parts) != 2
                or path_parts[0] != "masks"
                or not _safe_bundle_id(Path(path_parts[-1]).stem)
                or Path(path_parts[-1]).suffix.lower() != ".png"
                or "\\" in raw_path
            ):
                errors.append(f"mask VisualOp for {instance_id!r} is not bundle-relative: {raw_path!r}")
                continue
            if not (out_dir / raw_path).is_file():
                errors.append(f"mask VisualOp artifact missing for {instance_id!r}: {raw_path!r}")
    for relative in (
        "reference.png",
        "rig_intent.json",
        "donors.json",
        "secondary_regions.json",
        "attachments.json",
        "provenance/assembly.json",
    ):
        if not (out_dir / relative).exists():
            errors.append(f"missing Rig Bundle artifact: {relative}")
    return errors


def export_rig_bundle(document, image_sources: dict, out_dir: Path, *, reference_image=None) -> Path:
    """Validate, stage, and atomically publish a deterministic Rig Bundle."""
    errors = validate_rig_export(document, image_sources)
    if errors:
        raise RigBundleError("; ".join(errors))

    out_dir = Path(out_dir)
    if out_dir.is_symlink() or (out_dir.exists() and not out_dir.is_dir()):
        raise RigBundleError(f"Rig Bundle target must be a regular directory: {out_dir}")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    with tempfile.TemporaryDirectory(prefix=f".{out_dir.name}.staging-", dir=out_dir.parent) as temp_root:
        staged_out = Path(temp_root) / "bundle"
        staged_out.mkdir()
        _write_rig_bundle_stage(document, image_sources, staged_out, reference_image=reference_image)
        bundle_errors = validate_exported_rig_bundle(staged_out)
        if bundle_errors:
            raise RigBundleError("; ".join(bundle_errors))

        if out_dir.exists():
            backup = out_dir.with_name(f".{out_dir.name}.backup-{uuid.uuid4().hex}")
            os.replace(out_dir, backup)
        try:
            os.replace(staged_out, out_dir)
        except Exception:
            if backup is not None and backup.exists() and not out_dir.exists():
                os.replace(backup, out_dir)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    return out_dir


def _write_rig_bundle_stage(document, image_sources: dict, out_dir: Path, *, reference_image=None) -> None:
    """Build a complete v0.4 bundle in a new staging directory."""
    layers_dir = out_dir / "layers"
    variants_dir = out_dir / "variants"
    masks_dir = out_dir / "masks"
    provenance_dir = out_dir / "provenance"
    for directory in (layers_dir, variants_dir, masks_dir, provenance_dir):
        directory.mkdir(parents=True, exist_ok=True)

    all_order = [
        instance_id
        for instance_id in document.composition.get("draw_order", [])
        if instance_id in document.instances
    ]
    all_order.extend(
        instance_id
        for instance_id in sorted(document.instances, key=lambda key: document.instances[key].draw_order)
        if instance_id not in all_order
    )
    visible_ids = [
        instance_id for instance_id in all_order if document.instances[instance_id].visible
    ]
    variant_members = {
        member_id
        for spec in (document.variant_sets or {}).values()
        if isinstance(spec, dict)
        for member_id in spec.get("members", [])
        if isinstance(member_id, str) and member_id in document.instances
    }
    hidden_variant_ids = [
        instance_id for instance_id in all_order
        if instance_id in variant_members and instance_id not in visible_ids
    ]
    export_ids = [*visible_ids, *hidden_variant_ids]
    canonical_layers = {
        instance_id: _canonical_layer_image(document, image_sources, instance_id)
        for instance_id in export_ids
    }
    for instance_id in visible_ids:
        canonical_layers[instance_id].save(layers_dir / f"{instance_id}.png")
    for instance_id in hidden_variant_ids:
        canonical_layers[instance_id].save(variants_dir / f"{instance_id}.png")

    # Keep mask artifacts self-contained for visible and alternate states.
    for instance_id in export_ids:
        for op in document.instances[instance_id].visual_ops:
            if op.get("type") != "mask":
                continue
            if not _safe_bundle_id(op.get("id", "mask")):
                raise RigBundleError(f"mask operation on {instance_id!r} has an unsafe id")
            raw_path = op.get("params", {}).get("path", "")
            source_path = _resolve_visual_op_path(Path(image_sources[instance_id]), raw_path)
            if not source_path.is_file():
                raise RigBundleError(
                    f"mask artifact missing for instance {instance_id!r}: {op.get('id')!r}"
                )
            shutil.copyfile(source_path, masks_dir / f"{instance_id}__{op.get('id', 'mask')}.png")

    if reference_image is None:
        # The reference remains the visible Assembly truth. Alternate states
        # are exported separately and are not activated by this operation.
        reference_image = render_subset(document, image_sources, visible_ids)
    reference_image.save(out_dir / "reference.png")

    exported_asset_ids = {
        document.instances[instance_id].asset_ref for instance_id in export_ids
    }
    manifest = {
        "format": RIG_BUNDLE_FORMAT,
        "version": RIG_BUNDLE_VERSION,
        "assembly_format": ASSEMBLY_FORMAT,
        "canvas": dict(document.composition.get("canvas", {})),
        "layers": visible_ids,
        "draw_order": list(visible_ids),
        "instance_draw_order": [instance_id for instance_id in all_order if instance_id in export_ids],
        "variant_layers": {
            instance_id: f"variants/{instance_id}.png" for instance_id in hidden_variant_ids
        },
        "assets": {
            asset_id: document.assets[asset_id].to_dict()
            for asset_id in sorted(exported_asset_ids)
            if asset_id in document.assets
        },
        "instances": {},
        "variant_sets": document.variant_sets,
        "expressions": document.expressions,
        "expression_intent": build_expression_intent(document),
        "rig_intent": document.rig_intent,
        "secondary_regions": document.rig_intent.get("regions", {}),
        "attachments": document.rig_intent.get("attachments", {}),
        "donors": {
            asset_id: asset.provenance
            for asset_id, asset in document.assets.items()
            if asset.provenance.get("operation") in {"donor_import", "donor_replace"}
        },
        "source_metadata": {
            source_id: {
                key: source.metadata[key]
                for key in ("generation", "canvas", "validation", "derived", "warnings")
                if key in source.metadata
            }
            for source_id, source in document.sources.items()
        },
    }
    for instance_id in export_ids:
        instance_data = document.instances[instance_id].to_dict()
        for op in instance_data.get("visual_ops", []):
            if op.get("type") != "mask":
                continue
            mask_name = f"{instance_id}__{op.get('id', 'mask')}.png"
            mask_path = masks_dir / mask_name
            if not mask_path.is_file():
                raise RigBundleError(
                    f"mask artifact missing for instance {instance_id!r}: {op.get('id')!r}"
                )
            op.setdefault("params", {})["path"] = f"masks/{mask_name}"
        manifest["instances"][instance_id] = instance_data
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "rig_intent.json").write_text(json.dumps(document.rig_intent, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "donors.json").write_text(
        json.dumps(manifest["donors"], indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "secondary_regions.json").write_text(
        json.dumps(document.rig_intent.get("regions", {}), indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "attachments.json").write_text(
        json.dumps(document.rig_intent.get("attachments", {}), indent=2, sort_keys=True), encoding="utf-8"
    )
    (provenance_dir / "assembly.json").write_text(
        json.dumps(document.provenance.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
