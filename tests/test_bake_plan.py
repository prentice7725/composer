from __future__ import annotations

from pathlib import Path

from portrait_composer.assembly import identity_assembly
from portrait_composer.bake_plan import analyze_bake_plan, apply_bake_plan, create_bake_plan, remove_bake_plan
from portrait_composer.bundle import read_portrait_bundle

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    return identity_assembly(bundle)


def test_bake_plan_is_a_serialized_logical_recipe_and_undoable(tmp_path: Path):
    document, _, _ = _doc(tmp_path)
    plan = create_bake_plan(
        document,
        "torso_plan",
        sources=["neck__instance", "topwear__instance"],
        result_semantic="neck_topwear",
        result_slot="torso",
    )
    assert plan["status"] == "PLANNED"
    assert document.to_dict()["bake_plans"]["torso_plan"] == plan

    analysis = analyze_bake_plan(document, "torso_plan")
    assert analysis.verdict == "WARN"
    assert document.bake_plans["torso_plan"]["status"] == "WARN"

    reloaded = type(document).from_dict(document.to_dict())
    assert reloaded.bake_plans == document.bake_plans

    document.undo()
    assert document.bake_plans["torso_plan"]["status"] == "PLANNED"
    document.undo()
    assert document.bake_plans == {}


def test_bake_plan_apply_is_one_history_step_and_marks_baked(tmp_path: Path):
    document, image_sources, _ = _doc(tmp_path)
    plan_id = "torso_plan"
    create_bake_plan(
        document,
        plan_id,
        sources=["neck__instance", "topwear__instance"],
        result_semantic="neck_topwear",
        result_slot="torso",
    )
    before_apply = document.to_dict()
    derived_id, _ = apply_bake_plan(
        document,
        image_sources,
        plan_id,
        work_dir=tmp_path / "work",
    )

    assert document.bake_plans[plan_id]["status"] == "BAKED"
    assert document.bake_plans[plan_id]["derived_instance_id"] == derived_id
    assert derived_id in document.instances

    document.undo()
    assert document.to_dict() == before_apply
    document.redo()
    assert document.bake_plans[plan_id]["status"] == "BAKED"


def test_remove_bake_plan_is_transactional(tmp_path: Path):
    document, _, _ = _doc(tmp_path)
    create_bake_plan(document, "p", sources=["neck__instance", "topwear__instance"], result_semantic="x", result_slot="torso")
    remove_bake_plan(document, "p")
    assert document.bake_plans == {}
    document.undo()
    assert "p" in document.bake_plans

