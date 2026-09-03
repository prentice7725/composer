"""LayerInstance.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #6, #13.

A placement of an AssetDefinition into a specific character's assembly.
Assets are never copied -- instances reference them by id (``asset_ref``).

``slot`` is a placement vocabulary term (see slots.py), not a semantic
label -- see directive #13: "slot은 semantic이 아니다".

``plane`` (C1, directive #14) says which of the asset's ``planes`` this
instance renders, for a multi-plane AssetDefinition (e.g. one "uniform"
asset with sleeve_back/torso/sleeve_front planes placed into three
different slots by three different instances). ``None`` means "the
asset's one and only plane" -- true for every C0/C0.5 identity-imported
instance, since Portrait Bundle v1 layers are single-plane. It's bookkeeping
only: which pixel content backs an instance is decided by whatever image
ends up in that instance's ``image_sources`` entry at write time (harvest/
bake), not derived from ``plane`` at render time -- see validation.py's
plane-membership check and assembly.py's harvest/bake helpers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0

    def is_identity(self) -> bool:
        return (
            self.x == 0.0
            and self.y == 0.0
            and self.scale_x == 1.0
            and self.scale_y == 1.0
            and self.rotation == 0.0
        )

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "rotation": self.rotation,
        }

    @staticmethod
    def from_dict(d: dict) -> "Transform":
        return Transform(
            x=d.get("x", 0.0),
            y=d.get("y", 0.0),
            scale_x=d.get("scale_x", 1.0),
            scale_y=d.get("scale_y", 1.0),
            rotation=d.get("rotation", 0.0),
        )


@dataclass
class LayerInstance:
    id: str
    asset_ref: str
    slot: str
    draw_order: int
    visible: bool = True
    opacity: float = 1.0
    transform: Transform = field(default_factory=Transform)
    transform_link: Optional[str] = None
    plane: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_ref": self.asset_ref,
            "slot": self.slot,
            "draw_order": self.draw_order,
            "visible": self.visible,
            "opacity": self.opacity,
            "transform": self.transform.to_dict(),
            "transform_link": self.transform_link,
            "plane": self.plane,
        }

    @staticmethod
    def from_dict(d: dict) -> "LayerInstance":
        return LayerInstance(
            id=d["id"],
            asset_ref=d["asset_ref"],
            slot=d["slot"],
            draw_order=d["draw_order"],
            visible=d.get("visible", True),
            opacity=d.get("opacity", 1.0),
            transform=Transform.from_dict(d.get("transform", {})),
            transform_link=d.get("transform_link"),
            plane=d.get("plane"),
        )
