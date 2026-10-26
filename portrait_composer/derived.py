"""Producer-derived candidates and explicit left/right adoption.

The producer's ``derived/`` tree is an optional candidate source.  This module
keeps discovery side-effect free and puts document mutation behind one
transaction so adopt, undo/redo, save/reload, and revert have deterministic
semantics.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from PIL import Image

from .assets import AssetDefinition
from .instances import LayerInstance
from .sources import SourceBinding, SourceAsset, content_hash

if TYPE_CHECKING:
    from .bundle import PortraitBundle
    from .document import AssemblyDocument


class DerivedCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class DerivedCandidate:
    source_semantic: str
    kind: str
    member: str
    path: Path
    source_bundle: str

    def to_dict(self) -> dict:
        return {
            "source_semantic": self.source_semantic,
            "kind": self.kind,
            "member": self.member,
            "path": str(self.path),
            "source_bundle": self.source_bundle,
        }


def candidates_from_bundle(bundle: "PortraitBundle", *, kind: str = "left_right") -> list[DerivedCandidate]:
    block = (bundle.derived or {}).get(kind, {})
    if block.get("status") != "computed":
        return []
    paths = block.get("paths", {})
    result: list[DerivedCandidate] = []
    for semantic in sorted(paths):
        entries = paths[semantic]
        if kind == "left_right":
            for member in ("left", "right"):
                relative = entries.get(member)
                if relative:
                    result.append(
                        DerivedCandidate(
                            source_semantic=semantic,
                            kind=kind,
                            member=member,
                            path=bundle.root / relative,
                            source_bundle=_source_bundle_id(bundle),
                        )
                    )
        elif isinstance(entries, str):
            result.append(
                DerivedCandidate(
                    source_semantic=semantic,
                    kind=kind,
                    member="default",
                    path=bundle.root / entries,
                    source_bundle=_source_bundle_id(bundle),
                )
            )
    return result


def _source_bundle_id(bundle: "PortraitBundle") -> str:
    from .bundle import source_id_for

    return source_id_for(bundle)


def _instances_for_semantic(document: "AssemblyDocument", semantic: str) -> list[str]:
    return [
        instance_id
        for instance_id, instance in document.instances.items()
        if (document.assets.get(instance.asset_ref) is not None
            and document.assets[instance.asset_ref].semantic == semantic
            and not document.assets[instance.asset_ref].provenance.get("operation") == "adopt_producer_derivative")
    ]


def _pair_instances(document, semantic: str, source_bundle: str, canonical_instance_id: str) -> dict[str, LayerInstance]:
    matches: dict[str, LayerInstance] = {}
    for instance in document.instances.values():
        asset = document.assets.get(instance.asset_ref)
        provenance = asset.provenance if asset is not None else {}
        if (
            provenance.get("operation") == "adopt_producer_derivative"
            and provenance.get("source_semantic") == semantic
            and provenance.get("source_bundle") == source_bundle
            and provenance.get("canonical_instance") == canonical_instance_id
        ):
            member = provenance.get("member")
            if member in {"left", "right"}:
                if member in matches:
                    raise DerivedCandidateError(
                        f"multiple {member} derivatives already exist for {semantic!r} from {source_bundle!r}"
                    )
                matches[member] = instance
    return matches


def _validate_pair_images(
    document,
    image_sources: dict,
    candidates: list[DerivedCandidate],
    *,
    reactivating: bool,
    existing_pair: dict[str, LayerInstance],
) -> None:
    canvas = document.composition.get("canvas") or {}
    width, height = canvas.get("width"), canvas.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise DerivedCandidateError("the Assembly canvas size is missing or invalid")

    source_record = document.sources.get(candidates[0].source_bundle)
    source_root = Path(source_record.path).resolve() if source_record and source_record.path else None
    for candidate in candidates:
        path = Path(candidate.path)
        if not path.is_file():
            raise DerivedCandidateError(f"{candidate.member} candidate image is unavailable: {path}")
        try:
            with Image.open(path) as raw:
                image = raw.convert("RGBA")
                if image.size != (width, height):
                    raise DerivedCandidateError(
                        f"{candidate.member} candidate canvas is {image.width}×{image.height}; "
                        f"Assembly canvas is {width}×{height}"
                    )
                if image.getchannel("A").getbbox() is None:
                    raise DerivedCandidateError(f"{candidate.member} candidate has no visible pixels")
        except (OSError, ValueError) as exc:
            if isinstance(exc, DerivedCandidateError):
                raise
            raise DerivedCandidateError(f"{candidate.member} candidate is not a readable image: {exc}") from exc

        if source_root is None or not source_root.exists() or source_root in path.resolve().parents:
            continue
        # After an Assembly save/reload, the adopted pixels are self-contained
        # under its layers/ directory. Allow those exact files for reactivation;
        # new candidates must still come from the selected producer bundle.
        matching_member = existing_pair.get(candidate.member) if reactivating else None
        stored_path = image_sources.get(matching_member.id) if matching_member is not None else None
        if stored_path is None or Path(stored_path).resolve() != path.resolve():
            raise DerivedCandidateError(
                f"{candidate.member} candidate is outside its declared source bundle {source_root}"
            )

def _safe_visual_ops(instance: LayerInstance) -> list[dict]:
    unsupported = [
        op.get("type", "unknown") for op in instance.visual_ops
        if op.get("type") != "color"
    ]
    if unsupported:
        raise DerivedCandidateError(
            "canonical layer has VisualOps that cannot be mapped to both derivatives: "
            + ", ".join(sorted(set(unsupported)))
        )
    return copy.deepcopy(instance.visual_ops)


def adopt_derived_split(
    document: "AssemblyDocument",
    image_sources: dict,
    candidates: Iterable[DerivedCandidate],
    *,
    canonical_instance_id: str | None = None,
) -> list[str]:
    """Adopt or reactivate one producer left/right pair atomically."""
    candidates = list(candidates)
    if not candidates:
        raise DerivedCandidateError("no derived candidates supplied")
    semantic = candidates[0].source_semantic
    if any(c.source_semantic != semantic or c.kind != "left_right" for c in candidates):
        raise DerivedCandidateError("adoption requires one left_right semantic group")
    by_member = {candidate.member: candidate for candidate in candidates}
    if len(by_member) != len(candidates) or set(by_member) != {"left", "right"}:
        raise DerivedCandidateError("adoption requires both geometric left and right candidates")
    source_bundle = by_member["left"].source_bundle
    if by_member["right"].source_bundle != source_bundle:
        raise DerivedCandidateError("left and right candidates must come from the same producer bundle")
    canonical_matches = _instances_for_semantic(document, semantic)
    if canonical_instance_id is None:
        if len(canonical_matches) != 1:
            raise DerivedCandidateError(
                f"choose the exact canonical instance for {semantic!r}; found {canonical_matches!r}"
            )
        canonical_instance_id = canonical_matches[0]
    if canonical_instance_id not in canonical_matches:
        raise DerivedCandidateError(
            f"{canonical_instance_id!r} is not a canonical instance for {semantic!r}"
        )
    source_instance_id = canonical_instance_id
    source_instance = document.instances[source_instance_id]
    existing_pair = _pair_instances(document, semantic, source_bundle, source_instance_id)
    if existing_pair and set(existing_pair) != {"left", "right"}:
        raise DerivedCandidateError(f"the saved derivative pair for {semantic!r} is incomplete")
    if existing_pair and all(instance.visible for instance in existing_pair.values()) and not source_instance.visible:
        return [existing_pair[member].id for member in ("left", "right")]
    _validate_pair_images(
        document,
        image_sources,
        candidates,
        reactivating=bool(existing_pair),
        existing_pair=existing_pair,
    )
    existing_pair_ids = {instance.id for instance in existing_pair.values()}
    other_active = [
        instance.id
        for instance in document.instances.values()
        if instance.id not in existing_pair_ids
        and (asset := document.assets.get(instance.asset_ref)) is not None
        and asset.provenance.get("operation") == "adopt_producer_derivative"
        and asset.provenance.get("canonical_instance") == source_instance_id
        and instance.visible
    ]
    if other_active:
        raise DerivedCandidateError(
            f"another derivative pair is already in use for {source_instance_id!r}: {other_active!r}; "
            "revert it before choosing a different source"
        )
    if not existing_pair:
        if source_instance.transform_link:
            raise DerivedCandidateError(
                f"canonical instance {source_instance_id!r} belongs to transform link "
                f"{source_instance.transform_link!r}; remove or resolve that link before splitting"
            )
        source_asset = document.assets.get(source_instance.asset_ref)
        if source_asset is None:
            raise DerivedCandidateError(f"canonical asset is missing for {source_instance_id!r}")
        if source_instance.plane is not None or len(source_asset.planes) > 1:
            raise DerivedCandidateError(
                f"canonical instance {source_instance_id!r} uses a multi-plane asset; "
                "the derivative-to-plane mapping is ambiguous"
            )
        visual_ops = _safe_visual_ops(source_instance)
    else:
        visual_ops = []

    revision = None
    source_record = document.sources.get(source_bundle)
    if source_record is not None:
        manifest = Path(source_record.path or "") / "manifest.json"
        if manifest.is_file():
            revision = content_hash(manifest)
    if revision is None:
        revision = "derived:" + source_bundle

    draw_order = list(document.composition.get("draw_order", []))
    original_index = draw_order.index(source_instance_id) if source_instance_id in draw_order else len(draw_order)
    inserted_ids: list[str] = []
    provenance_base = {
        "kind": "left_right",
        "source_semantic": semantic,
        "source_bundle": source_bundle,
        "canonical_instance": source_instance_id,
        "canonical_index": original_index,
        "canonical_visible": source_instance.visible,
        "canonical_in_draw_order": source_instance_id in draw_order,
    }

    pending_sources: dict[str, Path] = {}
    with document.transaction():
        if source_bundle not in document.sources:
            document.sources[source_bundle] = SourceAsset(source_id=source_bundle, path=None)
        source_instance.visible = False
        existing_ids = {instance.id for instance in existing_pair.values()}
        document.composition["draw_order"] = [
            item for item in draw_order if item != source_instance_id and item not in existing_ids
        ]
        insertion = original_index
        if existing_pair:
            inserted_ids = [existing_pair[member].id for member in ("left", "right")]
            for member, instance in existing_pair.items():
                instance.visible = True
                candidate = by_member[member]
                if instance.id not in image_sources:
                    pending_sources[instance.id] = Path(candidate.path)
            document.composition["draw_order"][insertion:insertion] = inserted_ids
        else:
            for offset, member in enumerate(("left", "right")):
                candidate = by_member[member]
                base_id = f"{semantic}.{member}"
                asset_id = base_id
                suffix = 2
                while asset_id in document.assets or f"{asset_id}__instance" in document.instances:
                    asset_id = f"{base_id}_{suffix}"
                    suffix += 1
                instance_id = f"{asset_id}__instance"
                asset = AssetDefinition(
                    id=asset_id,
                    semantic=asset_id,
                    source_binding=SourceBinding(
                        source_id=source_bundle,
                        revision=revision,
                        source_layer_id=_candidate_source_layer(candidate, source_record),
                        fallback_semantic=semantic,
                    ),
                    planes=[asset_id],
                    provenance={
                        "operation": "adopt_producer_derivative",
                        **provenance_base,
                        "member": member,
                    },
                )
                document.add_asset(asset)
                instance = LayerInstance(
                    id=instance_id,
                    asset_ref=asset_id,
                    slot=source_instance.slot,
                    draw_order=source_instance.draw_order + offset,
                    visible=True,
                    opacity=source_instance.opacity,
                    transform=type(source_instance.transform).from_dict(
                        source_instance.transform.to_dict()
                    ),
                    transform_link=None,
                    plane=None,
                    visual_ops=copy.deepcopy(visual_ops),
                )
                document.add_instance(instance)
                document.composition["draw_order"].insert(insertion + offset, instance_id)
                pending_sources[instance_id] = Path(candidate.path)
                document.provenance.record(
                    instance_id, operation="adopt_producer_derivative", sources=[source_bundle],
                    **provenance_base, member=member
                )
                document.provenance.record(
                    asset_id, operation="adopt_producer_derivative", sources=[source_bundle],
                    **provenance_base, member=member
                )
                inserted_ids.append(instance_id)
    # Keep the external source map atomic with the document transaction.
    image_sources.update(pending_sources)
    return inserted_ids


def _candidate_source_layer(candidate: DerivedCandidate, source_record: SourceAsset | None) -> str:
    path = Path(candidate.path).resolve()
    if source_record is not None and source_record.path:
        root = Path(source_record.path).resolve()
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return path.name


def revert_derived_split(
    document: "AssemblyDocument",
    image_sources: dict,
    source_semantic: str,
    *,
    source_bundle: str | None = None,
    canonical_instance_id: str | None = None,
) -> None:
    """Hide one adopted pair and restore its exact canonical source."""
    derived = [
        instance for instance in document.instances.values()
        if document.assets.get(instance.asset_ref) is not None
        and document.assets[instance.asset_ref].provenance.get("operation") == "adopt_producer_derivative"
        and document.assets[instance.asset_ref].provenance.get("source_semantic") == source_semantic
        and (source_bundle is None or document.assets[instance.asset_ref].provenance.get("source_bundle") == source_bundle)
        and (canonical_instance_id is None or document.assets[instance.asset_ref].provenance.get("canonical_instance") == canonical_instance_id)
    ]
    if not derived:
        raise DerivedCandidateError(f"no adopted producer split for {source_semantic!r}")
    pairs = {
        (
            document.assets[instance.asset_ref].provenance.get("source_bundle"),
            document.assets[instance.asset_ref].provenance.get("canonical_instance"),
        )
        for instance in derived
    }
    if len(pairs) != 1:
        raise DerivedCandidateError(
            f"choose the exact source bundle and canonical instance to revert {source_semantic!r}"
        )
    pair_source, source_instance_id = next(iter(pairs))
    pair = _pair_instances(document, source_semantic, pair_source, source_instance_id)
    if set(pair) != {"left", "right"}:
        raise DerivedCandidateError(f"the saved derivative pair for {source_semantic!r} is incomplete")
    derivative_ids = {instance.id for instance in pair.values()}
    for section in ("hierarchy", "variant_sets", "links", "rig_intent", "expressions", "donor_slots", "bake_plans"):
        reference = _find_reference(getattr(document, section, None), derivative_ids, section)
        if reference:
            raise DerivedCandidateError(
                f"cannot revert {source_semantic!r}: {section} reference at {reference}; "
                "remove or retarget that reference first"
            )
    source_instance_id = document.assets[derived[0].asset_ref].provenance["canonical_instance"]
    pair_provenance = document.assets[pair["left"].asset_ref].provenance
    original_index = int(pair_provenance.get("canonical_index", 0))
    canonical_visible = bool(pair_provenance.get("canonical_visible", True))
    canonical_in_draw_order = bool(pair_provenance.get("canonical_in_draw_order", True))
    with document.transaction():
        draw_order = [
            item for item in document.composition.get("draw_order", [])
            if item not in derivative_ids and item != source_instance_id
        ]
        for instance in pair.values():
            instance.visible = False
        canonical = document.instances.get(source_instance_id)
        if canonical is None:
            raise DerivedCandidateError(f"canonical instance missing: {source_instance_id!r}")
        canonical.visible = canonical_visible
        if canonical_in_draw_order:
            draw_order.insert(min(original_index, len(draw_order)), source_instance_id)
        document.composition["draw_order"] = draw_order


def _find_reference(value, targets: set[str], path: str) -> str | None:
    if isinstance(value, str):
        return path if value in targets else None
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key in targets:
                return f"{path}.{key}"
            found = _find_reference(child, targets, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            found = _find_reference(child, targets, f"{path}[{index}]")
            if found:
                return found
    return None
