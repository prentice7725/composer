from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image


def make_portrait_bundle(root: Path, *, size=(40, 40), layers=None, source_id="A001") -> Path:
    """Writes a minimal Portrait Bundle (see bundle.py docstring for the
    assumed interchange contract) to ``root`` and returns ``root``."""
    if layers is None:
        layers = [
            ("body", "body", 10, (255, 0, 0, 255)),
            ("topwear", "torso", 40, (0, 255, 0, 200)),
            ("head", "head", 60, (0, 0, 255, 255)),
        ]

    root.mkdir(parents=True, exist_ok=True)
    layers_dir = root / "layers"
    layers_dir.mkdir(exist_ok=True)

    manifest_layers = []
    for layer_id, semantic, draw_order, color in layers:
        img = Image.new("RGBA", size, color)
        file_rel = f"layers/{layer_id}.png"
        img.save(root / file_rel)
        manifest_layers.append(
            {"id": layer_id, "semantic": semantic, "file": file_rel, "draw_order": draw_order, "planes": [layer_id]}
        )

    manifest = {
        "format": "portrait-bundle",
        "version": "0.1",
        "canvas": {"width": size[0], "height": size[1]},
        "source": {"source_id": source_id},
        "layers": manifest_layers,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


@pytest.fixture
def portrait_bundle(tmp_path) -> Path:
    return make_portrait_bundle(tmp_path / "sample.portrait")
