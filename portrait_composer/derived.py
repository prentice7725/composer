"""Producer-derived candidates and explicit left/right adoption.

The producer's ``derived/`` tree is an optional candidate source.  This module
keeps discovery side-effect free and puts document mutation behind one
transaction so adopt, undo/redo, save/reload, and revert have deterministic
semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

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


def _instance_for_semantic(document: "AssemblyDocument", semantic: str) -> str:
    matches = [
        instance_id
        for instance_id, instance in document.instances.items()
        if (document.assets.get(instance.asset_ref) is not None
            and document.assets[instance.asset_ref].semantic == semantic
            and not document.assets[instance.asset_ref].provenance.get("operation") == "adopt_producer_derivative")
    ]
    if len(matches) != 1:
        raise DerivedCandidateError(
            f"expected exactly one canonical instance for {semantic!r}, found {matches!r}"
        )
    return matches[0]


def adopt_derived_split(
    document: "AssemblyDocument",
    image_sources: dict,
    candidates: Iterable[DerivedCandidate],
) -> list[str]:
    """Adopt one producer left/right pair as an atomic document edit."""
    candidates = list(candidates)
    if not candidates:
        raise DerivedCandidateError("no derived candidates supplied")
    semantic = candidates[0].source_semantic
    if any(c.source_semantic != semantic or c.kind != "left_right" for c in candidates):
        raise DerivedCandidateError("adoption requires one left_right semantic group")
    by_member = {candidate.member: candidate for candidate in candidates}
    if set(by_member) != {"left", "right"}:
        raise DerivedCandidateError("adoption requires both geometric left and right candidates")
    source_instance_id = _instance_for_semantic(document, semantic)
    source_instance = document.instances[source_instance_id]
    if any(
        asset.provenance.get("operation") == "adopt_producer_derivative"
        and asset.provenance.get("source_semantic") == semantic
        for asset in document.assets.values()
    ):
        raise DerivedCandidateError(f"producer split already adopted for {semantic!r}")

    source_bundle = by_member["left"].source_bundle
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
    }

    pending_sources: dict[str, Path] = {}
    with document.transaction():
        if source_bundle not in document.sources:
            document.sources[source_bundle] = SourceAsset(source_id=source_bundle, path=None)
        source_instance.visible = False
        document.composition["draw_order"] = [item for item in draw_order if item != source_instance_id]
        insertion = original_index
        for offset, member in enumerate(("left", "right")):
            candidate = by_member[member]
            asset_id = f"{semantic}.{member}"
            instance_id = f"{asset_id}__instance"
            if asset_id in document.assets or instance_id in document.instances:
                raise DerivedCandidateError(f"derived id already exists: {asset_id!r}")
            asset = AssetDefinition(
                id=asset_id,
                semantic=asset_id,
                source_binding=SourceBinding(
                    source_id=source_bundle,
                    revision=revision,
                    source_layer_id=str(
                        candidate.path.relative_to(Path(source_record.path).resolve())
                        if source_record and source_record.path else candidate.path.name
                    ).replace("\\", "/"),
                    fallback_semantic=semantic,
                ),
                planes=[asset_id],
                provenance={
                    "operation": "adopt_producer_derivative",
                    **provenance_base,
                    "member": member,
                    "path": str(candidate.path),
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
            )
            document.add_instance(instance)
            document.composition["draw_order"].insert(insertion + offset, instance_id)
            pending_sources[instance_id] = candidate.path
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


def revert_derived_split(document: "AssemblyDocument", image_sources: dict, source_semantic: str) -> None:
    """Hide an adopted pair and restore its canonical source in one edit."""
    derived = [
        instance for instance in document.instances.values()
        if document.assets.get(instance.asset_ref) is not None
        and document.assets[instance.asset_ref].provenance.get("operation") == "adopt_producer_derivative"
        and document.assets[instance.asset_ref].provenance.get("source_semantic") == source_semantic
    ]
    if not derived:
        raise DerivedCandidateError(f"no adopted producer split for {source_semantic!r}")
    derivative_ids = {instance.id for instance in derived}
    for variant_id, variant in document.variant_sets.items():
        if derivative_ids & set(variant.get("members", [])):
            raise DerivedCandidateError(f"cannot revert {source_semantic!r}: VariantSet {variant_id!r} references it")
    for ref, scope in document.rig_intent.get("deformation_scopes", {}).items():
        if ref in derivative_ids and scope == "independent":
            raise DerivedCandidateError(f"cannot revert {source_semantic!r}: RigIntent references {ref!r}")

    source_instance_id = document.assets[derived[0].asset_ref].provenance["canonical_instance"]
    original_index = int(document.assets[derived[0].asset_ref].provenance.get("canonical_index", 0))
    with document.transaction():
        draw_order = [item for item in document.composition.get("draw_order", []) if item not in derivative_ids]
        for instance in derived:
            instance.visible = False
        canonical = document.instances.get(source_instance_id)
        if canonical is None:
            raise DerivedCandidateError(f"canonical instance missing: {source_instance_id!r}")
        canonical.visible = True
        draw_order.insert(min(original_index, len(draw_order)), source_instance_id)
        document.composition["draw_order"] = draw_order
