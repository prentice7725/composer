"""AssetDefinition.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #5, #14.

A reusable visual atom. It does NOT own character placement state -- that is
LayerInstance's job (see instances.py). One AssetDefinition may expose
multiple ``planes`` that different LayerInstances place into different slots
(see #14 Multi-Plane Asset).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .sources import SourceBinding


@dataclass
class AssetDefinition:
    id: str
    semantic: str
    source_binding: Optional[SourceBinding] = None
    planes: list = field(default_factory=list)
    compatibility: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "semantic": self.semantic,
            "source_binding": self.source_binding.to_dict() if self.source_binding else None,
            "planes": list(self.planes),
            "compatibility": dict(self.compatibility),
            "provenance": dict(self.provenance),
        }

    @staticmethod
    def from_dict(d: dict) -> "AssetDefinition":
        sb = d.get("source_binding")
        return AssetDefinition(
            id=d["id"],
            semantic=d["semantic"],
            source_binding=SourceBinding.from_dict(sb) if sb else None,
            planes=list(d.get("planes", [])),
            compatibility=dict(d.get("compatibility", {})),
            provenance=dict(d.get("provenance", {})),
        )
