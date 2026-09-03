"""C0.5 -- Portrait Bundle v1 contract sync.

Directive: sync Composer's Portrait Bundle reader with the real,
producer-owned contract from `prentice7725/seethrough-portrait`
(schemas/vendor/portrait-bundle-v1.schema.json, docs/PORTRAIT_BUNDLE_V1.md).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from portrait_composer.bundle import BundleError, read_portrait_bundle, source_id_for

from .conftest import make_portrait_bundle

VENDORED_SCHEMA = json.loads(
    Path(__file__).parent.parent.joinpath(
        "schemas", "vendor", "portrait-bundle-v1.schema.json"
    ).read_text(encoding="utf-8")
)


def _manifest(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def test_fixture_conforms_to_the_vendored_upstream_schema(tmp_path: Path):
    """The fixture builder itself must produce schema-valid manifests --
    otherwise every other test here would be validating our reader against
    a contract nobody upstream actually emits."""
    root = make_portrait_bundle(tmp_path / "a.portrait")
    jsonschema.validate(_manifest(root), VENDORED_SCHEMA)


def test_reads_valid_bundle_end_to_end(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait")
    bundle = read_portrait_bundle(root)

    assert bundle.version == "1.0"
    assert [l.tag for l in bundle.layers] == ["neck", "topwear", "head"]
    assert bundle.canvas["width"] == 40 and bundle.canvas["height"] == 40
    assert bundle.warnings == []
    assert source_id_for(bundle) == "A001"
    # draw_order tracks z_order position, strictly increasing in z_order order
    orders = [l.draw_order for l in bundle.layers]
    assert orders == sorted(orders)


def test_rejects_unknown_major_version(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait", version="2.0")
    with pytest.raises(BundleError, match="major version"):
        read_portrait_bundle(root)


def test_rejects_non_production_repaired_canonical_stage(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait", canonical_stage="draft")
    with pytest.raises(BundleError, match="canonical_stage"):
        read_portrait_bundle(root)


@pytest.mark.parametrize(
    "key,value",
    [
        ("coordinate_system", "bottom-left-y-up"),
        ("color_space", "linear"),
        ("alpha", "premultiplied"),
    ],
)
def test_rejects_unsupported_canvas_contract(tmp_path: Path, key, value):
    root = make_portrait_bundle(tmp_path / "a.portrait", canvas_overrides={key: value})
    with pytest.raises(BundleError, match=f"canvas.{key}"):
        read_portrait_bundle(root)


def test_rejects_missing_layer_file(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait")
    (root / "layers" / "topwear.png").unlink()
    with pytest.raises(BundleError, match="file missing"):
        read_portrait_bundle(root)


@pytest.mark.parametrize("tag", ["head_remainder", "neck_remainder"])
def test_rejects_forbidden_rig_specific_layer_tags(tmp_path: Path, tag):
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        layers=[(tag, (10, 10, 10, 255))],
        z_order_override=[tag],
    )
    with pytest.raises(BundleError, match="rig-specific subdivision"):
        read_portrait_bundle(root)


def test_body_remainder_is_a_canonical_tag_not_forbidden(tmp_path: Path):
    """body_remainder is itself canonical (SEMANTIC_Z_ORDER's first entry
    upstream, unresolved semantic-ownership residual) -- the forbidden set
    is an explicit rig-specific denylist, not a '*_remainder' wildcard."""
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        layers=[("body_remainder", (7, 7, 7, 255)), ("head", (4, 5, 6, 255))],
        z_order_override=["body_remainder", "head"],
    )
    bundle = read_portrait_bundle(root)
    assert {l.tag for l in bundle.layers} == {"body_remainder", "head"}


def test_legitimate_left_right_semantic_splits_are_not_forbidden(tmp_path: Path):
    """eyel/eyer etc. are real SEMANTIC_Z_ORDER content splits (two visible
    eyes), not the rig-specific subdivisions the contract bans -- they must
    import cleanly."""
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        layers=[("eyel", (1, 2, 3, 255)), ("eyer", (4, 5, 6, 255))],
        z_order_override=["eyel", "eyer"],
    )
    bundle = read_portrait_bundle(root)
    assert {l.tag for l in bundle.layers} == {"eyel", "eyer"}


def test_rejects_layer_missing_from_z_order(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait", z_order_override=["neck", "head"])
    with pytest.raises(BundleError, match="z_order"):
        read_portrait_bundle(root)


def test_semantic_warnings_are_surfaced_as_import_warnings_not_errors(tmp_path: Path):
    root = make_portrait_bundle(tmp_path / "a.portrait", semantic_warnings=["missing_eyewhite"])
    bundle = read_portrait_bundle(root)
    assert bundle.warnings == ["semantic warning: missing_eyewhite"]


def test_non_pass_validation_status_is_surfaced_as_warning(tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        validation_overrides={"seams": "review", "local_fidelity": "unavailable"},
    )
    bundle = read_portrait_bundle(root)
    assert "validation.seams = 'review'" in bundle.warnings
    assert "validation.local_fidelity = 'unavailable'" in bundle.warnings
    assert not any("static_reconstruction" in w for w in bundle.warnings)  # that one still passes


def test_high_risk_occlusion_edge_is_surfaced_as_warning(tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        occlusion_edges=[
            {"front": "topwear", "back": "neck", "disocclusion_risk": 0.82},
            {"front": "head", "back": "neck", "disocclusion_risk": 0.1},
        ],
    )
    bundle = read_portrait_bundle(root)
    assert bundle.warnings == ["occlusion risk: 'topwear' over 'neck' (disocclusion_risk=0.82)"]


def test_absent_occlusion_graph_produces_no_warning(tmp_path: Path):
    """'not computed' must never be presented as 'no occlusion risk'."""
    root = make_portrait_bundle(tmp_path / "a.portrait")  # no occlusion_edges given
    bundle = read_portrait_bundle(root)
    assert not any("occlusion" in w for w in bundle.warnings)


def test_generation_provenance_is_preserved_verbatim(tmp_path: Path):
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        generation_overrides={"seed_mode": "regression", "seed": 42, "source_identity": None},
    )
    # regression mode doesn't need source_identity; drop the None we injected
    manifest = _manifest(root)
    del manifest["generation"]["source_identity"]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    bundle = read_portrait_bundle(root)
    assert bundle.generation["seed_mode"] == "regression"
    assert bundle.generation["canonical_regression_seed"] == 42
    assert bundle.source_identity is None
