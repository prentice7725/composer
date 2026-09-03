"""Guards the committed static fixtures under tests/fixtures/portrait_bundles/
against reader bit-rot: these are checked-in bundles (not generated fresh
per test into tmp_path), so a future bundle.py change that breaks real
Portrait Bundle v1 input shows up here even if every tmp_path-based test
happens to only exercise the shapes that change was written against.
"""
from __future__ import annotations

from pathlib import Path

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle, source_id_for

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "portrait_bundles"


def test_regression_seed_mode_fixture_imports_cleanly():
    bundle = read_portrait_bundle(FIXTURES_DIR / "sample_regression.portrait")
    assert bundle.generation["seed_mode"] == "regression"
    assert bundle.generation["canonical_regression_seed"] == 42

    document, image_sources, warnings = identity_assembly(bundle)
    assert warnings == []
    assert document.validate().ok
    assert set(document.assets) == {"neck", "topwear", "head"}


def test_deterministic_auto_fixture_surfaces_warnings_and_skips_raw_layers():
    bundle = read_portrait_bundle(FIXTURES_DIR / "sample_deterministic_auto.portrait")
    assert bundle.generation["seed_mode"] == "deterministic_auto"
    assert source_id_for(bundle) == "A001"

    document, image_sources, warnings = identity_assembly(bundle)
    assert "semantic warning: missing_eyewhite" in warnings
    assert any("occlusion risk" in w for w in warnings)
    assert "eyewhite" not in document.assets
    assert not any("raw_layers" in str(p) for p in image_sources.values())
