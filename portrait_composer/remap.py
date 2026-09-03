"""Reimport / remap classification.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #8;
SEETHROUGH_..._MASTER_v0.2.md #6.

When an upstream Portrait Bundle is re-harvested (new revision), each
existing AssetDefinition's binding is reclassified against the new bundle's
layers:

    EXACT_MATCH     same source_layer_id exists in the new bundle
    SEMANTIC_MATCH   no id match, but exactly one new layer shares semantic
    AMBIGUOUS        no id match, multiple new layers share semantic
    ORPHANED         no id match, no semantic match

AMBIGUOUS and ORPHANED are never auto-resolved ("silent guess 금지", #8) --
a caller must call ``apply_manual_remap`` explicitly, or the report stays
unresolved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .assets import AssetDefinition
from .bundle import PortraitBundle
from .document import AssemblyDocument
from .sources import SourceAsset, SourceBinding, content_hash

EXACT_MATCH = "EXACT_MATCH"
SEMANTIC_MATCH = "SEMANTIC_MATCH"
AMBIGUOUS = "AMBIGUOUS"
ORPHANED = "ORPHANED"


@dataclass
class RemapEntry:
    asset_id: str
    status: str
    candidates: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"asset_id": self.asset_id, "status": self.status, "candidates": list(self.candidates)}


@dataclass
class RemapReport:
    entries: list  # list[RemapEntry]

    @property
    def unresolved(self) -> list:
        return [e for e in self.entries if e.status in (AMBIGUOUS, ORPHANED)]

    @property
    def all_resolved(self) -> bool:
        return not self.unresolved

    def to_dict(self) -> dict:
        return {
            "resolved": self.all_resolved,
            "entries": [e.to_dict() for e in self.entries],
        }


def classify_remap(document: AssemblyDocument, new_bundle: PortraitBundle) -> RemapReport:
    by_id = {l.id: l for l in new_bundle.layers}
    by_semantic: dict[str, list] = {}
    for l in new_bundle.layers:
        by_semantic.setdefault(l.semantic, []).append(l)

    entries = []
    for asset_id, asset in document.assets.items():
        sb = asset.source_binding
        if sb is None:
            entries.append(RemapEntry(asset_id, ORPHANED, []))
            continue

        if sb.source_layer_id in by_id:
            entries.append(RemapEntry(asset_id, EXACT_MATCH, [sb.source_layer_id]))
            continue

        semantic = sb.fallback_semantic or asset.semantic
        candidates = by_semantic.get(semantic, [])
        if len(candidates) == 1:
            entries.append(RemapEntry(asset_id, SEMANTIC_MATCH, [candidates[0].id]))
        elif len(candidates) > 1:
            entries.append(RemapEntry(asset_id, AMBIGUOUS, [c.id for c in candidates]))
        else:
            entries.append(RemapEntry(asset_id, ORPHANED, []))

    return RemapReport(entries=entries)


def apply_auto_resolvable_remap(document: AssemblyDocument, new_bundle: PortraitBundle, report: RemapReport) -> None:
    """Applies EXACT_MATCH / SEMANTIC_MATCH entries (1 unambiguous candidate).
    Never touches AMBIGUOUS/ORPHANED entries -- those require
    ``apply_manual_remap``.
    """
    source_id = new_bundle.source.get("source_id", new_bundle.root.name)
    revision = content_hash(new_bundle.root / "manifest.json")
    by_id = {l.id: l for l in new_bundle.layers}

    with document.transaction():
        document.sources[source_id] = SourceAsset(source_id=source_id, path=str(new_bundle.root))
        for entry in report.entries:
            if entry.status not in (EXACT_MATCH, SEMANTIC_MATCH):
                continue
            new_layer = by_id[entry.candidates[0]]
            asset = document.assets[entry.asset_id]
            asset.source_binding = SourceBinding(
                source_id=source_id,
                revision=revision,
                source_layer_id=new_layer.id,
                fallback_semantic=new_layer.semantic,
            )
            document.provenance.record(
                entry.asset_id, operation="remap", sources=[source_id], status=entry.status
            )


def apply_manual_remap(document: AssemblyDocument, asset_id: str, new_bundle: PortraitBundle, chosen_layer_id: str) -> None:
    """Explicitly resolves one AMBIGUOUS/ORPHANED entry to a caller-chosen layer."""
    by_id = {l.id: l for l in new_bundle.layers}
    if chosen_layer_id not in by_id:
        raise KeyError(f"no such layer in new bundle: {chosen_layer_id!r}")
    new_layer = by_id[chosen_layer_id]
    source_id = new_bundle.source.get("source_id", new_bundle.root.name)
    revision = content_hash(new_bundle.root / "manifest.json")

    with document.transaction():
        if asset_id not in document.assets:
            raise KeyError(f"no such asset: {asset_id!r}")
        document.sources[source_id] = SourceAsset(source_id=source_id, path=str(new_bundle.root))
        asset = document.assets[asset_id]
        asset.source_binding = SourceBinding(
            source_id=source_id,
            revision=revision,
            source_layer_id=new_layer.id,
            fallback_semantic=new_layer.semantic,
        )
        document.provenance.record(asset_id, operation="remap", sources=[source_id], status="MANUAL")
