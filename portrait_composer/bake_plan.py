"""Logical Bake Plan authoring (C6-A/C6-H foundation).

Creating or analyzing a plan does not create a PNG.  Only ``apply_bake_plan``
delegates to the existing canonical bake implementation.
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import bake as _bake
from .seam_repair import normalize_seam_policy, resolve_bake_mode

PLAN_STATUSES = ("PLANNED", "RIG_CHECKED", "CAN_BAKE", "WARN", "BLOCK", "BAKED")


class BakePlanError(ValueError):
    pass


def _run_authoring(document, operation):
    if document.in_transaction:
        return operation()
    with document.transaction():
        return operation()


def _require_plan(document, plan_id: str) -> dict:
    plan = document.bake_plans.get(plan_id)
    if plan is None:
        raise BakePlanError(f"no such bake plan: {plan_id!r}")
    return plan


def create_bake_plan(
    document,
    plan_id: str,
    *,
    sources: list[str],
    result_semantic: str,
    result_slot: str,
    mode: str | None = None,
    seam_policy: dict | None = None,
) -> dict:
    if not plan_id:
        raise BakePlanError("plan id must be non-empty")
    if not isinstance(sources, list) or not sources or len(set(sources)) != len(sources):
        raise BakePlanError("sources must be a non-empty list of unique instance ids")
    if not result_semantic or not result_slot:
        raise BakePlanError("result_semantic and result_slot must be non-empty")
    try:
        resolved_mode = resolve_bake_mode(result_semantic, mode)
        resolved_policy = normalize_seam_policy(
            seam_policy,
            result_semantic=result_semantic,
            mode=resolved_mode,
        )
    except ValueError as exc:
        raise BakePlanError(str(exc)) from exc

    def mutate():
        if plan_id in document.bake_plans:
            raise BakePlanError(f"bake plan already exists: {plan_id!r}")
        plan = {
            "plan_id": plan_id,
            "sources": list(sources),
            "result_semantic": result_semantic,
            "result_slot": result_slot,
            "mode": resolved_mode,
            "seam_policy": resolved_policy,
            "status": "PLANNED",
        }
        document.bake_plans[plan_id] = plan
        return copy.deepcopy(plan)

    return _run_authoring(document, mutate)


def update_bake_plan(document, plan_id: str, **changes) -> dict:
    allowed = {"sources", "result_semantic", "result_slot", "mode", "seam_policy"}
    unknown = set(changes) - allowed
    if unknown:
        raise BakePlanError(f"unsupported bake plan fields: {sorted(unknown)!r}")

    def mutate():
        current = _require_plan(document, plan_id)
        updated = copy.deepcopy(current)
        updated.update(copy.deepcopy(changes))
        if not isinstance(updated.get("sources"), list) or not updated["sources"]:
            raise BakePlanError("sources must be a non-empty list")
        if len(set(updated["sources"])) != len(updated["sources"]):
            raise BakePlanError("sources must be unique")
        if not updated.get("result_semantic") or not updated.get("result_slot"):
            raise BakePlanError("result_semantic and result_slot must be non-empty")
        try:
            resolved_mode = resolve_bake_mode(updated["result_semantic"], updated.get("mode"))
            updated["mode"] = resolved_mode
            updated["seam_policy"] = normalize_seam_policy(
                updated.get("seam_policy"),
                result_semantic=updated["result_semantic"],
                mode=resolved_mode,
            )
        except ValueError as exc:
            raise BakePlanError(str(exc)) from exc
        updated["status"] = "PLANNED"
        updated["plan_id"] = plan_id
        updated.pop("analysis", None)
        updated.pop("derived_instance_id", None)
        document.bake_plans[plan_id] = updated
        return copy.deepcopy(updated)

    return _run_authoring(document, mutate)


def remove_bake_plan(document, plan_id: str) -> None:
    def mutate():
        if plan_id not in document.bake_plans:
            raise BakePlanError(f"no such bake plan: {plan_id!r}")
        del document.bake_plans[plan_id]

    _run_authoring(document, mutate)


def analyze_bake_plan(document, plan_id: str):
    plan = _require_plan(document, plan_id)
    analysis = _bake.analyze_bake(
        document,
        list(plan["sources"]),
        mode=plan.get("mode"),
        seam_policy=plan.get("seam_policy"),
        result_semantic=plan.get("result_semantic", ""),
    )

    def mutate():
        current = _require_plan(document, plan_id)
        current["status"] = analysis.verdict
        current["analysis"] = analysis.to_dict()
        return analysis

    return _run_authoring(document, mutate)


def apply_bake_plan(document, image_sources: dict, plan_id: str, *, work_dir: Path, profile: str | None = None):
    plan = _require_plan(document, plan_id)
    analysis = _bake.analyze_bake(
        document,
        list(plan["sources"]),
        mode=plan.get("mode"),
        seam_policy=plan.get("seam_policy"),
        result_semantic=plan.get("result_semantic", ""),
    )
    if analysis.verdict == _bake.BLOCK:
        raise _bake.BakeBlockedError(analysis)

    result_holder = {}
    with document.transaction():
        result_holder["result"] = _bake.apply_bake_plan(
            document,
            image_sources,
            list(plan["sources"]),
            derived_id=plan["result_semantic"],
            semantic=plan["result_semantic"],
            slot=plan["result_slot"],
            work_dir=work_dir,
            profile=profile,
            mode=plan.get("mode"),
            seam_policy=plan.get("seam_policy"),
        )
        current = _require_plan(document, plan_id)
        current["status"] = "BAKED"
        current["analysis"] = analysis.to_dict()
        current["derived_instance_id"] = result_holder["result"][0]
    return result_holder["result"]
