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


def add_member(document: "AssemblyDocument", vs_id: str, member_id: str, *, activate: bool = False) -> None:
    """Add one existing LayerInstance to a VariantSet (C3 donor support)."""
    vs = document.variant_sets.get(vs_id)
    if vs is None:
        raise VariantSetError(f"no such variant set: {vs_id!r}")
    if member_id not in document.instances:
        raise VariantSetError(f"variant set {vs_id!r}: member {member_id!r} is not an instance")
    if member_id not in vs["members"]:
        vs["members"].append(member_id)
    if vs.get("mode") == "exclusive" and member_id != vs.get("active"):
        # Preserve the authoring/reference invariant: adding an expression
        # donor must not make two exclusive variants render simultaneously.
        document.instances[member_id].visible = False
    if activate:
        set_active(document, vs_id, member_id)


def configure_state_groups(
    document: "AssemblyDocument",
    vs_id: str,
    groups: dict[str, list[str]],
    *,
    default: str | None = None,
    active: str | None = None,
) -> None:
    """Attach optional multi-layer state groups to an exclusive VariantSet.

    A facial state can be a stack (``eyewhite + irides + eyelash``), while a
    VariantSet's public members remain ordinary LayerInstance ids.  The
    optional ``state_groups`` extension keeps that stack atomic for
    authoring/reference visibility without introducing runtime parameters.
    """
    vs = document.variant_sets.get(vs_id)
    if vs is None:
        raise VariantSetError(f"no such variant set: {vs_id!r}")
    normalized: dict[str, list[str]] = {}
    all_group_members: list[str] = []
    for state, member_ids in groups.items():
        if not state:
            raise VariantSetError("VariantSet state name must be non-empty")
        unique = list(dict.fromkeys(member_ids))
        for member_id in unique:
            if member_id not in document.instances:
                raise VariantSetError(f"variant set {vs_id!r}: state member {member_id!r} is not an instance")
        normalized[state] = unique
        all_group_members.extend(unique)

    members = list(dict.fromkeys([*vs.get("members", []), *all_group_members]))
    if not members:
        raise VariantSetError(f"variant set {vs_id!r}: state groups need at least one member")
    vs["members"] = members
    vs["state_groups"] = normalized
    default = default or vs.get("default") or members[0]
    active = active or vs.get("active") or default
    if default not in members:
        raise VariantSetError(f"variant set {vs_id!r}: default {default!r} not in members")
    if active not in members:
        raise VariantSetError(f"variant set {vs_id!r}: active {active!r} not in members")
    vs["default"] = default
    vs["active"] = active
    _apply_exclusive_visibility(document, vs_id)


def create_or_add_member(
    document: "AssemblyDocument", vs_id: str, member_id: str, *, default: bool = False
) -> None:
    """Create a standard exclusive set when absent, otherwise append a member."""
    if vs_id not in document.variant_sets:
        add_variant_set(document, vs_id, members=[member_id], default=member_id)
    else:
        add_member(document, vs_id, member_id, activate=default)


def remove_member(document: "AssemblyDocument", vs_id: str, member_id: str) -> None:
    """Remove one member from a VariantSet (C5-D drag-out / context action,
    directive #9.2). Reassigns ``default``/``active`` to another remaining
    member if the removed one held either -- a VariantSet must always be
    able to render something, so it can never be left with zero members."""
    vs = document.variant_sets.get(vs_id)
    if vs is None:
        raise VariantSetError(f"no such variant set: {vs_id!r}")
    if member_id not in vs["members"]:
        raise VariantSetError(f"variant set {vs_id!r}: {member_id!r} is not a member")
    if len(vs["members"]) <= 1:
        raise VariantSetError(f"variant set {vs_id!r}: cannot remove its only member")

    vs["members"].remove(member_id)
    if vs.get("default") == member_id:
        vs["default"] = vs["members"][0]
    if vs.get("active") == member_id:
        set_active(document, vs_id, vs["members"][0])


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
    state_groups = vs.get("state_groups") or {}
    active_group = next(
        (set(member_ids) for member_ids in state_groups.values() if active in member_ids),
        {active},
    )
    grouped_members = {member_id for member_ids in state_groups.values() for member_id in member_ids}
    for member_id in vs["members"]:
        inst = document.instances.get(member_id)
        if inst is not None:
            inst.visible = member_id in active_group
    # Keep group members that were added as a visibility stack but are not
    # exposed as selectable VariantSet members in sync as well.
    for member_id in grouped_members - set(vs["members"]):
        inst = document.instances.get(member_id)
        if inst is not None:
            inst.visible = member_id in active_group
