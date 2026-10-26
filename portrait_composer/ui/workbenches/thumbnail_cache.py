"""Small corrected-source thumbnail cache for visual authoring cards."""
from __future__ import annotations

import hashlib
import io
import json
from collections import OrderedDict
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QPixmap

from ...visual_ops import apply_visual_ops

_CACHE: OrderedDict[tuple, QPixmap] = OrderedDict()
_CACHE_LIMIT = 384


def instance_thumbnail(main_window, instance_id: str, *, size: int = 64, source_revision=None) -> QPixmap:
    """Return a corrected thumbnail keyed by source and VisualOps revision."""
    document = getattr(main_window, "document", None)
    instance = document.instances.get(instance_id) if document is not None else None
    scene = getattr(getattr(main_window, "canvas", None), "scene_model", None)
    path = scene._resolve_image_path(instance_id) if scene is not None else None
    if instance is None or path is None:
        return QPixmap()
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return QPixmap()
    if not path.is_file():
        return QPixmap()

    visual_ops = list(getattr(instance, "visual_ops", []) or [])
    correction_payload = json.dumps(visual_ops, sort_keys=True, separators=(",", ":"), default=str)
    correction_revision = hashlib.sha256(correction_payload.encode("utf-8")).hexdigest()
    key = (
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        correction_revision,
        str(source_revision or ""),
        int(size),
    )
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return QPixmap(cached)

    base_dir = path.parent.parent if path.parent.name == "layers" else path.parent
    try:
        with Image.open(path) as raw:
            image = apply_visual_ops(raw.convert("RGBA"), visual_ops, base_dir=base_dir)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG")
        pixmap = QPixmap()
        if not pixmap.loadFromData(output.getvalue(), "PNG"):
            return QPixmap()
    except (OSError, ValueError, TypeError):
        return QPixmap()

    _CACHE[key] = QPixmap(pixmap)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return pixmap
