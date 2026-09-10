"""ORA-first external pixel-edit round trip.

OpenRaster is an exchange format only.  The Assembly Bundle remains the
source of truth; the sidecar is the only authority for Composer instance
identity and authored metadata.  This module deliberately does not import
RigIntent, VariantSet meaning, or runtime settings from an external file.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .expressions import build_expression_intent
from .visual_ops import apply_visual_ops

ROUNDTRIP_FORMAT = "portrait-composer-roundtrip"
ROUNDTRIP_VERSION = "0.1"
_ID_RE = re.compile(r"^\[PC:([^\]]+)\]\s*(.*)$")


class ExternalEditError(ValueError):
    pass


def _sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def _layer_image(document, image_sources: dict, instance_id: str) -> Image.Image:
    source = Path(image_sources[instance_id])
    with Image.open(source) as image:
        result = image.convert("RGBA")
    base_dir = source.parent.parent if source.parent.name == "layers" else source.parent
    return apply_visual_ops(result, document.instances[instance_id].visual_ops, base_dir=base_dir)


def _visible_ids(document) -> list[str]:
    return [
        instance_id
        for instance_id in document.composition.get("draw_order", [])
        if instance_id in document.instances and document.instances[instance_id].visible
    ]


def _sidecar(document, image_sources: dict, ids: list[str]) -> dict:
    layers = {}
    for draw_index, instance_id in enumerate(ids):
        instance = document.instances[instance_id]
        asset = document.assets.get(instance.asset_ref)
        image = _layer_image(document, image_sources, instance_id)
        layers[instance_id] = {
            "semantic": asset.semantic if asset else instance.asset_ref,
            "source_hash": _sha256(image),
            "transform": instance.transform.to_dict(),
            "draw_index": draw_index,
            "visible": bool(instance.visible),
        }
    canvas = dict(document.composition.get("canvas", {}))
    return {
        "format": ROUNDTRIP_FORMAT,
        "version": ROUNDTRIP_VERSION,
        "assembly_revision": document.provenance.to_dict().get("revision"),
        "canvas": canvas,
        "layers": layers,
        "expression_intent": build_expression_intent(document),
    }


def export_ora(document, image_sources: dict, out_path: Path, *, sidecar_path: Path | None = None) -> tuple[Path, Path]:
    """Write an ORA layer exchange plus a deterministic Composer sidecar."""
    out_path = Path(out_path)
    sidecar_path = Path(sidecar_path) if sidecar_path is not None else out_path.with_name("composer-roundtrip.json")
    ids = _visible_ids(document)
    canvas = document.composition.get("canvas", {})
    width = int(canvas.get("width") or 1)
    height = int(canvas.get("height") or 1)
    stack = ET.Element("image", {
        "version": "0.0.1",
        "w": str(width),
        "h": str(height),
        "name": "Portrait Composer",
        "src": "mergedimage.png",
    })
    stack_node = ET.SubElement(stack, "stack", {"name": "Composer layers"})
    payloads: dict[str, bytes] = {}
    for index, instance_id in enumerate(ids):
        instance = document.instances[instance_id]
        asset = document.assets.get(instance.asset_ref)
        semantic = asset.semantic if asset else instance.asset_ref
        filename = f"data/{index:04d}_{instance_id}.png"
        image = _layer_image(document, image_sources, instance_id)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payloads[filename] = buffer.getvalue()
        ET.SubElement(stack_node, "layer", {
            "name": f"[PC:{instance_id}] {semantic}",
            "src": filename,
            "x": str(round(instance.transform.x)),
            "y": str(round(instance.transform.y)),
            "opacity": str(instance.opacity),
            "visibility": "visible" if instance.visible else "hidden",
        })
    merged = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # ORA stack order is bottom-to-top; the Assembly draw_order has the same
    # meaning in Composer's source reconstruction renderer.
    for instance_id in ids:
        image = _layer_image(document, image_sources, instance_id)
        instance = document.instances[instance_id]
        merged.alpha_composite(image, dest=(round(instance.transform.x), round(instance.transform.y)))
    merged_buffer = io.BytesIO()
    merged.save(merged_buffer, format="PNG")
    payloads["mergedimage.png"] = merged_buffer.getvalue()
    xml = ET.tostring(stack, encoding="utf-8", xml_declaration=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as archive:
        archive.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
        archive.writestr("stack.xml", xml)
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    sidecar = _sidecar(document, image_sources, ids)
    sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8")
    return out_path, sidecar_path


def _load_sidecar(path: Path) -> dict:
    try:
        sidecar = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalEditError(f"invalid Composer roundtrip sidecar: {exc}") from exc
    if sidecar.get("format") != ROUNDTRIP_FORMAT or sidecar.get("version") != ROUNDTRIP_VERSION:
        raise ExternalEditError("unsupported Composer roundtrip sidecar version")
    if not isinstance(sidecar.get("layers"), dict):
        raise ExternalEditError("roundtrip sidecar layers must be an object")
    return sidecar


def inspect_ora(ora_path: Path, sidecar_path: Path) -> dict:
    """Classify an ORA against its sidecar without mutating Composer state."""
    sidecar = _load_sidecar(sidecar_path)
    try:
        archive = zipfile.ZipFile(ora_path)
        root = ET.fromstring(archive.read("stack.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ExternalEditError(f"invalid OpenRaster file: {exc}") from exc
    external: dict[str, dict] = {}
    for layer in root.findall(".//layer"):
        match = _ID_RE.match(layer.get("name", ""))
        if not match:
            continue
        instance_id, semantic = match.groups()
        src = layer.get("src")
        if not src:
            continue
        with archive.open(src) as raw:
            image = Image.open(raw).convert("RGBA")
            external[instance_id] = {"semantic": semantic.strip(), "hash": _sha256(image), "src": src}
    statuses = {}
    expected = sidecar.get("layers", {})
    for instance_id, entry in expected.items():
        if instance_id not in external:
            statuses[instance_id] = "MISSING_EXTERNAL_LAYER"
        elif external[instance_id]["hash"] == entry.get("source_hash"):
            statuses[instance_id] = "UNCHANGED"
        else:
            statuses[instance_id] = "PIXELS_CHANGED"
    for instance_id in external:
        if instance_id not in expected:
            statuses[instance_id] = "NEW_EXTERNAL_LAYER"
    return {"ora": str(ora_path), "sidecar": str(sidecar_path), "layers": statuses, "external": external}


def apply_ora_reimport(document, image_sources: dict, ora_path: Path, sidecar_path: Path, work_dir: Path, *, instance_ids: list[str] | None = None) -> dict:
    """Apply only explicitly matched pixel changes; contracts stay intact."""
    report = inspect_ora(ora_path, sidecar_path)
    allowed = set(instance_ids) if instance_ids is not None else {
        key for key, status in report["layers"].items() if status == "PIXELS_CHANGED"
    }
    archive = zipfile.ZipFile(ora_path)
    changed = []
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    with document.transaction():
        for instance_id in sorted(allowed):
            if report["layers"].get(instance_id) != "PIXELS_CHANGED":
                continue
            if instance_id not in document.instances:
                continue
            src = report["external"][instance_id]["src"]
            target = work_dir / f"{instance_id}.png"
            target.write_bytes(archive.read(src))
            image_sources[instance_id] = target
            document.provenance.record(instance_id, operation="external_edit_reimport", detail={"format": "ora", "path": str(ora_path)})
            changed.append(instance_id)
    report["applied"] = changed
    return report
