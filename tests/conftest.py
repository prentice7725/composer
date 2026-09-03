"""Portrait Bundle v1 fixture builder.

These fixtures are hand-built directly against the real, producer-owned
contract vendored at schemas/vendor/portrait-bundle-v1.schema.json /
docs/PORTRAIT_BUNDLE_V1.md (from `prentice7725/seethrough-portrait`,
pinned commit in schemas/vendor/README.md), cross-checked field-by-field
against that repo's own exporter (`seethrough_engine/export.py`) and its
test fixture (`tests/unit/seethrough_engine/test_bundle.py::result_fixture`).
They are not produced by running the real pipeline (which needs
diffusers/torch/opencv and a real portrait image) -- `test_schema_conformance`
below at least keeps them honest against the vendored JSON Schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

DEFAULT_LAYERS = (
    # (tag, RGBA color) -- "neck" < "topwear" < "head" in the real
    # producer's SEMANTIC_Z_ORDER, so this is also z_order order.
    ("neck", (255, 0, 0, 255)),
    ("topwear", (0, 255, 0, 200)),
    ("head", (0, 0, 255, 255)),
)


def make_portrait_bundle(
    root: Path,
    *,
    size=(40, 40),
    layers=DEFAULT_LAYERS,
    source_identity="A001",
    generation_overrides: dict | None = None,
    validation_overrides: dict | None = None,
    semantic_warnings: list | None = None,
    z_order_override: list | None = None,
    raw_layers: dict | None = None,
    occlusion_edges: list | None = None,
    canonical_stage="production_repaired",
    version="1.0",
    canvas_overrides: dict | None = None,
) -> Path:
    """Writes a Portrait Bundle v1 to ``root`` and returns ``root``.

    ``layers``: sequence of (tag, RGBA color) written to layers/<tag>.png.
    ``raw_layers``: optional {tag: RGBA color} written to raw_layers/<tag>.png
    -- forensic only; a tag here that ISN'T also in ``layers`` (e.g. an
    eyewhite candidate the producer's recovery ladder rejected) is exactly
    the case Composer must never fall back to.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "layers").mkdir(exist_ok=True)

    Image.new("RGBA", size, (128, 128, 128, 255)).save(root / "original.png")

    # each entry is (tag, color) or (tag, color, source_tag) -- source_tag
    # defaults to tag, matching today's producer, but can be overridden to
    # exercise remap's SEMANTIC_MATCH/AMBIGUOUS paths (see test_remap.py).
    normalized = [(e[0], e[1], e[2] if len(e) > 2 else e[0]) for e in layers]
    layer_entries = {}
    tags = [tag for tag, _, _ in normalized]
    for tag, color, source_tag in normalized:
        Image.new("RGBA", size, color).save(root / "layers" / f"{tag}.png")
        layer_entries[tag] = {"path": f"layers/{tag}.png", "source_tag": source_tag}

    raw_entries = {}
    if raw_layers:
        (root / "raw_layers").mkdir(exist_ok=True)
        for tag, color in raw_layers.items():
            Image.new("RGBA", size, color).save(root / "raw_layers" / f"{tag}.png")
            raw_entries[tag] = f"raw_layers/{tag}.png"

    (root / "diagnostics").mkdir(exist_ok=True)
    diagnostics = {}
    if occlusion_edges is not None:
        occlusion = {
            "version": "1.0",
            "alpha_threshold": 10,
            "depth_available": False,
            "edges": occlusion_edges,
        }
        (root / "diagnostics" / "occlusion_graph.json").write_text(
            json.dumps(occlusion, indent=2), encoding="utf-8"
        )
        diagnostics["occlusion_graph"] = "diagnostics/occlusion_graph.json"

    generation = {
        "seed_mode": "deterministic_auto",
        "attempt_index": 0,
        "seed": 12345,
        "canonical_regression_seed": 42,
        "source_identity": source_identity,
    }
    generation.update(generation_overrides or {})

    validation = {"static_reconstruction": "pass", "seams": "pass", "local_fidelity": "pass"}
    validation.update(validation_overrides or {})

    canvas = {
        "width": size[0],
        "height": size[1],
        "coordinate_system": "top-left-y-down",
        "color_space": "srgb",
        "alpha": "straight",
    }
    canvas.update(canvas_overrides or {})

    manifest = {
        "format": "portrait-bundle",
        "version": version,
        "canvas": canvas,
        "semantics": {
            "schema": "portrait-semantic-tags",
            "version": "v3",
            "z_order": z_order_override if z_order_override is not None else list(tags),
            "warnings": semantic_warnings or [],
        },
        "original": "original.png",
        "generation": generation,
        "layers": layer_entries,
        "raw_layers": raw_entries,
        "layer_contract": {
            "canonical_stage": canonical_stage,
            "raw_layers_preserved": bool(raw_layers),
            "silhouette_guard": True,
            "semantic_ownership": {
                "version": "1.0",
                "stage": "post_repair_pre_remainder",
                "report": "diagnostics/semantic_ownership.json",
            },
            "fidelity_repair": {
                "version": "1.0",
                "order": [
                    "reclaim_occluded",
                    "fit_layer_tone",
                    "fit_edge_alpha",
                    "clean_garment_orphans",
                    "fit_edge_alpha_final",
                    "fit_mouth_contact",
                    "fit_seam_residual",
                ],
                "report": "diagnostics/fidelity.json",
            },
        },
        "diagnostics": diagnostics,
        "validation": validation,
        "source": {"filename": "input.png"},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


@pytest.fixture
def portrait_bundle(tmp_path) -> Path:
    return make_portrait_bundle(tmp_path / "sample.portrait")
