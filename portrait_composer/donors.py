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
from .slots import is_known_slot
from .variants import add_member, add_variant_set, configure_state_groups

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
    target_roi: Any = None,
    target_size: tuple[int, int] | None = None,
    target_anchor: tuple[float, float] | None = None,
    target_rotation: float = 0.0,
    target_drift_tolerance: float = 0.15,
) -> DriftReport:
    """Validate bounds and, when supplied, donor-to-target alignment drift.

    Bounds checks remain useful without a target.  Passing ``target_roi`` or
    ``target_anchor`` enables a deterministic comparison of placed ROI center,
    size, and rotation; this is still authoring QA, not image understanding.
    """
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
    if target_roi is not None or target_anchor is not None:
        if box is None:
            reasons.append("target alignment drift requires a donor ROI")
        else:
            target_size = target_size or image_size
            target_box = _bbox(target_roi, target_size) if target_roi is not None else None
            donor_cx = (box[0] + box[2]) / 2
            donor_cy = (box[1] + box[3]) / 2
            scale_x = float(transform.get("scale_x", 1.0))
            scale_y = float(transform.get("scale_y", 1.0))
            placed_center = (
                float(transform.get("x", 0.0)) + donor_cx * scale_x,
                float(transform.get("y", 0.0)) + donor_cy * scale_y,
            )
            if target_box is not None:
                target_center = ((target_box[0] + target_box[2]) / 2, (target_box[1] + target_box[3]) / 2)
                target_width = max(1, target_box[2] - target_box[0])
                target_height = max(1, target_box[3] - target_box[1])
                center_delta_norm = (((placed_center[0] - target_center[0]) / target_width) ** 2 + ((placed_center[1] - target_center[1]) / target_height) ** 2) ** 0.5
                scale_ratio = [((box[2] - box[0]) * scale_x) / target_width, ((box[3] - box[1]) * scale_y) / target_height]
                overlap = max(0, min(box[2], target_box[2]) - max(box[0], target_box[0])) * max(0, min(box[3], target_box[3]) - max(box[1], target_box[1]))
                union = (box[2] - box[0]) * (box[3] - box[1]) + target_width * target_height - overlap
                metrics.update({"center_delta_norm": center_delta_norm, "scale_ratio": scale_ratio, "roi_overlap": overlap / union if union else 0.0})
                if center_delta_norm > target_drift_tolerance:
                    reasons.append(f"target ROI center drift is {center_delta_norm:.3f}")
                if any(abs(ratio - 1.0) > target_drift_tolerance for ratio in scale_ratio):
                    reasons.append(f"target ROI scale drift is {scale_ratio!r}")
            elif target_anchor is not None:
                anchor_x, anchor_y = target_anchor
                target_w, target_h = target_size
                center_delta_norm = (((placed_center[0] - anchor_x) / max(1, target_w)) ** 2 + ((placed_center[1] - anchor_y) / max(1, target_h)) ** 2) ** 0.5
                metrics["center_delta_norm"] = center_delta_norm
                if center_delta_norm > target_drift_tolerance:
                    reasons.append(f"target anchor drift is {center_delta_norm:.3f}")
            rotation_delta = abs(float(transform.get("rotation", 0.0)) - float(target_rotation)) % 360
            rotation_delta = min(rotation_delta, 360 - rotation_delta)
            metrics["rotation_delta"] = rotation_delta
            if rotation_delta > 15:
                reasons.append(f"target rotation drift is {rotation_delta:.1f} degrees")
    if reasons:
        return DriftReport("FAIL", reasons, metrics)
    return DriftReport("PASS", [], metrics)


def _transform_dict(alignment: dict | Transform | None) -> dict:
    if alignment is None:
        return Transform().to_dict()
    result = alignment.to_dict() if isinstance(alignment, Transform) else dict(alignment)
    return Transform.from_dict(result).to_dict()


def expression_donor_kind(semantic: str) -> str | None:
    """Return the expression family for a donor semantic, if any."""
    normalized = semantic.strip().lower().replace("-", "_").replace(" ", "_")
    if (
        normalized in {"eye", "eyes", "eye_state", "eyes_state", "blink"}
        or normalized.startswith(("eye_", "eyes_", "blink_"))
    ):
        return "eyes"
    if (
        normalized in {"mouth", "mouth_state", "mouth_viseme", "talk", "open_mouth"}
        or normalized.startswith(("mouth_", "talk_", "open_mouth_"))
    ):
        return "mouth"
    if normalized in {"brow", "brows", "brow_state"} or normalized.startswith("brow_"):
        return "brow"
    return None


def _default_variant_set(semantic: str) -> str | None:
    kind = expression_donor_kind(semantic)
    return {"eyes": "eyes_state", "mouth": "mouth_state", "brow": "brow_state"}.get(kind)


def _expression_state(semantic: str, kind: str) -> str:
    normalized = semantic.strip().lower().replace("-", "_").replace(" ", "_")
    if kind == "eyes":
        return "closed" if normalized == "blink" or any(token in normalized for token in ("closed", "blink")) else "open"
    if kind == "mouth":
        return "open" if any(token in normalized for token in ("open", "talk")) else "closed"
    return "default"


def _normalized_slot(semantic: str, *, kind: str | None = None, target_slot: str | None = None) -> str:
    if target_slot and is_known_slot(target_slot):
        return target_slot
    normalized = semantic.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "body_remainder":
        return "body_back"
    if kind == "eyes" or normalized in {"eye", "eyes", "eyewhite", "irides", "iris", "eyelash"}:
        return "eye"
    if kind == "mouth" or normalized in {"mouth", "mouth_closed", "mouth_neutral", "mouth_open"}:
        return "mouth"
    if normalized in {"neck"}:
        return "neck"
    if normalized in {"head", "face"}:
        return normalized
    if normalized.startswith("hair_"):
        return "hair_front" if normalized.endswith("front") else "hair_back"
    if normalized in {"topwear", "torso", "upper_torso"} or normalized.startswith(("topwear_", "upper_torso_")):
        return "torso"
    if normalized in {"handwear", "hand_overlay", "sleeve", "arm"} or normalized.startswith(("handwear_", "hand_overlay_", "sleeve_", "arm_")):
        return "torso_front"
    return semantic


def _expression_stack(document: "AssemblyDocument", kind: str, *, target_instance_id: str | None = None) -> list[str]:
    """Find the existing facial stack without guessing from pixels."""
    if document is None:
        return []
    eye_semantics = {"eyewhite", "irides", "iris", "eyelash", "eye", "eyes", "eye_open", "eyes_open"}
    mouth_semantics = {"mouth", "mouth_closed", "mouth_neutral"}
    allowed = eye_semantics if kind == "eyes" else mouth_semantics
    found: list[str] = []
    if target_instance_id in document.instances:
        target = document.instances[target_instance_id]
        target_asset = document.assets.get(target.asset_ref)
        target_semantic = target_asset.semantic.lower() if target_asset and isinstance(target_asset.semantic, str) else ""
        if target_semantic in allowed:
            found.append(target_instance_id)
    for instance_id, instance in document.instances.items():
        asset = document.assets.get(instance.asset_ref)
        semantic = asset.semantic.lower() if asset and isinstance(asset.semantic, str) else ""
        if semantic in allowed and instance_id not in found:
            found.append(instance_id)
    found.sort(key=lambda instance_id: document.instances[instance_id].draw_order)
    return found


def _auto_expression_preset(document: "AssemblyDocument", variant_set_id: str, instance_id: str, semantic: str) -> None:
    normalized = semantic.strip().lower().replace("-", "_").replace(" ", "_")
    preset_name = None
    if normalized == "blink" or normalized.startswith("blink_"):
        preset_name = "expression_blink"
    elif normalized == "talk_open" or normalized.startswith("talk_open_"):
        preset_name = "expression_talk_open"
    if preset_name is None:
        return
    preset = document.expressions.get(preset_name, {"variants": {}})
    variants = dict(preset.get("variants", {}))
    variants[variant_set_id] = instance_id
    document.expressions[preset_name] = {
        "variants": variants,
        "metadata": {"auto_generated": True, "source": "donor_import"},
    }


def _configure_expression_variant(
    document: "AssemblyDocument",
    *,
    variant_set_id: str,
    donor_instance_id: str,
    kind: str,
    state: str,
    target_instance_id: str | None,
) -> None:
    existing = document.variant_sets.get(variant_set_id)
    if existing is None:
        stack = _expression_stack(document, kind, target_instance_id=target_instance_id)
        if state == "closed":
            groups = {"open": stack, "closed": [donor_instance_id]}
        else:
            groups = {"closed": stack, "open": [donor_instance_id]}
        groups = {name: members for name, members in groups.items() if members}
        members = list(dict.fromkeys(member_id for member_ids in groups.values() for member_id in member_ids))
        default = next(iter(groups.get("open", [])), donor_instance_id)
        add_variant_set(document, variant_set_id, members=members, default=default)
        configure_state_groups(document, variant_set_id, groups, default=default, active=default)
    else:
        groups = {name: list(member_ids) for name, member_ids in (existing.get("state_groups") or {}).items()}
        if not groups:
            previous = list(existing.get("members", []))
            if kind == "eyes":
                groups["open"] = previous
            else:
                groups["closed"] = previous
        stack = _expression_stack(document, kind, target_instance_id=target_instance_id)
        if kind == "eyes" and stack:
            groups.setdefault("open", [])
            groups["open"] = list(dict.fromkeys([*groups["open"], *stack]))
        if kind == "mouth" and stack:
            groups.setdefault("closed", [])
            groups["closed"] = list(dict.fromkeys([*groups["closed"], *stack]))
        groups.setdefault(state, [])
        groups[state] = list(dict.fromkeys([*groups[state], donor_instance_id]))
        active = existing.get("active") if existing.get("active") in existing.get("members", []) else None
        default = existing.get("default") if existing.get("default") in existing.get("members", []) else None
        default = default or next(iter(groups.get("open", [])), donor_instance_id)
        active = active or default
        configure_state_groups(document, variant_set_id, groups, default=default, active=active)
    vs = document.variant_sets[variant_set_id]
    vs.setdefault("state_labels", {})
    for state_name, member_ids in vs.get("state_groups", {}).items():
        for member_id in member_ids:
            vs["state_labels"][member_id] = state_name


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
    import_mode: str | None = None,
    target_instance_id: str | None = None,
    target_roi: Any = None,
    target_size: tuple[int, int] | None = None,
    target_anchor: tuple[float, float] | None = None,
    target_rotation: float = 0.0,
    target_drift_tolerance: float = 0.15,
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
    expression_kind = expression_donor_kind(semantic)
    if import_mode is None:
        import_mode = "variant_member" if variant_set_id or expression_kind else "independent_layer"
    if import_mode not in {"variant_member", "replacement", "independent_layer"}:
        raise DonorError(
            f"invalid donor import_mode: {import_mode!r} "
            "(expected 'variant_member', 'replacement', or 'independent_layer')"
        )
    if import_mode == "replacement" and target_instance_id is None:
        raise DonorError("replacement import requires target_instance_id")
    if import_mode == "variant_member" and expression_kind is None and not (variant_set_id or variant_set):
        raise DonorError("variant_member import requires an expression semantic or variant_set_id")
    asset_id = asset_id or f"{semantic}__donor"
    if import_mode == "replacement":
        instance_id = target_instance_id
    else:
        instance_id = instance_id or f"{asset_id}__instance"
    source_id = donor_id or f"donor:{donor_path.stem}"
    variant_set_id = variant_set_id or variant_set or _default_variant_set(semantic)

    target_instance = document.instances.get(target_instance_id) if target_instance_id else None
    if target_instance_id and target_instance is None:
        raise DonorError(f"no such target instance: {target_instance_id!r}")
    if alignment is None and target_instance is not None and import_mode in {"variant_member", "replacement"}:
        alignment = target_instance.transform

    with Image.open(donor_path) as source_image:
        source_image = source_image.convert("RGBA")
        processed = _apply_matte(source_image, matte)
        processed = _apply_operations(processed, operations)
        drift = check_drift(
            processed.size,
            roi,
            alignment=alignment,
            tolerance=drift_tolerance,
            target_roi=target_roi,
            target_size=target_size,
            target_anchor=target_anchor,
            target_rotation=target_rotation,
            target_drift_tolerance=target_drift_tolerance,
        )
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
        "target_roi": dict(target_roi) if isinstance(target_roi, dict) else target_roi,
        "target_anchor": list(target_anchor) if target_anchor is not None else None,
        "operations": list(operations or []),
        "drift": drift.to_dict(),
        "import_mode": import_mode,
        "target_instance_id": target_instance_id,
        "variant_state": _expression_state(semantic, expression_kind) if expression_kind else None,
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
        if import_mode == "replacement":
            assert target_instance is not None
            instance_id = target_instance.id
            target_instance.asset_ref = asset_id
            target_instance.slot = slot or _normalized_slot(
                semantic,
                kind=expression_kind,
                target_slot=target_instance.slot,
            )
            target_instance.plane = None
            if alignment is not None:
                target_instance.transform = Transform.from_dict(transform)
            draw_order = target_instance.draw_order
        else:
            if draw_order is None:
                draw_order = max((i.draw_order for i in document.instances.values()), default=-10) + 10
            document.add_instance(
                LayerInstance(
                    id=instance_id,
                    asset_ref=asset_id,
                    slot=slot or _normalized_slot(semantic, kind=expression_kind),
                    draw_order=draw_order,
                    transform=Transform.from_dict(transform),
                )
            )
            document.composition.setdefault("draw_order", []).append(instance_id)
        document.provenance.record(instance_id, "donor_import", sources=[source_id], detail=provenance_detail)
        document.provenance.record(asset_id, "donor_import", sources=[source_id], detail=provenance_detail)

        if import_mode == "variant_member":
            if expression_kind:
                _configure_expression_variant(
                    document,
                    variant_set_id=variant_set_id,
                    donor_instance_id=instance_id,
                    kind=expression_kind,
                    state=_expression_state(semantic, expression_kind),
                    target_instance_id=target_instance_id,
                )
            elif variant_set_id:
                if variant_set_id in document.variant_sets:
                    add_member(document, variant_set_id, instance_id)
                else:
                    add_variant_set(document, variant_set_id, members=[instance_id], default=instance_id)
            _auto_expression_preset(
                document,
                variant_set_id,
                instance_id,
                semantic,
            )

    if image_sources is not None:
        image_sources[instance_id] = image_path
    return DonorImportResult(asset_id, instance_id, image_path, source_id, drift, variant_set_id)


# Names used by adapters and early prototypes.
add_donor = import_donor
import_donor_asset = import_donor
