"""VariantSet authoring (C1).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #12;
SEETHROUGH_..._MASTER_v0.2.md #5.

C1 scope only, per the directive: exclusive membership, default member,
active member, validation, transaction/undo, serialization. Expression
donors adding members (C3) and AutoRig visibility/crossfade parameter
compilation (MASTER #5) are explicitly out of scope here.

``document.variant_sets`` shape (raw dict, validated in validation.py):

    {vs_id: {"mode": "exclusive", "default": member_id, "active": member_id,
              "members": [member_id, ...]}}

``members`` are LayerInstance ids. In ``exclusive`` mode, ``set_active``
also drives ``LayerInstance.visible`` for every member -- Composer must
always be able to render an accurate reference.png (directive #9), and
that means showing exactly the currently-active member, not all of them
at once. This is authoring-time visibility bookkeeping, not the
compiled AutoRig crossfade binding MASTER #5 describes for runtime.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument


class VariantSetError(Exception):
    pass


def add_variant_set(
    document: "AssemblyDocument",
    vs_id: str,
    *,
    members: list,
    default: str,
    mode: str = "exclusive",
) -> None:
    if vs_id in document.variant_sets:
        raise VariantSetError(f"variant set id already exists: {vs_id!r}")
    if default not in members:
        raise VariantSetError(f"variant set {vs_id!r}: default {default!r} not in members")
    for m in members:
        if m not in document.instances:
            raise VariantSetError(f"variant set {vs_id!r}: member {m!r} is not an instance")

    document.variant_sets[vs_id] = {
        "mode": mode,
        "default": default,
        "active": default,
        "members": list(members),
    }
    if mode == "exclusive":
        _apply_exclusive_visibility(document, vs_id)


def remove_variant_set(document: "AssemblyDocument", vs_id: str) -> None:
    if vs_id not in document.variant_sets:
        raise VariantSetError(f"no such variant set: {vs_id!r}")
    del document.variant_sets[vs_id]


def set_active(document: "AssemblyDocument", vs_id: str, member_id: str) -> None:
    """The "VariantSet exclusive 동작" operation: switches the active
    member and, in exclusive mode, shows only that member's instance."""
    vs = document.variant_sets.get(vs_id)
    if vs is None:
        raise VariantSetError(f"no such variant set: {vs_id!r}")
    if member_id not in vs["members"]:
        raise VariantSetError(f"variant set {vs_id!r}: {member_id!r} is not a member")

    vs["active"] = member_id
    if vs.get("mode") == "exclusive":
        _apply_exclusive_visibility(document, vs_id)


def _apply_exclusive_visibility(document: "AssemblyDocument", vs_id: str) -> None:
    vs = document.variant_sets[vs_id]
    active = vs["active"]
    for member_id in vs["members"]:
        inst = document.instances.get(member_id)
        if inst is not None:
            inst.visible = member_id == active
