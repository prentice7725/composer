"""Slot / Plane vocabulary (C1).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #13-14.

Slot is a placement/render-plane vocabulary, not a semantic label
(directive #13: "slot은 semantic이 아니다") -- distinct from an
AssetDefinition's ``semantic`` (assets.py) and from a Portrait Bundle
layer's SEMANTIC_Z_ORDER tag (bundle.py). A LayerInstance's ``slot`` says
*where it renders*; its asset's ``semantic`` says *what it is*.

``SLOT_VOCABULARY`` is the directive's initial vocabulary (#13) -- open,
not closed: an unrecognized slot is a validation *warning*
(validation.py), not a hard error, since this is deliberately an "초기
vocabulary" a project can extend.

A multi-plane AssetDefinition (directive #14 -- one asset whose different
``planes`` land in different slots, e.g. a uniform's sleeve_back/torso/
sleeve_front) is placed by giving each LayerInstance a distinct
``slot`` + ``plane`` pair, all sharing one ``asset_ref``.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument

SLOT_VOCABULARY = (
    "body_back",
    "hair_back",
    "torso_back",
    "torso",
    "torso_front",
    "neck",
    "head",
    "face",
    "eye",
    "mouth",
    "accessory_front",
    "hair_front",
    "headwear",
)


class SlotError(Exception):
    pass


def is_known_slot(slot: str) -> bool:
    return slot in SLOT_VOCABULARY


def set_slot(document: "AssemblyDocument", instance_id: str, slot: str) -> None:
    """The "slot 변경" operation. Does not enforce SLOT_VOCABULARY membership
    (that's a validation warning, not a hard error) -- only that the
    instance exists."""
    inst = document.instances.get(instance_id)
    if inst is None:
        raise SlotError(f"no such instance: {instance_id!r}")
    inst.slot = slot


def set_plane(document: "AssemblyDocument", instance_id: str, plane: Optional[str]) -> None:
    """Assigns which of the asset's declared ``planes`` this instance
    renders (directive #14). ``plane=None`` means "the asset's one and
    only plane". Membership in ``asset.planes`` is enforced by
    validation.py, not here, so this stays usable mid-transaction."""
    inst = document.instances.get(instance_id)
    if inst is None:
        raise SlotError(f"no such instance: {instance_id!r}")
    inst.plane = plane
