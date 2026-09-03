"""C1 exit checklist, end to end.

    [x] 서로 다른 3 Portrait Bundle 동시 로드
    [x] asset 단위 source 선택
    [x] provenance에 bundle + seed + layer 보존
    [x] hierarchy reorder
    [x] slot 변경
    [x] transform link 생성/해제
    [x] VariantSet exclusive 동작
    [x] final draw_order 변경
    [x] reference.png deterministic render
    [x] save -> reload -> 동일 document
    [x] undo/redo 전부 통과
    [x] raw_layers harvest 불가 회귀 테스트 (test_harvest.py)
    [x] identity C0/C0.5 회귀 계속 PASS (test_identity_assembly.py, test_portrait_bundle_contract.py)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer import hierarchy as H
from portrait_composer import links as L
from portrait_composer import variants as V
from portrait_composer.assembly import harvest_assembly, instance_id_for, set_draw_order
from portrait_composer.assets import AssetDefinition
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.instances import LayerInstance
from portrait_composer.render import render_reference
from portrait_composer.slots import set_slot

from .conftest import make_portrait_bundle


def _three_runs(tmp_path: Path):
    layers_by_run = {
        "seed_1843": [("neck", (10, 0, 0, 255)), ("topwear", (20, 0, 0, 255)), ("head", (30, 0, 0, 255))],
        "seed_5902": [("neck", (0, 10, 0, 255)), ("topwear", (0, 20, 0, 255)), ("head", (0, 30, 0, 255))],
        "seed_8177": [("neck", (0, 0, 10, 255)), ("topwear", (0, 0, 20, 255)), ("head", (0, 0, 30, 255))],
    }
    return {
        run_label: read_portrait_bundle(
            make_portrait_bundle(tmp_path / f"{run_label}.portrait", source_identity="A001", layers=layers)
        )
        for run_label, layers in layers_by_run.items()
    }


def test_c1_full_pipeline(tmp_path: Path):
    # 3 Portrait Bundles, asset-level source selection
    bundles = _three_runs(tmp_path)
    selections = {"neck": "seed_1843", "topwear": "seed_5902", "head": "seed_8177"}
    document, image_sources, warnings = harvest_assembly(bundles, selections)
    assert warnings == []
    document.mark_saved()

    neck, topwear, head = (instance_id_for(t) for t in ("neck", "topwear", "head"))

    # provenance: bundle + seed + layer preserved per harvested instance
    for inst_id, expected_run in ((neck, "seed_1843"), (topwear, "seed_5902"), (head, "seed_8177")):
        record = document.provenance.for_target(inst_id)[0]
        assert record.extra["run_label"] == expected_run
        assert record.extra["generation"]["source_identity"] == "A001"

    # hierarchy + reorder
    with document.transaction():
        H.add_node(document, "grp_upper", label="Upper Body")
        H.add_node(document, "n_neck", parent="grp_upper", ref=neck)
        H.add_node(document, "n_topwear", parent="grp_upper", ref=topwear)
    with document.transaction():
        H.move_node(document, "n_topwear", new_parent="grp_upper", index=0)
    assert H.children_of(document, "grp_upper") == ["n_topwear", "n_neck"]

    # slot change
    with document.transaction():
        set_slot(document, topwear, "torso_front")
    assert document.instances[topwear].slot == "torso_front"

    # transform link create + release
    with document.transaction():
        L.create_link(document, "upper_link", [neck, topwear])
    assert document.instances[neck].transform_link == "upper_link"
    with document.transaction():
        L.dissolve_link(document, "upper_link")
    assert document.instances[neck].transform_link is None

    # VariantSet exclusive switching (add a second head variant sharing the slot)
    with document.transaction():
        document.add_asset(AssetDefinition(id="head_alt", semantic="head"))
        document.add_instance(
            LayerInstance(id="head_alt__instance", asset_ref="head_alt", slot="head", draw_order=999)
        )
        document.composition["draw_order"].append("head_alt__instance")
    image_sources["head_alt__instance"] = image_sources[head]  # reuse an existing image for the fixture

    with document.transaction():
        V.add_variant_set(document, "head_choice", members=[head, "head_alt__instance"], default=head)
    assert document.instances[head].visible is True
    assert document.instances["head_alt__instance"].visible is False

    with document.transaction():
        V.set_active(document, "head_choice", "head_alt__instance")
    assert document.instances[head].visible is False
    assert document.instances["head_alt__instance"].visible is True

    # final draw_order authoring
    set_draw_order(document, [topwear, neck, head, "head_alt__instance"])
    assert document.composition["draw_order"][:3] == [topwear, neck, head]

    assert document.validate().ok

    # deterministic render: same document -> byte-identical reference.png across calls
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)
    render_a = render_reference(document, out_dir / "layers")
    render_b = render_reference(document, out_dir / "layers")
    assert render_a.tobytes() == render_b.tobytes()
    on_disk = Image.open(out_dir / "reference.png").convert("RGBA")
    assert render_a.tobytes() == on_disk.tobytes()

    # save -> reload -> identical document
    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.to_dict() == document.to_dict()
    assert reloaded.validate().ok
    assert reloaded.hierarchy == document.hierarchy
    assert reloaded.variant_sets == document.variant_sets

    # undo/redo across everything since mark_saved() (harvest itself stays committed)
    while document.dirty:
        document.undo()
    assert not document.dirty
    assert document.hierarchy.get("nodes", {}) == {}
    assert "head_choice" not in document.variant_sets
    assert document.instances[topwear].slot == "topwear"  # slot change undone too

    while document.history.can_redo():
        document.redo()
    assert document.composition["draw_order"][:3] == [topwear, neck, head]
    assert document.instances["head_alt__instance"].visible is True
