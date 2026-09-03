"""Source model.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #7-8,
SEETHROUGH_..._MASTER_v0.2.md #3, #6.

    SourceAsset -> SourceRevision -> SourceBinding

SourceRevision is content-hash based. SourceBinding is what an
AssetDefinition actually references: (source_id, revision, source_layer_id,
fallback_semantic).

Remap classification lives in ``remap.py`` -- this module only defines the
data shapes and the hashing primitive they are built on.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def content_hash(path: Path) -> str:
    """Stable content hash for a source file, used as a SourceRevision id."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


@dataclass
class SourceAsset:
    """A Portrait Bundle (or other upstream artifact) Composer harvested from."""

    source_id: str
    path: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "path": self.path, "metadata": dict(self.metadata)}

    @staticmethod
    def from_dict(d: dict) -> "SourceAsset":
        return SourceAsset(source_id=d["source_id"], path=d.get("path"), metadata=dict(d.get("metadata", {})))


@dataclass
class SourceRevision:
    """A specific, content-addressed state of a SourceAsset."""

    source_id: str
    revision: str  # e.g. "sha256:..."

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "revision": self.revision}

    @staticmethod
    def from_dict(d: dict) -> "SourceRevision":
        return SourceRevision(source_id=d["source_id"], revision=d["revision"])


@dataclass
class SourceBinding:
    """What an AssetDefinition actually points at, upstream.

    ``fallback_semantic`` is what remap falls back to matching on when the
    exact (source_id, revision, source_layer_id) triple no longer resolves.
    """

    source_id: str
    revision: str
    source_layer_id: str
    fallback_semantic: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "revision": self.revision,
            "source_layer_id": self.source_layer_id,
            "fallback_semantic": self.fallback_semantic,
        }

    @staticmethod
    def from_dict(d: dict) -> "SourceBinding":
        return SourceBinding(
            source_id=d["source_id"],
            revision=d["revision"],
            source_layer_id=d["source_layer_id"],
            fallback_semantic=d.get("fallback_semantic"),
        )
