"""Resolve a trustworthy original for an unmodified topwear/handwear bake.

Both preview and apply use this entry point. Missing or incompatible source
data falls back to local seam repair; an original is never guessed by name.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from .instances import Transform
from .seam_repair import repair_semantic_merge
from .sources import content_hash


def _bundle_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("reference path escapes its source bundle")
    return path


def _load_reference(document, image_sources, layers, transform_overrides):
    bindings = []
    for instance_id, _, _ in layers:
        instance = document.instances[instance_id]
        transform = (transform_overrides or {}).get(instance_id, instance.transform)
        if isinstance(transform, dict):
            transform = Transform.from_dict(transform)
        if not transform.is_identity() or instance.opacity != 1 or instance.visual_ops:
            return None
        binding = document.assets[instance.asset_ref].source_binding
        if binding is None:
            return None
        bindings.append(binding)
    if len(bindings) != 2 or len({(b.source_id, b.revision) for b in bindings}) != 1:
        return None
    source = document.sources.get(bindings[0].source_id)
    if source is None or not source.path:
        return None
    root = Path(source.path).resolve()
    manifest_path = root / "manifest.json"
    if content_hash(manifest_path) != bindings[0].revision:
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "portrait-bundle":
        return None
    entries = manifest["layers"]
    tags = [b.source_layer_id for b in bindings]
    if {entries[tag]["source_tag"] for tag in tags} != {"topwear", "handwear"}:
        return None
    size = layers[0][2].size
    # Saved assemblies can point at copied PNGs. Compare pixels, not paths,
    # to reject replacement rasters while allowing faithful imported copies.
    for (instance_id, _, rendered), tag in zip(layers, tags):
        with Image.open(_bundle_file(root, entries[tag]["path"])) as image:
            canonical = image.convert("RGBA")
        with Image.open(image_sources[instance_id]) as image:
            current = image.convert("RGBA")
        if canonical.size != size or current.size != size:
            return None
        expected_render = Image.alpha_composite(Image.new("RGBA", size), canonical)
        if current.tobytes() != canonical.tobytes() or rendered.tobytes() != expected_render.tobytes():
            return None
    original_path = _bundle_file(root, manifest["original"])
    with Image.open(original_path) as image:
        original = image.convert("RGBA")
    if original.size != size:
        return None
    order = manifest["semantics"]["z_order"]
    if len(order) != len(set(order)) or set(order) != set(entries):
        return None
    earliest = min(order.index(tag) for tag in tags)
    excluded = Image.new("L", size, 0)
    # Hair/face/etc. from the original must never be burned into this bake,
    # even if those other instances are now hidden, moved or removed.
    for tag in order[earliest + 1:]:
        if tag in tags:
            continue
        with Image.open(_bundle_file(root, entries[tag]["path"])) as image:
            if image.size != size:
                return None
            excluded = ImageChops.lighter(excluded, image.convert("RGBA").getchannel("A"))
    excluded = excluded.point(lambda v: 255 if v else 0).filter(ImageFilter.MaxFilter(5))
    valid = ImageChops.subtract(original.getchannel("A"), excluded).point(lambda v: 255 if v == 255 else 0)
    return original, valid, {
        "source_id": bindings[0].source_id,
        "revision": bindings[0].revision,
        "original_hash": content_hash(original_path),
    }


def repair_bake_seams(document, image_sources, composite, layers, policy, *, transform_overrides=None):
    reference = None
    if policy["cleanup"] != "off" and policy["remove_internal_lines"]:
        try:
            reference = _load_reference(document, image_sources, layers, transform_overrides)
        except (OSError, ValueError, KeyError, TypeError):
            # Source bundles may no longer exist after an assembly is moved.
            # Reference restoration is optional; canonical layer bake still works.
            reference = None
    kwargs = {}
    if reference is not None:
        kwargs = {"reference_image": reference[0], "reference_valid_mask": reference[1]}
    repaired, report = repair_semantic_merge(composite, layers, policy, **kwargs)
    if reference is not None:
        report["reference_source"] = reference[2]
    return repaired, report
