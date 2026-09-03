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
    classify_remap,
)

from .conftest import make_portrait_bundle


def _old_document(tmp_path: Path):
    old_root = make_portrait_bundle(tmp_path / "old.portrait")
    bundle = read_portrait_bundle(old_root)
    document, _ = identity_assembly(bundle)
    return document


def test_exact_match_when_layer_id_unchanged(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(tmp_path / "new.portrait")  # identical layer ids
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert report.all_resolved
    statuses = {e.asset_id: e.status for e in report.entries}
    assert statuses == {"body": EXACT_MATCH, "topwear": EXACT_MATCH, "head": EXACT_MATCH}


def test_semantic_match_when_id_renamed_but_unique_semantic(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("body", "body", 10, (255, 0, 0, 255)),
            ("topwear_v2", "torso", 40, (0, 255, 0, 200)),
            ("head", "head", 60, (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert report.all_resolved
    by_id = {e.asset_id: e for e in report.entries}
    assert by_id["topwear"].status == SEMANTIC_MATCH
    assert by_id["topwear"].candidates == ["topwear_v2"]


def test_ambiguous_when_multiple_layers_share_semantic(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("body", "body", 10, (255, 0, 0, 255)),
            ("topwear_a", "torso", 40, (0, 255, 0, 200)),
            ("topwear_b", "torso", 41, (0, 200, 0, 200)),
            ("head", "head", 60, (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)

    report = classify_remap(document, new_bundle)
    assert not report.all_resolved
    by_id = {e.asset_id: e for e in report.entries}
    assert by_id["topwear"].status == AMBIGUOUS
    assert set(by_id["topwear"].candidates) == {"topwear_a", "topwear_b"}


def test_orphaned_when_no_id_or_semantic_match(tmp_path: Path):
    document = _old_document(tmp_path)
    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("body", "body", 10, (255, 0, 0, 255)),
            ("head", "head", 60, (0, 0, 255, 255)),
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
            ("body", "body", 10, (255, 0, 0, 255)),
            ("topwear_a", "torso", 40, (0, 255, 0, 200)),
            ("topwear_b", "torso", 41, (0, 200, 0, 200)),
            ("head", "head", 60, (0, 0, 255, 255)),
        ],
    )
    new_bundle = read_portrait_bundle(new_root)
    report = classify_remap(document, new_bundle)

    old_binding = document.assets["topwear"].source_binding
    apply_auto_resolvable_remap(document, new_bundle, report)

    # AMBIGUOUS entry left untouched
    assert document.assets["topwear"].source_binding is old_binding
    # EXACT_MATCH entries rebound to the new revision
    assert document.assets["body"].source_binding.source_layer_id == "body"
    assert document.assets["body"].source_binding.revision != old_binding.revision

    # manual resolution for the ambiguous one
    apply_manual_remap(document, "topwear", new_bundle, "topwear_b")
    assert document.assets["topwear"].source_binding.source_layer_id == "topwear_b"
    records = document.provenance.for_target("topwear")
    assert records[-1].operation == "remap"
