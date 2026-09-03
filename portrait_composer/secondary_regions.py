"""Authorable secondary-motion regions (C4).

This module stores region geometry and qualitative response intent.  Numeric
stiffness/damping and all deformation safety remain AutoRig responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument

UPPER_TORSO_SECONDARY = "upper_torso_secondary"
RESPONSE_PROFILES = ("soft", "firm_bounce", "springy")
GEOMETRY_KINDS = ("two_lobe",)
PREFLIGHT_READY = "READY"
PREFLIGHT_DEGRADED = "DEGRADED"
PREFLIGHT_DISABLED = "DISABLED"


class SecondaryRegionError(ValueError):
    pass


def _run_authoring(document: "AssemblyDocument", operation):
    """Commit one public edit, while composing cleanly inside outer edits."""
    if document.in_transaction:
        return operation()
    with document.transaction():
        return operation()


def default_two_lobe_geometry() -> dict:
    """Return the deterministic normalized starter geometry from the directive."""
    return {
        "kind": "two_lobe",
        "left": {"center": [0.39, 0.36], "radius": [0.24, 0.20]},
        "right": {"center": [0.61, 0.36], "radius": [0.24, 0.20]},
    }


def _normalise_geometry(geometry: dict | None) -> dict:
    if geometry is None:
        return default_two_lobe_geometry()
    result = dict(geometry)
    if result.get("kind") not in GEOMETRY_KINDS:
        raise SecondaryRegionError(f"unknown secondary geometry kind {result.get('kind')!r}")
    for side in ("left", "right"):
        lobe = result.get(side)
        if not isinstance(lobe, dict) or len(lobe.get("center", [])) != 2 or len(lobe.get("radius", [])) != 2:
            raise SecondaryRegionError(f"two_lobe geometry requires {side}.center and {side}.radius")
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (*lobe["center"], *lobe["radius"])):
            raise SecondaryRegionError(f"two_lobe {side} geometry must contain finite numbers")
        if any(v <= 0 for v in lobe["radius"]):
            raise SecondaryRegionError(f"two_lobe {side}.radius must be positive")
    return result


def _normalise_locks(locks: dict | None) -> dict:
    result = {"center": 0.10, "neckline": 0.16, "shoulder": 0.08}
    if locks:
        result.update(locks)
    for key, value in result.items():
        if not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
            raise SecondaryRegionError(f"lock {key!r} must be a number in [0, 1]")
    return result


def make_region(
    *,
    target: str,
    geometry: dict | None = None,
    locks: dict | None = None,
    exclusions: list | None = None,
    author_strength: float = 0.9,
    response_profile: str = "soft",
    enabled: bool = True,
) -> dict:
    if not target:
        raise SecondaryRegionError("secondary region target must be non-empty")
    if response_profile not in RESPONSE_PROFILES:
        raise SecondaryRegionError(f"unknown response_profile {response_profile!r}; expected {RESPONSE_PROFILES!r}")
    if not isinstance(author_strength, (int, float)) or not isfinite(author_strength) or not 0 <= author_strength <= 1:
        raise SecondaryRegionError("author_strength must be a number in [0, 1]")
    return {
        "target": target,
        "geometry": _normalise_geometry(geometry),
        "locks": _normalise_locks(locks),
        "exclusions": list(exclusions or []),
        "author_strength": float(author_strength),
        "response_profile": response_profile,
        "enabled": bool(enabled),
    }


def add_region(
    document: "AssemblyDocument",
    region_id: str,
    *,
    target: str,
    geometry: dict | None = None,
    locks: dict | None = None,
    exclusions: list | None = None,
    author_strength: float = 0.9,
    response_profile: str = "soft",
    enabled: bool = True,
) -> dict:
    """Add an authored region to ``document.rig_intent``."""
    if not region_id:
        raise SecondaryRegionError("region id must be non-empty")
    region = make_region(
        target=target, geometry=geometry, locks=locks, exclusions=exclusions,
        author_strength=author_strength, response_profile=response_profile, enabled=enabled,
    )
    def mutate():
        intent = document.rig_intent
        intent.setdefault("regions", {})
        if region_id in intent["regions"]:
            raise SecondaryRegionError(f"secondary region id already exists: {region_id!r}")
        intent["regions"][region_id] = region
    _run_authoring(document, mutate)
    return region


def add_upper_torso_secondary(
    document: "AssemblyDocument",
    *,
    target: str,
    region_id: str = UPPER_TORSO_SECONDARY,
    response_profile: str = "soft",
    author_strength: float = 0.9,
    geometry: dict | None = None,
    locks: dict | None = None,
    exclusions: list | None = None,
) -> dict:
    """Add the canonical region with deterministic ``two_lobe`` geometry."""
    return add_region(
        document, region_id, target=target, geometry=geometry, locks=locks,
        exclusions=exclusions, author_strength=author_strength,
        response_profile=response_profile,
    )


def update_region(document: "AssemblyDocument", region_id: str, **changes: Any) -> dict:
    if region_id not in document.rig_intent.get("regions", {}):
        raise SecondaryRegionError(f"no such secondary region: {region_id!r}")
    def mutate():
        regions = document.rig_intent["regions"]
        current = dict(regions[region_id])
        current.update(changes)
        updated = make_region(
            target=current["target"], geometry=current.get("geometry"), locks=current.get("locks"),
            exclusions=current.get("exclusions"), author_strength=current.get("author_strength", 0.9),
            response_profile=current.get("response_profile", "soft"), enabled=current.get("enabled", True),
        )
        # Preserve optional authoring diagnostics/metadata such as explicit
        # neckline intrusion or overlay coverage when only geometry is edited.
        known = {"target", "geometry", "locks", "exclusions", "author_strength", "response_profile", "enabled"}
        updated = {**{k: v for k, v in current.items() if k not in known}, **updated}
        regions[region_id] = updated
        return updated
    return _run_authoring(document, mutate)


def set_geometry(document: "AssemblyDocument", region_id: str, geometry: dict) -> dict:
    return update_region(document, region_id, geometry=geometry)


def remove_region(document: "AssemblyDocument", region_id: str) -> None:
    if region_id not in document.rig_intent.get("regions", {}):
        raise SecondaryRegionError(f"no such secondary region: {region_id!r}")
    _run_authoring(document, lambda: document.rig_intent["regions"].__delitem__(region_id))


@dataclass
class PreflightReport:
    status: str
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status, "reasons": list(self.reasons), "checks": dict(self.checks)}

    @property
    def ok(self) -> bool:
        return self.status == PREFLIGHT_READY


def _target_instances(document: "AssemblyDocument", target: str) -> list:
    if target in document.instances:
        return [document.instances[target]]
    if target == "topwear_with_arms":
        return [i for i in document.instances.values() if i.slot in {"torso_back", "torso", "torso_front"}]
    return [i for i in document.instances.values() if i.slot == target or document.assets.get(i.asset_ref, None) and document.assets[i.asset_ref].semantic == target]


def _geometry_bounds(geometry: dict) -> tuple[float, float, float, float]:
    points = []
    for side in ("left", "right"):
        lobe = geometry[side]
        cx, cy = lobe["center"]
        rx, ry = lobe["radius"]
        points.extend([(cx - rx, cy - ry), (cx + rx, cy + ry)])
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def visual_preflight(document: "AssemblyDocument", region_id: str = UPPER_TORSO_SECONDARY) -> PreflightReport:
    """Run Composer-owned checks only; mesh stretch/inversion is AutoRig QA."""
    region = (document.rig_intent or {}).get("regions", {}).get(region_id)
    if region is None:
        return PreflightReport(PREFLIGHT_DISABLED, [f"region {region_id!r} does not exist"], {"target_exists": False})

    reasons: list[str] = []
    checks: dict[str, Any] = {}
    target = region.get("target")
    target_instances = _target_instances(document, target)
    checks["target_exists"] = bool(target_instances)
    if not target_instances:
        return PreflightReport(PREFLIGHT_DISABLED, [f"target {target!r} does not exist"], checks)

    visible = any(i.visible and i.opacity > 0 for i in target_instances)
    checks["target_visible"] = visible
    if not visible:
        reasons.append("target instance is not visible")

    scopes = (document.rig_intent or {}).get("deformation_scopes", {})
    target_refs = {target, *(i.id for i in target_instances), *(i.slot for i in target_instances)}
    target_scopes = {ref: scopes[ref] for ref in target_refs if ref in scopes}
    checks["deformation_scopes"] = dict(target_scopes)
    if any(scope in {"baked", "rigid"} for scope in target_scopes.values()):
        reasons.append("secondary region conflicts with baked/rigid deformation_scope")
    if not target_scopes:
        reasons.append("target deformation_scope is not authored")

    try:
        geometry = _normalise_geometry(region.get("geometry"))
        bounds = _geometry_bounds(geometry)
        checks["geometry_in_target"] = all(0 <= value <= 1 for value in bounds)
        if not checks["geometry_in_target"]:
            reasons.append("region geometry extends outside normalized target bounds")
    except SecondaryRegionError as exc:
        checks["geometry_in_target"] = False
        reasons.append(str(exc))

    locks = region.get("locks", {})
    checks["locks_valid"] = all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in locks.values())
    if not checks["locks_valid"]:
        reasons.append("one or more region locks are invalid")

    # Explicit authoring metadata is preferred.  The deterministic slot scan
    # is only a conservative warning signal, never a body-shape heuristic.
    coverage = region.get("overlay_coverage")
    if coverage is None:
        coverage = region.get("occlusion", {}).get("overlay_coverage") if isinstance(region.get("occlusion"), dict) else None
    if isinstance(coverage, (int, float)) and coverage >= 0.75:
        checks["overlay_coverage"] = coverage
        reasons.append("hand/accessory overlay covers most of the target region")
    if region.get("neckline_intrusion"):
        checks["neckline_intrusion"] = True
        reasons.append("region intrudes into the neckline")
    if region.get("center_lock_valid") is False:
        checks["center_lock_valid"] = False
        reasons.append("center lock is invalid")
    if region.get("shoulder_lock_valid") is False:
        checks["shoulder_lock_valid"] = False
        reasons.append("shoulder lock is invalid")
    attachments = (document.rig_intent or {}).get("attachments", {})
    conflicting = [aid for aid, a in attachments.items() if target in {a.get("child"), a.get("target")} and a.get("mode") in {"free", "hinge"}]
    checks["attachment_conflicts"] = conflicting
    if conflicting:
        reasons.append(f"attachment relationship conflicts with secondary region: {conflicting!r}")

    if not region.get("enabled", True) or not visible:
        status = PREFLIGHT_DISABLED
    elif not checks.get("geometry_in_target") or not checks.get("locks_valid") or any("conflicts" in r for r in reasons):
        status = PREFLIGHT_DISABLED
    elif reasons:
        status = PREFLIGHT_DEGRADED
    else:
        status = PREFLIGHT_READY
    return PreflightReport(status, reasons, checks)


preflight_region = visual_preflight
create_upper_torso_secondary = add_upper_torso_secondary
create_region = add_region
author_secondary_region = add_region
edit_region = update_region
