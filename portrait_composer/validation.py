"""Document validation.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #30.

Hard errors block commit (see document.py's transaction model). Warnings
never block -- they're surfaced to the caller/CLI for review.

C0 checks: missing source, missing asset, missing instance ref, duplicate
stable id, invalid draw order ref, invalid VariantSet member, invalid rig
target, broken attachment target, and (in ``production`` mode) unresolved
source binding.

C1 checks (directive #11-14): hierarchy node/parent/ref/cycle integrity
(hierarchy.py), instance.plane must be one of its asset's declared planes,
transform_link two-way consistency (an instance's transform_link must name
a link it's actually a member of, and vice versa), VariantSet active-member
validity, and an unrecognized slot (soft -- slots.py's vocabulary is
explicitly open).

C4 checks validate the typed RigIntent vocabulary and secondary-region shape.
This is authoring-contract validation, not AutoRig mesh/deformation QA.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import hierarchy as _hierarchy
from .slots import is_known_slot
from .rig_intent import ATTACHMENT_MODES, DEFORMATION_SCOPES, LOGICAL_SURFACES
from .secondary_regions import GEOMETRY_KINDS, RESPONSE_PROFILES

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
            # a baked/derived asset (bake.py, C2) legitimately has no single
            # upstream source_binding -- its provenance chain explains its
            # origin instead. Only flag a *non*-derived asset here.
            is_derived = bool(asset.provenance.get("derived_from"))
            if production and not is_derived:
                errors.append(f"asset {asset_id!r}: unresolved source binding (required for production export)")
            continue
        if sb.source_id not in document.sources:
            errors.append(f"asset {asset_id!r}: missing source {sb.source_id!r}")

    # missing asset (instance -> asset_ref); plane membership; slot vocabulary; transform_link
    for inst_id, inst in document.instances.items():
        asset = document.assets.get(inst.asset_ref)
        if asset is None:
            errors.append(f"instance {inst_id!r}: missing asset {inst.asset_ref!r}")
        elif inst.plane is not None and inst.plane not in asset.planes:
            errors.append(
                f"instance {inst_id!r}: plane {inst.plane!r} is not declared by asset "
                f"{inst.asset_ref!r} (planes={asset.planes!r})"
            )

        if not is_known_slot(inst.slot):
            warnings.append(f"instance {inst_id!r}: slot {inst.slot!r} is not in SLOT_VOCABULARY")

        if inst.transform_link:
            link = document.links.get(inst.transform_link)
            if link is None:
                warnings.append(f"instance {inst_id!r}: transform_link {inst.transform_link!r} not defined")
            elif inst_id not in link.get("members", []):
                errors.append(
                    f"instance {inst_id!r}: transform_link {inst.transform_link!r} does not list it as a member"
                )

    # transform_link -> member consistency in the other direction
    for link_id, link in document.links.items():
        for member_id in link.get("members", []):
            member = document.instances.get(member_id)
            if member is None:
                errors.append(f"link {link_id!r}: member {member_id!r} is not an instance")
            elif member.transform_link != link_id:
                errors.append(
                    f"link {link_id!r}: member {member_id!r}.transform_link is "
                    f"{member.transform_link!r}, not {link_id!r}"
                )

    # hierarchy integrity (hierarchy.py)
    errors.extend(_hierarchy.validate_hierarchy(document))

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
        active = vs.get("active")
        if active is not None and active not in members:
            errors.append(f"variant_set {vs_id!r}: active {active!r} not in members")

    # rig intent: regions/attachments must target real instances or slots;
    # values are Composer vocabulary, not AutoRig solver settings.
    rig_intent = document.rig_intent or {}
    slot_names = {inst.slot for inst in document.instances.values()}
    semantic_names = {asset.semantic for asset in document.assets.values()}
    valid_targets = instance_ids | slot_names | semantic_names | set(LOGICAL_SURFACES)
    for ref, scope in rig_intent.get("deformation_scopes", {}).items():
        if scope not in DEFORMATION_SCOPES:
            errors.append(
                f"rig_intent.deformation_scopes[{ref!r}]: invalid scope {scope!r}; "
                f"expected one of {DEFORMATION_SCOPES!r}"
            )
        if ref not in valid_targets:
            errors.append(f"rig_intent.deformation_scopes[{ref!r}]: invalid target {ref!r}")
    for region_id, region in rig_intent.get("regions", {}).items():
        target = region.get("target")
        if target is not None and target not in valid_targets:
            errors.append(f"rig_intent.regions[{region_id!r}]: invalid target {target!r}")
        geometry = region.get("geometry", {})
        if geometry.get("kind") not in GEOMETRY_KINDS:
            errors.append(
                f"rig_intent.regions[{region_id!r}]: invalid geometry kind {geometry.get('kind')!r}"
            )
        profile = region.get("response_profile")
        if profile not in RESPONSE_PROFILES:
            errors.append(f"rig_intent.regions[{region_id!r}]: invalid response_profile {profile!r}")
        strength = region.get("author_strength")
        if not isinstance(strength, (int, float)) or not 0 <= strength <= 1:
            errors.append(f"rig_intent.regions[{region_id!r}]: author_strength must be in [0, 1]")
        for lock_name, lock in region.get("locks", {}).items():
            if not isinstance(lock, (int, float)) or not 0 <= lock <= 1:
                errors.append(f"rig_intent.regions[{region_id!r}]: lock {lock_name!r} must be in [0, 1]")
    for attach_id, attach in rig_intent.get("attachments", {}).items():
        for key in ("target", "child"):
            ref = attach.get(key)
            if ref is not None and ref not in valid_targets:
                errors.append(f"rig_intent.attachments[{attach_id!r}]: broken attachment {key} {ref!r}")
        if attach.get("mode") not in ATTACHMENT_MODES:
            errors.append(
                f"rig_intent.attachments[{attach_id!r}]: invalid mode {attach.get('mode')!r}; "
                f"expected one of {ATTACHMENT_MODES!r}"
            )

    # ExpressionPreset is a thin bundle of VariantSet members.  Keep it
    # explicit in the document, but never turn it into a new runtime system.
    for preset_id, preset in getattr(document, "expressions", {}).items():
        for set_id, member in preset.get("variants", {}).items():
            variant_set = document.variant_sets.get(set_id)
            if variant_set is None:
                errors.append(f"expression {preset_id!r}: missing variant_set {set_id!r}")
            elif member not in variant_set.get("members", []):
                errors.append(f"expression {preset_id!r}: {member!r} is not a member of variant_set {set_id!r}")

    return ValidationResult(errors=errors, warnings=warnings)
