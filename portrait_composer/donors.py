"""Donor import and provenance (C3).

The importer produces a normal ``AssetDefinition`` and ``LayerInstance``.
Expression membership is optional and, when requested, uses an ordinary
VariantSet.  The source image is never handed to AutoRig and every operation
needed to reproduce the derived asset is kept in provenance.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from PIL import Image, ImageChops

from .assets import AssetDefinition
from .instances import LayerInstance, Transform
from .sources import SourceAsset, SourceBinding, content_hash
from .variants import add_member, add_variant_set

if TYPE_CHECKING:
    from .document import AssemblyDocument


class DonorError(ValueError):
    pass


class DonorDriftError(DonorError):
    pass


@dataclass
class DriftReport:
    status: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict:
        return {"status": self.status, "reasons": list(self.reasons), "metrics": dict(self.metrics)}


@dataclass
class DonorImportResult:
    asset_id: str
    instance_id: str
    image_path: Path
    source_id: str
    drift: DriftReport
    variant_set_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "instance_id": self.instance_id,
            "image_path": str(self.image_path),
            "source_id": self.source_id,
            "drift": self.drift.to_dict(),
            "variant_set_id": self.variant_set_id,
        }


def _bbox(roi: Any, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    if roi is None:
        return None
    width, height = size
    if isinstance(roi, dict):
        if {"x", "y", "width", "height"} <= set(roi):
            values = (roi["x"], roi["y"], roi["width"], roi["height"])
            if roi.get("normalized"):
                values = (values[0] * width, values[1] * height, values[2] * width, values[3] * height)
            x, y, w, h = values
            return round(x), round(y), round(x + w), round(y + h)
        if {"left", "top", "right", "bottom"} <= set(roi):
            values = (roi["left"], roi["top"], roi["right"], roi["bottom"])
            if roi.get("normalized"):
                values = (values[0] * width, values[1] * height, values[2] * width, values[3] * height)
            return tuple(round(v) for v in values)
    if isinstance(roi, (tuple, list)) and len(roi) == 4:
        return tuple(round(v) for v in roi)
    raise DonorError("ROI must be {x, y, width, height}, {left, top, right, bottom}, or a 4-item sequence")


def _apply_matte(image: Image.Image, matte: Any) -> Image.Image:
    if matte is None:
        return image
    matte_path = Path(matte) if isinstance(matte, (str, Path)) else None
    if matte_path is not None:
        if not matte_path.exists():
            raise DonorError(f"matte file does not exist: {matte_path}")
        with Image.open(matte_path) as matte_image:
            mask = matte_image.convert("RGBA").getchannel("A") if matte_image.mode == "RGBA" else matte_image.convert("L")
            mask = mask.copy()
    elif isinstance(matte, Image.Image):
        mask = matte.getchannel("A") if matte.mode == "RGBA" else matte.convert("L")
    else:
        raise DonorError("matte must be an image path or PIL Image")
    if mask.size != image.size:
        raise DonorError(f"matte size {mask.size} does not match donor size {image.size}")
    rgba = image.convert("RGBA")
    alpha = ImageChops.multiply(rgba.getchannel("A"), mask)
    rgba.putalpha(alpha)
    return rgba


def _apply_operations(image: Image.Image, operations: list | None) -> Image.Image:
    """Apply the small deterministic pixel operations Composer owns.

    Alignment remains instance transform state.  Unknown operations are
    rejected so provenance can never claim a transformation that was silently
    skipped.
    """
    result = image
    for operation in operations or []:
        if isinstance(operation, str):
            name, options = operation, {}
        elif isinstance(operation, dict):
            name, options = operation.get("op"), operation
        else:
            raise DonorError(f"invalid donor operation: {operation!r}")
        if name in {"flip_x", "mirror_x", "hflip"}:
            result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif name in {"flip_y", "mirror_y", "vflip"}:
            result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        elif name == "rotate":
            angle = options.get("degrees", options.get("angle"))
            if not isinstance(angle, (int, float)) or not isfinite(angle):
                raise DonorError("rotate operation needs a finite degrees/angle value")
            result = result.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)
        else:
            raise DonorError(f"unsupported donor operation: {name!r}")
    return result


def check_drift(
    image_size: tuple[int, int],
    roi: Any = None,
    *,
    alignment: dict | Transform | None = None,
    tolerance: float = 0.0,
) -> DriftReport:
    """Validate deterministic crop/alignment bounds without guessing semantics."""
    width, height = image_size
    reasons: list[str] = []
    metrics: dict[str, Any] = {"image_size": [width, height]}
    box = _bbox(roi, image_size)
    if box is not None:
        left, top, right, bottom = box
        metrics["roi"] = [left, top, right, bottom]
        overflow = max(0, -left, -top, right - width, bottom - height)
        metrics["roi_overflow"] = overflow
        if right <= left or bottom <= top:
            reasons.append("ROI has no positive area")
        elif overflow > tolerance:
            reasons.append(f"ROI drifts outside donor bounds by {overflow}px")

    transform = alignment.to_dict() if isinstance(alignment, Transform) else dict(alignment or {})
    for key in ("x", "y", "scale_x", "scale_y", "rotation"):
        if key in transform and (not isinstance(transform[key], (int, float)) or not isfinite(transform[key])):
            reasons.append(f"alignment.{key} must be finite")
    if transform.get("scale_x", 1) <= 0 or transform.get("scale_y", 1) <= 0:
        reasons.append("alignment scale must be positive")
    if reasons:
        return DriftReport("FAIL", reasons, metrics)
    return DriftReport("PASS", [], metrics)


def _transform_dict(alignment: dict | Transform | None) -> dict:
    if alignment is None:
        return Transform().to_dict()
    result = alignment.to_dict() if isinstance(alignment, Transform) else dict(alignment)
    return Transform.from_dict(result).to_dict()


def _default_variant_set(semantic: str) -> str | None:
    normalized = semantic.lower()
    if normalized in {"eye", "eyes", "eye_state"} or normalized.startswith("eye_") or normalized.startswith("eyes_"):
        return "eye_state"
    if normalized in {"mouth", "mouth_state", "mouth_viseme"} or normalized.startswith("mouth_"):
        return "mouth_viseme"
    if normalized in {"brow", "brows", "brow_state"} or normalized.startswith("brow_"):
        return "brow_state"
    return None


def import_donor(
    document: "AssemblyDocument",
    donor_path: Path,
    *,
    semantic: str,
    asset_id: str | None = None,
    instance_id: str | None = None,
    donor_id: str | None = None,
    matte: Any = None,
    alignment: dict | Transform | None = None,
    roi: Any = None,
    drift_tolerance: float = 0.0,
    allow_drift: bool = False,
    operations: list | None = None,
    slot: str | None = None,
    draw_order: int | None = None,
    variant_set_id: str | None = None,
    variant_set: str | None = None,
    image_sources: dict | None = None,
    work_dir: Path | None = None,
) -> DonorImportResult:
    """Import one donor through matte, alignment intent, ROI and drift check.

    ``alignment`` is stored on the LayerInstance as Composer placement state;
    it is not baked into the pixels.  The output image is cropped/matted and
    written to ``work_dir`` so it can be exported as a normal layer.
    """
    donor_path = Path(donor_path)
    if not donor_path.exists():
        raise DonorError(f"donor file does not exist: {donor_path}")
    if not semantic:
        raise DonorError("donor semantic must be non-empty")
    asset_id = asset_id or f"{semantic}__donor"
    instance_id = instance_id or f"{asset_id}__instance"
    source_id = donor_id or f"donor:{donor_path.stem}"
    variant_set_id = variant_set_id or variant_set or _default_variant_set(semantic)

    with Image.open(donor_path) as source_image:
        source_image = source_image.convert("RGBA")
        processed = _apply_matte(source_image, matte)
        processed = _apply_operations(processed, operations)
        drift = check_drift(processed.size, roi, alignment=alignment, tolerance=drift_tolerance)
        if not drift.ok and not allow_drift:
            raise DonorDriftError("; ".join(drift.reasons))
        box = _bbox(roi, processed.size)
        if box is not None:
            processed = processed.crop(box)

    work_dir = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="portrait-composer-donor-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = work_dir / f"{instance_id}.png"
    processed.save(image_path)

    transform = _transform_dict(alignment)
    source_revision = content_hash(donor_path)
    provenance_detail = {
        "source_donor": str(donor_path),
        "donor_id": source_id,
        "crop": dict(roi) if isinstance(roi, dict) else list(roi) if isinstance(roi, (list, tuple)) else roi,
        "matte": str(matte) if isinstance(matte, (str, Path)) else bool(matte is not None),
        "alignment_transform": transform,
        "semantic_roi": dict(roi) if isinstance(roi, dict) else roi,
        "operations": list(operations or []),
        "drift": drift.to_dict(),
    }
    asset_provenance = {"operation": "donor_import", **provenance_detail}

    with document.transaction():
        if source_id in document.sources:
            existing = document.sources[source_id]
            if existing.path != str(donor_path):
                raise DonorError(f"source id already refers to another donor: {source_id!r}")
        else:
            document.sources[source_id] = SourceAsset(
                source_id=source_id,
                path=str(donor_path),
                metadata={"kind": "donor", "revision": source_revision},
            )
        document.add_asset(
            AssetDefinition(
                id=asset_id,
                semantic=semantic,
                source_binding=SourceBinding(
                    source_id=source_id,
                    revision=source_revision,
                    source_layer_id=asset_id,
                    fallback_semantic=semantic,
                ),
                planes=[semantic],
                provenance=asset_provenance,
            )
        )
        if draw_order is None:
            draw_order = max((i.draw_order for i in document.instances.values()), default=-10) + 10
        document.add_instance(
            LayerInstance(
                id=instance_id,
                asset_ref=asset_id,
                slot=slot or semantic,
                draw_order=draw_order,
                transform=Transform.from_dict(transform),
            )
        )
        document.composition.setdefault("draw_order", []).append(instance_id)
        document.provenance.record(instance_id, "donor_import", sources=[source_id], detail=provenance_detail)
        document.provenance.record(asset_id, "donor_import", sources=[source_id], detail=provenance_detail)

        if variant_set_id:
            if variant_set_id in document.variant_sets:
                add_member(document, variant_set_id, instance_id)
            else:
                add_variant_set(document, variant_set_id, members=[instance_id], default=instance_id)

    if image_sources is not None:
        image_sources[instance_id] = image_path
    return DonorImportResult(asset_id, instance_id, image_path, source_id, drift, variant_set_id)


# Names used by adapters and early prototypes.
add_donor = import_donor
import_donor_asset = import_donor
