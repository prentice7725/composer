"""Bake / Merge (C2).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #16-17.

Bake is not a destructive source edit (#16):

    source AssetDefinitions / LayerInstances
              |
             bake
              |
    derived AssetDefinition + derived LayerInstance + provenance chain

The sources stay in the document exactly as they were -- ``apply_bake_plan``
only hides them (``visible = False``) and removes them from
``composition.draw_order``, both inside the same transaction as everything
else it does, so ``document.undo()`` restores the pre-bake document exactly
(instances still fully present and re-showable, not deleted).

Every real bake must go through ``analyze_bake`` first (dry-run, #17):

    CAN_BAKE / WARN / BLOCK

``apply_bake_plan`` refuses to run on a BLOCK verdict. A WARN verdict is
returned to the caller (not swallowed) but does not block.

RigIntent is C4, not implemented yet (rig_intent.py is a stub) -- when
``document.rig_intent`` carries data, this module inspects it; when it's
empty, that is surfaced as a WARN ("can't verify"), never silently treated
as "no conflict, safe to bake" -- see ``_rig_intent_reasons``.

Known gap: occlusion-risk data (bundle.py's ``diagnostics/occlusion_graph.json``
surfacing) is only ever returned as transient import warnings from
``identity_assembly``/``harvest_assembly`` -- it isn't persisted onto the
document, so bake-time can't check it yet. Not faked here; wire it in once
occlusion diagnostics are persisted per-instance.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .assets import AssetDefinition
from .instances import LayerInstance, Transform
from .render import render_subset

if TYPE_CHECKING:
    from .document import AssemblyDocument

CAN_BAKE = "CAN_BAKE"
WARN = "WARN"
BLOCK = "BLOCK"

BAKE_VERSION = "1.0"


class BakeError(Exception):
    pass


class BakeBlockedError(BakeError):
    def __init__(self, analysis: "BakeAnalysis"):
        self.analysis = analysis
        super().__init__("; ".join(analysis.reasons) or "bake blocked")


@dataclass
class BakeAnalysis:
    verdict: str
    reasons: list = field(default_factory=list)  # each prefixed "BLOCK: " or "WARN: "
    instance_ids: list = field(default_factory=list)

    @property
    def block_reasons(self) -> list:
        return [r for r in self.reasons if r.startswith("BLOCK: ")]

    @property
    def warn_reasons(self) -> list:
        return [r for r in self.reasons if r.startswith("WARN: ")]

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": list(self.reasons), "instance_ids": list(self.instance_ids)}


def _rig_intent_reasons(document: "AssemblyDocument", instance_ids: list) -> list:
    """RigIntent is C4-empty today. Absence is never read as 'safe' -- it's
    surfaced as a WARN so a caller knows the check couldn't actually run."""
    reasons = []
    rig_intent = document.rig_intent or {}
    scopes = rig_intent.get("deformation_scopes", {})
    attachments = rig_intent.get("attachments", {})
    slot_names = {document.instances[i].slot for i in instance_ids if i in document.instances}

    checked_any = False
    for ref, scope in scopes.items():
        if ref in instance_ids or ref in slot_names:
            checked_any = True
            if scope == "independent":
                reasons.append(
                    f"BLOCK: instance/slot {ref!r} has an independent RigIntent deformation_scope; "
                    "bake would remove that independence"
                )

    for attach_id, attach in attachments.items():
        for key in ("target", "child"):
            ref = attach.get(key)
            if ref in instance_ids or ref in slot_names:
                checked_any = True
                reasons.append(
                    f"BLOCK: attachment {attach_id!r} references {ref!r} ({key}); "
                    "bake would break that attachment relationship"
                )

    if not checked_any:
        reasons.append(
            "WARN: no RigIntent authored yet for these instances -- independent-motion/attachment "
            "conflicts cannot be verified (absence is not treated as 'safe')"
        )
    return reasons


def analyze_bake(document: "AssemblyDocument", instance_ids: list) -> BakeAnalysis:
    """Dry-run bake analysis (directive #17). Never mutates the document."""
    reasons: list[str] = []
    instance_ids = list(instance_ids)

    if len(instance_ids) < 2:
        reasons.append("BLOCK: bake needs at least 2 source instances")

    missing = [i for i in instance_ids if i not in document.instances]
    if missing:
        reasons.append(f"BLOCK: unknown instance(s): {missing!r}")
        return BakeAnalysis(verdict=BLOCK, reasons=reasons, instance_ids=instance_ids)

    # canvas: a bake target needs a defined, single canvas to composite into
    canvas = document.composition.get("canvas") or {}
    if not canvas.get("width") or not canvas.get("height"):
        reasons.append("BLOCK: document.composition.canvas is not set")

    # unresolved source binding
    for inst_id in instance_ids:
        asset = document.assets.get(document.instances[inst_id].asset_ref)
        if asset is None:
            reasons.append(f"BLOCK: instance {inst_id!r}: missing asset {document.instances[inst_id].asset_ref!r}")
        elif asset.source_binding is None:
            reasons.append(f"BLOCK: instance {inst_id!r}: asset {asset.id!r} has an unresolved source binding")

    # incompatible VariantSet members -- baking would remove independent switching
    for vs_id, vs in document.variant_sets.items():
        members = set(vs.get("members", []))
        hit = members & set(instance_ids)
        for inst_id in sorted(hit):
            reasons.append(
                f"BLOCK: instance {inst_id!r} is a member of variant_set {vs_id!r}; "
                "baking would remove its independent switching"
            )

    # RigIntent: check what exists, warn about what can't be verified
    reasons.extend(_rig_intent_reasons(document, instance_ids))

    # transform_link dissolution
    linked = [i for i in instance_ids if document.instances[i].transform_link]
    if linked:
        reasons.append(
            f"WARN: transform_link(s) on {linked!r} will be dissolved by bake, losing coordinated movement"
        )

    # provenance spans multiple sources/seeds
    source_ids = set()
    for inst_id in instance_ids:
        asset = document.assets.get(document.instances[inst_id].asset_ref)
        if asset and asset.source_binding:
            source_ids.add(asset.source_binding.source_id)
    if len(source_ids) > 1:
        reasons.append(f"WARN: sources span multiple bundles/seeds: {sorted(source_ids)!r}")

    if any(r.startswith("BLOCK: ") for r in reasons):
        verdict = BLOCK
    elif any(r.startswith("WARN: ") for r in reasons):
        verdict = WARN
    else:
        verdict = CAN_BAKE

    return BakeAnalysis(verdict=verdict, reasons=reasons, instance_ids=instance_ids)


def apply_bake_plan(
    document: "AssemblyDocument",
    image_sources: dict,
    instance_ids: list,
    *,
    derived_id: str,
    semantic: str,
    work_dir: Path,
    slot: Optional[str] = None,
    profile: Optional[str] = None,
) -> tuple:
    """Bakes ``instance_ids`` into one derived AssetDefinition + LayerInstance.

    Refuses to run (raises ``BakeBlockedError``) on a BLOCK dry-run verdict.
    Returns ``(derived_instance_id, warnings)`` -- WARN-level dry-run
    reasons are returned, never silently dropped.

    ``work_dir`` is a scratch directory this writes
    ``<derived_id>__instance.png`` into; ``image_sources`` (an ordinary
    dict, not part of the document/transaction) is updated to point the
    new instance id at that file, the same convention
    identity_assembly/harvest_assembly use.
    """
    analysis = analyze_bake(document, instance_ids)
    if analysis.verdict == BLOCK:
        raise BakeBlockedError(analysis)

    instance_ids = list(instance_ids)
    draw_order = document.composition.get("draw_order", [])
    ordered_ids = [i for i in draw_order if i in instance_ids] or instance_ids

    composite = render_subset(document, image_sources, ordered_ids)

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    derived_inst_id = f"{derived_id}__instance"
    image_path = work_dir / f"{derived_inst_id}.png"
    composite.save(image_path)

    sources_detail = []
    for inst_id in ordered_ids:
        inst = document.instances[inst_id]
        asset = document.assets.get(inst.asset_ref)
        sources_detail.append(
            {
                "instance": inst_id,
                "asset": inst.asset_ref,
                "source_bundle": asset.source_binding.source_id if asset and asset.source_binding else None,
            }
        )

    anchor_draw_order = min(document.instances[i].draw_order for i in instance_ids)
    anchor_slot = slot or document.instances[ordered_ids[0]].slot

    with document.transaction():
        derived_asset = AssetDefinition(
            id=derived_id,
            semantic=semantic,
            source_binding=None,  # derived assets have a provenance chain instead of one upstream binding
            planes=[semantic],
            provenance={
                "derived_from": sources_detail,
                "operation": "alpha_composite",
                "profile": profile,
                "timestamp": time.time(),
                "version": BAKE_VERSION,
            },
        )
        document.add_asset(derived_asset)

        derived_instance = LayerInstance(
            id=derived_inst_id,
            asset_ref=derived_id,
            slot=anchor_slot,
            draw_order=anchor_draw_order,
            transform=Transform(),
        )
        document.add_instance(derived_instance)

        for inst_id in instance_ids:
            document.instances[inst_id].visible = False

        new_order = [i for i in draw_order if i not in instance_ids]
        insert_at = min(
            (draw_order.index(i) for i in ordered_ids if i in draw_order), default=len(new_order)
        )
        # position among survivors: count how many removed instances preceded this point
        removed_before = sum(1 for i in draw_order[:insert_at] if i in instance_ids)
        insert_position = insert_at - removed_before
        new_order.insert(insert_position, derived_inst_id)
        document.composition["draw_order"] = new_order

        for target_id in (derived_inst_id, derived_id):
            document.provenance.record(
                target_id,
                operation="bake",
                sources=list(instance_ids),
                detail=sources_detail,
                profile=profile,
            )

    image_sources[derived_inst_id] = image_path
    return derived_inst_id, analysis.warn_reasons
