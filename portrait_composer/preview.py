"""Transient proxy preview state (C6-C).

Preview values deliberately live outside ``AssemblyDocument``.  The UI can
update this object on every mouse move and render it through the canonical
Pillow evaluator; only the final release value is sent to a transactional
authoring command.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass
class PreviewState:
    active: bool = False
    transform_overrides: dict = field(default_factory=dict)
    visual_ops_overrides: dict = field(default_factory=dict)

    def begin(self) -> None:
        self.active = True
        self.transform_overrides.clear()
        self.visual_ops_overrides.clear()

    def set_transform(self, instance_id: str, transform) -> None:
        self.active = True
        self.transform_overrides[instance_id] = copy.deepcopy(transform)

    def set_visual_ops(self, instance_id: str, ops: list) -> None:
        self.active = True
        self.visual_ops_overrides[instance_id] = copy.deepcopy(ops)

    def clear(self) -> None:
        self.active = False
        self.transform_overrides.clear()
        self.visual_ops_overrides.clear()

    def snapshot(self) -> dict:
        return {
            "active": self.active,
            "transform_overrides": copy.deepcopy(self.transform_overrides),
            "visual_ops_overrides": copy.deepcopy(self.visual_ops_overrides),
        }

