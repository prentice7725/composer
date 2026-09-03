"""Hierarchy relation (C1).

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #11;
SEETHROUGH_..._MASTER_v0.2.md #4.

An editing/organizational tree over instances -- a layers-panel grouping,
not a render or motion concept. Deliberately kept separate from
Slot/TransformLink/VariantSet/RigIntent (directive #11, MASTER #4:
"이 다섯 개를 하나의 parent/group 개념으로 합치지 않는다").

``document.hierarchy`` shape:

    {
      "nodes": {
        node_id: {"parent": parent_node_id | None, "ref": instance_id | None, "label": str | None},
        ...
      },
      "children": {
        parent_node_id_or_"": [child_node_id, ...],   # "" is the root level
        ...
      }
    }

A node with ``ref`` set represents one LayerInstance's position in the
tree; a node with ``ref=None`` is a pure organizational group (e.g. a
"Upper Body" folder with no render meaning of its own).
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument

ROOT = ""  # the "" key in document.hierarchy["children"] is the root level


class HierarchyError(Exception):
    pass


def _ensure_shape(document: "AssemblyDocument") -> None:
    document.hierarchy.setdefault("nodes", {})
    document.hierarchy.setdefault("children", {})


def add_node(
    document: "AssemblyDocument",
    node_id: str,
    *,
    parent: Optional[str] = None,
    ref: Optional[str] = None,
    label: Optional[str] = None,
    index: Optional[int] = None,
) -> None:
    """Adds one node under ``parent`` (``None`` = root level), at ``index``
    among its new siblings (default: appended last)."""
    _ensure_shape(document)
    nodes = document.hierarchy["nodes"]
    if node_id in nodes:
        raise HierarchyError(f"hierarchy node id already exists: {node_id!r}")
    if parent is not None and parent not in nodes:
        raise HierarchyError(f"hierarchy parent does not exist: {parent!r}")

    nodes[node_id] = {"parent": parent, "ref": ref, "label": label}
    siblings = document.hierarchy["children"].setdefault(parent or ROOT, [])
    if index is None:
        siblings.append(node_id)
    else:
        siblings.insert(index, node_id)


def remove_node(document: "AssemblyDocument", node_id: str) -> None:
    """Removes one node. Its children are reparented to its own parent
    (non-destructive -- removing a group folder doesn't delete what's in
    it)."""
    _ensure_shape(document)
    nodes = document.hierarchy["nodes"]
    if node_id not in nodes:
        raise HierarchyError(f"no such hierarchy node: {node_id!r}")

    parent = nodes[node_id]["parent"]
    children_map = document.hierarchy["children"]

    old_siblings = children_map.get(parent or ROOT, [])
    if node_id in old_siblings:
        old_siblings.remove(node_id)

    for child_id in children_map.pop(node_id, []):
        nodes[child_id]["parent"] = parent
        children_map.setdefault(parent or ROOT, []).append(child_id)

    del nodes[node_id]


def move_node(
    document: "AssemblyDocument", node_id: str, *, new_parent: Optional[str] = None, index: Optional[int] = None
) -> None:
    """Reparents/repositions ``node_id`` -- the "hierarchy reorder" operation."""
    _ensure_shape(document)
    nodes = document.hierarchy["nodes"]
    if node_id not in nodes:
        raise HierarchyError(f"no such hierarchy node: {node_id!r}")
    if new_parent is not None and new_parent not in nodes:
        raise HierarchyError(f"hierarchy parent does not exist: {new_parent!r}")
    if new_parent == node_id:
        raise HierarchyError("a hierarchy node cannot be its own parent")

    children_map = document.hierarchy["children"]
    old_parent = nodes[node_id]["parent"]
    old_siblings = children_map.get(old_parent or ROOT, [])
    if node_id in old_siblings:
        old_siblings.remove(node_id)

    nodes[node_id]["parent"] = new_parent
    new_siblings = children_map.setdefault(new_parent or ROOT, [])
    if index is None:
        new_siblings.append(node_id)
    else:
        new_siblings.insert(index, node_id)


def children_of(document: "AssemblyDocument", node_id: Optional[str] = None) -> list:
    _ensure_shape(document)
    return list(document.hierarchy["children"].get(node_id or ROOT, []))


def validate_hierarchy(document: "AssemblyDocument") -> list:
    """Returns a list of hard-error strings (missing parent, cycle, dangling
    ref, orphaned children-list entry). Called from validation.py."""
    errors: list[str] = []
    nodes = document.hierarchy.get("nodes", {})
    children_map = document.hierarchy.get("children", {})

    for node_id, node in nodes.items():
        parent = node.get("parent")
        if parent is not None and parent not in nodes:
            errors.append(f"hierarchy node {node_id!r}: missing parent {parent!r}")
        ref = node.get("ref")
        if ref is not None and ref not in document.instances:
            errors.append(f"hierarchy node {node_id!r}: ref {ref!r} is not an instance")

    for parent_key, child_ids in children_map.items():
        for child_id in child_ids:
            if child_id not in nodes:
                errors.append(f"hierarchy children[{parent_key!r}]: unknown node {child_id!r}")

    # cycle detection: walk parent pointers from every node, bounded by node count
    limit = len(nodes) + 1
    for node_id in nodes:
        seen = {node_id}
        current = nodes[node_id].get("parent")
        steps = 0
        while current is not None:
            if current in seen or steps > limit:
                errors.append(f"hierarchy cycle detected involving {node_id!r}")
                break
            seen.add(current)
            current = nodes.get(current, {}).get("parent")
            steps += 1

    return errors
