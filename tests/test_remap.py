from __future__ import annotations

from pathlib import Path

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.remap import (
    AMBIGUOUS,
    EXACT_MATCH,
    ORPHANED,
    SEMANTIC_MATCH,
    apply_auto_resolvable_remap,
    apply_manual_remap,
    apply_remap_resolution,
    classify_remap,
)

from .conftest import make_portrait_bundle

BASE_LAYERS = [
    ("neck", (255, 0, 0, 255)),
    ("topwear", (0, 255, 0, 200)),
    ("head", (0, 0, 255, 255)),
]


def _old_document(tmp_path: Path):
    old_root = make_portrait_bundle(tmp_path / "old.portrait", layers=BASE_LAYERS)
    bundle = read_portrait_bundle(old_root)
    document, _, _ = identity_assembly(bundle)
    return document


def test_exact_match_when_tag_unchanged(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(tmp_path / "new.portrait", layers=BASE_LAYERS)
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert report.all_resolved
    statuses = {e.asset_id: e.status for e in report.entries}
    assert statuses == {"neck": EXACT_MATCH, "topwear": EXACT_MATCH, "head": EXACT_MATCH}


def test_semantic_match_when_tag_rekeyed_but_source_tag_still_unique(tmp_path: Path):
    """topwear gets rekeyed to topwear_v2 in the new bundle, but its
    source_tag still records 'topwear' -- exactly the schema-sanctioned
    case SEMANTIC_MATCH exists for (see remap.py's module docstring)."""
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("topwear_v2", (0, 255, 0, 200), "topwear"),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert report.all_resolved
    by_id = {e.asset_id: e for e in report.entries}
    assert by_id["topwear"].status == SEMANTIC_MATCH
    assert by_id["topwear"].candidates == ["topwear_v2"]


def test_ambiguous_when_multiple_new_tags_share_source_tag(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("topwear_a", (0, 255, 0, 200), "topwear"),
            ("topwear_b", (0, 200, 0, 200), "topwear"),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert not report.all_resolved
    by_id = {e.asset_id: e for e in report.entries}
    assert by_id["topwear"].status == AMBIGUOUS
    assert set(by_id["topwear"].candidates) == {"topwear_a", "topwear_b"}


def test_orphaned_when_tag_and_source_tag_both_gone(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert not report.all_resolved
    by_id = {e.asset_id: e for e in report.entries}
    assert by_id["topwear"].status == ORPHANED
    assert by_id["topwear"].candidates == []


def test_apply_auto_resolvable_remap_never_touches_ambiguous(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("topwear_a", (0, 255, 0, 200), "topwear"),
            ("topwear_b", (0, 200, 0, 200), "topwear"),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)
    report = classify_remap(document, new_bundle)

    old_binding = document.assets["topwear"].source_binding
    apply_auto_resolvable_remap(document, new_bundle, report)

    # AMBIGUOUS entry left untouched
    assert document.assets["topwear"].source_binding is old_binding
    # EXACT_MATCH entries rebound to the new revision
    assert document.assets["neck"].source_binding.source_layer_id == "neck"
    assert document.assets["neck"].source_binding.revision != old_binding.revision

    # manual resolution for the ambiguous one
    apply_manual_remap(document, "topwear", new_bundle, "topwear_b")
    assert document.assets["topwear"].source_binding.source_layer_id == "topwear_b"
    records = document.provenance.for_target("topwear")
    assert records[-1].operation == "remap"


def test_apply_remap_resolution_is_atomic_and_preserves_instance_authoring(tmp_path: Path):
    document = _old_document(tmp_path)
    instance = document.instances["topwear__instance"]
    instance.transform.x = 17.0
    instance.visual_ops = [{"id": "tone", "type": "color", "params": {"brightness": 0.8}}]
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("topwear_a", (0, 255, 0, 200), "topwear"),
            ("topwear_b", (0, 200, 0, 200), "topwear"),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)
    report = classify_remap(document, new_bundle)

    apply_remap_resolution(document, new_bundle, report, {"topwear": "topwear_b"})
    assert document.assets["topwear"].source_binding.source_layer_id == "topwear_b"
    assert document.instances["topwear__instance"].transform.x == 17.0
    assert document.instances["topwear__instance"].visual_ops[0]["id"] == "tone"
    assert document.remap_review["status"] == "RESOLVED"

    document.undo()
    assert document.assets["topwear"].source_binding.source_layer_id == "topwear"
    assert document.instances["topwear__instance"].transform.x == 17.0


def test_partial_remap_resolution_is_persisted_and_blocks_rig_export(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("neck", (255, 0, 0, 255)),
            ("topwear_a", (0, 255, 0, 200), "topwear"),
            ("topwear_b", (0, 200, 0, 200), "topwear"),
            ("head", (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)
    report = classify_remap(document, new_bundle)

    apply_remap_resolution(document, new_bundle, report, {})
    assert document.remap_review["status"] == "REVIEW_REQUIRED"
    assert document.remap_review["unresolved_assets"] == ["topwear"]

    restored = type(document).from_dict(document.to_dict())
    assert restored.remap_review == document.remap_review

    from portrait_composer.rig_bundle import validate_rig_export

    assert any("source remap review is unresolved" in error for error in validate_rig_export(document, {}))
