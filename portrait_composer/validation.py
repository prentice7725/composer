"""Document validation.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #30.

Hard errors block commit (see document.py's transaction model). Warnings
never block -- they're surfaced to the caller/CLI for review.

Only the C0-era checks are wired up: missing source, missing asset, missing
instance ref, duplicate stable id, invalid draw order ref, invalid
VariantSet member, invalid rig target, broken attachment target, and (in
``production`` mode) unresolved source binding. Occlusion/bake/secondary
checks are C1+ and are documented as TODO stubs -- they need data
(hierarchy, geometry, bake state) this phase does not populate yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


def validate(document: "AssemblyDocument", production: bool = False) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    asset_ids = set(document.assets.keys())
    instance_ids = set(document.instances.keys())

    # duplicate stable ID: an instance id must not collide with an asset id
    # (within each namespace, the backing dict already enforces uniqueness).
    collisions = asset_ids & instance_ids
    for cid in sorted(collisions):
        errors.append(f"duplicate stable ID used by both an asset and an instance: {cid!r}")

    # missing source / unresolved source binding
    for asset_id, asset in document.assets.items():
        sb = asset.source_binding
        if sb is None:
            if production:
                errors.append(f"asset {asset_id!r}: unresolved source binding (required for production export)")
            continue
        if sb.source_id not in document.sources:
            errors.append(f"asset {asset_id!r}: missing source {sb.source_id!r}")

    # missing asset (instance -> asset_ref)
    for inst_id, inst in document.instances.items():
        if inst.asset_ref not in document.assets:
            errors.append(f"instance {inst_id!r}: missing asset {inst.asset_ref!r}")
        if inst.transform_link and inst.transform_link not in document.links:
            warnings.append(f"instance {inst_id!r}: transform_link {inst.transform_link!r} not defined")

    # invalid draw order ref / missing instance ref
    draw_order = document.composition.get("draw_order", [])
    seen = set()
    for ref in draw_order:
        if ref not in instance_ids:
            errors.append(f"composition.draw_order: invalid instance ref {ref!r}")
        elif ref in seen:
            errors.append(f"composition.draw_order: duplicate instance ref {ref!r}")
        seen.add(ref)
    missing_from_order = instance_ids - set(draw_order)
    for inst_id in sorted(missing_from_order):
        warnings.append(f"instance {inst_id!r}: not present in composition.draw_order")

    # VariantSet member validity
    for vs_id, vs in document.variant_sets.items():
        members = vs.get("members", [])
        for m in members:
            if m not in asset_ids and m not in instance_ids:
                errors.append(f"variant_set {vs_id!r}: invalid member {m!r} (no such asset or instance)")
        default = vs.get("default")
        if default is not None and default not in members:
            errors.append(f"variant_set {vs_id!r}: default {default!r} not in members")

    # rig intent: regions/attachments must target real instances or slots
    rig_intent = document.rig_intent or {}
    slot_names = {inst.slot for inst in document.instances.values()}
    for region_id, region in rig_intent.get("regions", {}).items():
        target = region.get("target")
        if target is not None and target not in instance_ids and target not in slot_names:
            errors.append(f"rig_intent.regions[{region_id!r}]: invalid target {target!r}")
    for attach_id, attach in rig_intent.get("attachments", {}).items():
        for key in ("target", "child"):
            ref = attach.get(key)
            if ref is not None and ref not in instance_ids and ref not in slot_names:
                errors.append(f"rig_intent.attachments[{attach_id!r}]: broken attachment {key} {ref!r}")

    return ValidationResult(errors=errors, warnings=warnings)
