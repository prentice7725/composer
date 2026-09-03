"""Portrait Bundle (input) / Assembly Bundle (output) I/O.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #29;
SEETHROUGH_..._MASTER_v0.2.md #1-2.

IMPORTANT -- assumed input contract:
`seethrough-portrait` (the upstream project that produces Portrait Bundles)
is not implemented yet, so this module defines the minimal Portrait Bundle
shape Composer needs to do C0 identity import. Treat this as an interim
contract to be reconciled against the real seethrough-portrait output
format once that project lands, not as a spec Composer owns.

    <name>.portrait/
        manifest.json
        layers/
            <layer_id>.png

    manifest.json:
    {
      "format": "portrait-bundle",
      "version": "0.1",
      "canvas": {"width": W, "height": H},
      "source": {"source_id": "A001", "path": "optional/original.png"},
      "layers": [
        {"id": "hair_back", "semantic": "hair_back", "file": "layers/hair_back.png",
         "draw_order": 10, "planes": ["hair_back"]},
        ...
      ]
    }

Assembly Bundle (output, directive #29):

    A001.assembly/
        manifest.json
        reference.png
        layers/
        expressions/
        masks/
        diagnostics/
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .document import AssemblyDocument
from .render import render_reference

ASSEMBLY_FORMAT = "portrait-assembly"
ASSEMBLY_VERSION = "0.2"
PORTRAIT_FORMAT = "portrait-bundle"


class BundleError(Exception):
    pass


@dataclass
class PortraitBundleLayer:
    id: str
    semantic: str
    file: str
    draw_order: int
    planes: list = field(default_factory=list)


@dataclass
class PortraitBundle:
    root: Path
    canvas: dict
    source: dict
    layers: list  # list[PortraitBundleLayer]

    def layer_path(self, layer: PortraitBundleLayer) -> Path:
        return self.root / layer.file


def read_portrait_bundle(path: Path) -> PortraitBundle:
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise BundleError(f"not a portrait bundle (missing manifest.json): {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != PORTRAIT_FORMAT:
        raise BundleError(f"unexpected format in {manifest_path}: {manifest.get('format')!r}")

    layers = [
        PortraitBundleLayer(
            id=l["id"],
            semantic=l.get("semantic", l["id"]),
            file=l["file"],
            draw_order=l.get("draw_order", i * 10),
            planes=list(l.get("planes", [l["id"]])),
        )
        for i, l in enumerate(manifest.get("layers", []))
    ]
    return PortraitBundle(
        root=path,
        canvas=dict(manifest.get("canvas", {})),
        source=dict(manifest.get("source", {})),
        layers=layers,
    )


def write_assembly_bundle(
    document: AssemblyDocument,
    image_sources: dict,  # instance_id -> Path to source PNG
    out_dir: Path,
    reference_image=None,
) -> Path:
    """Writes a v0.2 Assembly Bundle to ``out_dir``.

    ``image_sources`` maps instance id -> a source PNG path to copy into
    ``layers/<instance_id>.png``. If ``reference_image`` (a PIL Image) is
    not given, it is rendered from ``document`` + the copied layer images.
    """
    out_dir = Path(out_dir)
    layers_dir = out_dir / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("expressions", "masks", "diagnostics"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    for inst_id, src_path in image_sources.items():
        shutil.copyfile(src_path, layers_dir / f"{inst_id}.png")

    if reference_image is None:
        reference_image = render_reference(document, layers_dir)
    reference_image.save(out_dir / "reference.png")

    manifest = {"format": ASSEMBLY_FORMAT, "version": ASSEMBLY_VERSION}
    manifest.update(document.to_dict())
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return out_dir


def read_assembly_bundle(path: Path) -> AssemblyDocument:
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise BundleError(f"not an assembly bundle (missing manifest.json): {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != ASSEMBLY_FORMAT:
        raise BundleError(f"unexpected format in {manifest_path}: {manifest.get('format')!r}")
    return AssemblyDocument.from_dict(manifest)


def assembly_layers_dir(path: Path) -> Path:
    return Path(path) / "layers"
