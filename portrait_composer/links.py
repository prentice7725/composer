"""TransformLink relation (C1).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #11;
SEETHROUGH_..._MASTER_v0.2.md #4.

Instances that move/align together during Composer editing -- purely an
authoring convenience, unrelated to Hierarchy/Slot/VariantSet/RigIntent
(directive #11). ``LayerInstance.transform_link`` (instances.py) names the
link a given instance belongs to; this module owns the link group itself
and keeps both sides consistent.

``document.links`` shape:

    {link_id: {"members": [instance_id, ...]}}
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .instances import Transform

if TYPE_CHECKING:
    from .document import AssemblyDocument


class LinkError(Exception):
    pass


def create_link(document: "AssemblyDocument", link_id: str, member_instance_ids: list) -> None:
    """Creates a TransformLink group and stamps every member's
    ``transform_link`` -- the "transform link 생성" operation."""
    if link_id in document.links:
        raise LinkError(f"transform link id already exists: {link_id!r}")
    for inst_id in member_instance_ids:
        if inst_id not in document.instances:
            raise LinkError(f"transform link {link_id!r}: no such instance {inst_id!r}")

    document.links[link_id] = {"members": list(member_instance_ids)}
    for inst_id in member_instance_ids:
        document.instances[inst_id].transform_link = link_id


def dissolve_link(document: "AssemblyDocument", link_id: str) -> None:
    """Removes a TransformLink group and clears ``transform_link`` on every
    former member -- the "transform link 해제" operation."""
    link = document.links.get(link_id)
    if link is None:
        raise LinkError(f"no such transform link: {link_id!r}")
    for inst_id in link["members"]:
        inst = document.instances.get(inst_id)
        if inst is not None and inst.transform_link == link_id:
            inst.transform_link = None
    del document.links[link_id]


def add_member(document: "AssemblyDocument", link_id: str, instance_id: str) -> None:
    link = document.links.get(link_id)
    if link is None:
        raise LinkError(f"no such transform link: {link_id!r}")
    if instance_id not in document.instances:
        raise LinkError(f"transform link {link_id!r}: no such instance {instance_id!r}")
    if instance_id not in link["members"]:
        link["members"].append(instance_id)
    document.instances[instance_id].transform_link = link_id


def remove_member(document: "AssemblyDocument", link_id: str, instance_id: str) -> None:
    link = document.links.get(link_id)
    if link is None:
        raise LinkError(f"no such transform link: {link_id!r}")
    if instance_id in link["members"]:
        link["members"].remove(instance_id)
    inst = document.instances.get(instance_id)
    if inst is not None and inst.transform_link == link_id:
        inst.transform_link = None


def apply_delta(document: "AssemblyDocument", link_id: str, *, dx=0.0, dy=0.0, drotation=0.0) -> None:
    """Applies the same translate/rotate delta to every member's transform
    -- "move together" is the entire point of a TransformLink."""
    link = document.links.get(link_id)
    if link is None:
        raise LinkError(f"no such transform link: {link_id!r}")
    for inst_id in link["members"]:
        inst = document.instances.get(inst_id)
        if inst is None:
            continue
        inst.transform.x += dx
        inst.transform.y += dy
        inst.transform.rotation += drotation
