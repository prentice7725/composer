"""AutoRig-facing Rig Bundle export (C6-I).

Rig Bundle is deliberately separate from an Assembly Bundle.  It contains
canonical rendered layers and the authored rig-facing contracts, but not UI
session state, transient previews, or Bake Plan recipes that were not baked.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from .bundle import ASSEMBLY_FORMAT
from .render import render_subset
from .visual_ops import apply_visual_ops

RIG_BUNDLE_FORMAT = "portrait-rig-bundle"
RIG_BUNDLE_VERSION = "0.3"


class RigBundleError(ValueError):
    pass


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
        if not instance.visible:
            continue
        if instance_id not in image_sources or not Path(image_sources[instance_id]).exists():
            errors.append(f"canonical layer output missing for visible instance {instance_id!r}")
        asset = document.assets.get(instance.asset_ref)
        if asset is None:
            continue
        if asset.source_binding is None and not asset.provenance.get("derived_from"):
            errors.append(f"visible instance {instance_id!r} has no resolved source or derived provenance")
        try:
            _canonical_layer_image(document, image_sources, instance_id)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"visible instance {instance_id!r} cannot be canonically evaluated: {exc}")
    for attachment_id, attachment in document.rig_intent.get("attachments", {}).items():
        if not isinstance(attachment, dict) or attachment.get("child") not in document.instances:
            errors.append(f"attachment {attachment_id!r} has an unknown child")
        if not isinstance(attachment, dict) or attachment.get("target") not in document.instances:
            errors.append(f"attachment {attachment_id!r} has an unknown target")
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
    if manifest.get("format") != RIG_BUNDLE_FORMAT:
        errors.append(f"unexpected Rig Bundle format: {manifest.get('format')!r}")
    if manifest.get("version") != RIG_BUNDLE_VERSION:
        errors.append(f"unexpected Rig Bundle version: {manifest.get('version')!r}")
    required = ("canvas", "layers", "draw_order", "instances", "assets", "rig_intent", "donors")
    for key in required:
        if key not in manifest:
            errors.append(f"manifest missing required field {key!r}")
    visible_ids = list(manifest.get("layers", []))
    instances = manifest.get("instances", {})
    if set(manifest.get("draw_order", [])) != set(visible_ids):
        errors.append("manifest.draw_order must contain exactly the visible canonical layers")
    for instance_id in visible_ids:
        if instance_id not in instances:
            errors.append(f"manifest.instances missing visible layer {instance_id!r}")
        if not (out_dir / "layers" / f"{instance_id}.png").exists():
            errors.append(f"missing canonical layer artifact for {instance_id!r}")
    for instance_id, instance in instances.items():
        for op in instance.get("visual_ops", []):
            if op.get("type") != "mask":
                continue
            raw_path = op.get("params", {}).get("path")
            if not isinstance(raw_path, str) or not raw_path.startswith("masks/"):
                errors.append(f"mask VisualOp for {instance_id!r} is not bundle-relative: {raw_path!r}")
                continue
            if not (out_dir / raw_path).exists():
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
    """Validate and write a deterministic AutoRig-facing bundle.

    The output contains only visible canonical instances.  The source
    ``image_sources`` and AssemblyDocument are never modified.
    """
    errors = validate_rig_export(document, image_sources)
    if errors:
        raise RigBundleError("; ".join(errors))

    out_dir = Path(out_dir)
    layers_dir = out_dir / "layers"
    masks_dir = out_dir / "masks"
    provenance_dir = out_dir / "provenance"
    for directory in (layers_dir, masks_dir, provenance_dir):
        directory.mkdir(parents=True, exist_ok=True)

    visible_ids = [
        instance_id
        for instance_id in document.composition.get("draw_order", [])
        if instance_id in document.instances and document.instances[instance_id].visible
    ]
    canonical_layers = {
        instance_id: _canonical_layer_image(document, image_sources, instance_id)
        for instance_id in visible_ids
    }
    for instance_id, image in canonical_layers.items():
        image.save(layers_dir / f"{instance_id}.png")

    # Keep mask artifacts self-contained even though the Rig Bundle omits
    # transient editor state.  The authored stack remains in the Assembly;
    # AutoRig receives the pixels and the mask files it needs for inspection.
    for instance_id in visible_ids:
        for op in document.instances[instance_id].visual_ops:
            if op.get("type") != "mask":
                continue
            raw_path = op.get("params", {}).get("path", "")
            source_path = _resolve_visual_op_path(Path(image_sources[instance_id]), raw_path)
            if source_path.exists():
                shutil.copyfile(source_path, masks_dir / f"{instance_id}__{op.get('id', 'mask')}.png")

    if reference_image is None:
        # Evaluate through the same source-map compositor used by Bake. This
        # also handles freshly imported identity documents whose source files
        # are still named by Portrait Bundle tags rather than instance ids.
        reference_image = render_subset(document, image_sources, visible_ids)
    reference_image.save(out_dir / "reference.png")

    manifest = {
        "format": RIG_BUNDLE_FORMAT,
        "version": RIG_BUNDLE_VERSION,
        "assembly_format": ASSEMBLY_FORMAT,
        "canvas": dict(document.composition.get("canvas", {})),
        "layers": visible_ids,
        "draw_order": list(visible_ids),
        "assets": {
            asset_id: asset.to_dict()
            for asset_id, asset in document.assets.items()
            if any(
                instance.asset_ref == asset_id and instance.visible
                for instance in document.instances.values()
            )
        },
        "instances": {},
        "variant_sets": document.variant_sets,
        "expressions": document.expressions,
        "rig_intent": document.rig_intent,
        "secondary_regions": document.rig_intent.get("regions", {}),
        "attachments": document.rig_intent.get("attachments", {}),
        "donors": {
            asset_id: asset.provenance
            for asset_id, asset in document.assets.items()
            if asset.provenance.get("operation") in {"donor_import", "donor_replace"}
        },
    }
    for instance_id in visible_ids:
        instance_data = document.instances[instance_id].to_dict()
        for op in instance_data.get("visual_ops", []):
            if op.get("type") != "mask":
                continue
            mask_name = f"{instance_id}__{op.get('id', 'mask')}.png"
            mask_path = masks_dir / mask_name
            if not mask_path.exists():
                raise RigBundleError(
                    f"mask artifact missing for visible instance {instance_id!r}: {op.get('id')!r}"
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
    bundle_errors = validate_exported_rig_bundle(out_dir)
    if bundle_errors:
        raise RigBundleError("; ".join(bundle_errors))
    return out_dir
