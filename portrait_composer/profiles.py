"""Export profiles (C2).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #18.

A profile is a bake *policy*, not a separate renderer or code path:

    same AssemblyDocument
          |
      profile policy
          |
    recommended / allowed bake plan

``analyze_profile`` only *recommends* candidates -- each is its own
``bake.BakeAnalysis`` (CAN_BAKE/WARN/BLOCK), exactly as if a caller had
picked that instance grouping by hand and called ``bake.analyze_bake``
directly. Nothing here auto-applies a bake; that's the point of splitting
analyze from apply (so a caller -- CLI, GUI, or an MCP tool -- can say
"analyze under PORTRAIT_RIG, apply whatever isn't BLOCKed").

- **PORTRAIT_STATIC**: maximum safe bake -- everything not needed for
  variant switching, merged into one static composite.
- **PORTRAIT_RIG**: NPC baseline -- head/face/hair/expression slots stay
  independent; the torso-system slots (torso_back/torso/torso_front) are
  grouped into one bake candidate when there's more than one of them and
  no RigIntent marks any of them independent (e.g. a uniform's sleeve/arm/
  handwear planes/instances sharing those slots become one
  "topwear_with_arms"-style surface -- directive #18, #27's example).
- **FULL_MOTION**: recommends nothing (deliberately -- "arm/hand/sleeve
  독립 유지 우선. Bake는 아주 보수적으로"). Call ``bake.analyze_bake``
  directly for a manual grouping if you actually want one under this
  profile.

PORTRAIT_RIG's torso grouping leaves a single deformable surface available
for upper_torso_secondary; it makes no motion decision itself. C4's region
authoring can declare the resulting logical surface's RigIntent separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from . import bake as _bake
from .rig_intent import is_rig_protected_semantic

if TYPE_CHECKING:
    from .document import AssemblyDocument

PORTRAIT_STATIC = "PORTRAIT_STATIC"
PORTRAIT_RIG = "PORTRAIT_RIG"
FULL_MOTION = "FULL_MOTION"

# slots that stay independent under PORTRAIT_RIG (head/face/hair/expression
# machinery) -- directive #18: "head/face/hair expression" kept, never baked
# away by this policy.
_RIG_KEPT_INDEPENDENT_SLOTS = {
    "head", "face", "eye", "mouth", "hair_front", "hair_back", "headwear", "neck",
}
_RIG_TORSO_SLOTS = {"torso_back", "torso", "torso_front"}


class ProfileError(Exception):
    pass


@dataclass
class BakeCandidate:
    label: str
    instance_ids: list
    analysis: "_bake.BakeAnalysis"

    def to_dict(self) -> dict:
        return {"label": self.label, "instance_ids": list(self.instance_ids), "analysis": self.analysis.to_dict()}


def _variant_member_ids(document: "AssemblyDocument") -> set:
    members: set = set()
    for vs in document.variant_sets.values():
        members.update(vs.get("members", []))
    return members


def _candidate(document: "AssemblyDocument", label: str, instance_ids: list) -> Optional[BakeCandidate]:
    if len(instance_ids) < 2:
        return None
    analysis = _bake.analyze_bake(document, instance_ids)
    return BakeCandidate(label=label, instance_ids=instance_ids, analysis=analysis)


def _analyze_static(document: "AssemblyDocument") -> list:
    protected = _variant_member_ids(document)
    eligible = [
        inst_id
        for inst_id, inst in document.instances.items()
        if inst.visible and inst_id not in protected
    ]
    eligible.sort(key=lambda i: document.instances[i].draw_order)
    candidate = _candidate(document, "static_composite", eligible)
    return [candidate] if candidate else []


def _analyze_rig(document: "AssemblyDocument") -> list:
    protected = _variant_member_ids(document)
    torso_ids = [
        inst_id
        for inst_id, inst in document.instances.items()
        if (
            inst.visible
            and inst.slot in _RIG_TORSO_SLOTS
            and inst_id not in protected
            and not is_rig_protected_semantic(document.assets[inst.asset_ref].semantic)
        )
    ]
    torso_ids.sort(key=lambda i: document.instances[i].draw_order)
    candidate = _candidate(document, "topwear_with_arms", torso_ids)
    return [candidate] if candidate else []


def _analyze_full_motion(document: "AssemblyDocument") -> list:
    return []


_ANALYZERS = {
    PORTRAIT_STATIC: _analyze_static,
    PORTRAIT_RIG: _analyze_rig,
    FULL_MOTION: _analyze_full_motion,
}


def analyze_profile(document: "AssemblyDocument", profile: str) -> list:
    """Returns a list of BakeCandidate, each carrying its own dry-run
    BakeAnalysis. Never mutates the document."""
    analyzer = _ANALYZERS.get(profile)
    if analyzer is None:
        raise ProfileError(f"unknown profile: {profile!r} (expected one of {list(_ANALYZERS)!r})")
    return analyzer(document)


def apply_candidate(
    document: "AssemblyDocument",
    image_sources: dict,
    candidate: BakeCandidate,
    *,
    derived_id: str,
    semantic: str,
    work_dir: Path,
    profile: Optional[str] = None,
    ordered_instance_ids: Optional[list] = None,
    transform_overrides: Optional[dict] = None,
    mode: str | None = None,
    seam_policy: dict | None = None,
) -> tuple:
    """Thin wrapper over bake.apply_bake_plan for one analyzed candidate.
    ``profile`` is stored verbatim in the derived asset's provenance --
    pass the PORTRAIT_STATIC/PORTRAIT_RIG/FULL_MOTION constant that
    produced this candidate; left as None (not defaulted to the
    candidate's label) if the caller doesn't want to claim one."""
    return _bake.apply_bake_plan(
        document,
        image_sources,
        candidate.instance_ids,
        derived_id=derived_id,
        semantic=semantic,
        work_dir=work_dir,
        profile=profile,
        ordered_instance_ids=ordered_instance_ids,
        transform_overrides=transform_overrides,
        mode=mode,
        seam_policy=seam_policy,
    )


def apply_non_blocking_candidates(
    document: "AssemblyDocument",
    image_sources: dict,
    candidates: list,
    *,
    work_dir: Path,
    profile: Optional[str] = None,
) -> list:
    """"BLOCK 없는 것만 자동 적용": applies every candidate whose own
    dry-run analysis isn't BLOCK, skipping BLOCKed ones. Each application
    is its own transaction (bake.apply_bake_plan), so one candidate
    failing to apply never touches another. Returns a list of
    ``{"label", "applied", "derived_instance_id", "warnings"}`` (or
    ``"skipped": "BLOCK"`` for the ones left out)."""
    results = []
    for candidate in candidates:
        if candidate.analysis.verdict == _bake.BLOCK:
            results.append({"label": candidate.label, "applied": False, "skipped": "BLOCK"})
            continue
        derived_inst_id, warnings = apply_candidate(
            document,
            image_sources,
            candidate,
            derived_id=candidate.label,
            semantic=candidate.label,
            work_dir=work_dir,
            profile=profile,
        )
        results.append(
            {"label": candidate.label, "applied": True, "derived_instance_id": derived_inst_id, "warnings": warnings}
        )
    return results
