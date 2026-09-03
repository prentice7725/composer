"""RigIntent authoring (C4).

RigIntent is deliberately a small authoring contract.  It records what a
Composer author permits downstream to move and how two authored objects are
related; it does not calculate constraints, meshes, weights, or physics.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument

DEFORMATION_SCOPES = ("baked", "rigid", "local", "independent", "secondary")
ATTACHMENT_MODES = ("weld", "hinge", "free", "follow")
# Stable Composer logical surfaces used by export-profile authoring.  These
# are labels, not slots and not runtime rig objects.
LOGICAL_SURFACES = ("topwear_with_arms",)


class RigIntentError(ValueError):
    """Raised for an invalid RigIntent authoring operation."""


def _ensure_shape(document: "AssemblyDocument") -> dict:
    intent = document.rig_intent
    if not isinstance(intent, dict):
        intent = {}
        document.rig_intent = intent
    intent.setdefault("regions", {})
    intent.setdefault("attachments", {})
    intent.setdefault("deformation_scopes", {})
    return intent


def set_deformation_scope(document: "AssemblyDocument", target: str, scope: str) -> None:
    """Author the allowed deformation scope for an instance or slot.

    The key is intentionally allowed to be a slot (for example
    ``topwear_with_arms``) because C2 profile analysis may operate on a
    logical surface before a derived instance is created.
    """
    if not target:
        raise RigIntentError("deformation scope target must be non-empty")
    if scope not in DEFORMATION_SCOPES:
        raise RigIntentError(f"unknown deformation_scope {scope!r}; expected one of {DEFORMATION_SCOPES!r}")
    _ensure_shape(document)["deformation_scopes"][target] = scope


def clear_deformation_scope(document: "AssemblyDocument", target: str) -> None:
    _ensure_shape(document)["deformation_scopes"].pop(target, None)


def add_attachment(
    document: "AssemblyDocument",
    attachment_id: str,
    *,
    child: str,
    target: str,
    mode: str,
) -> None:
    """Author an attachment relationship; AutoRig owns constraint math."""
    if not attachment_id:
        raise RigIntentError("attachment id must be non-empty")
    if mode not in ATTACHMENT_MODES:
        raise RigIntentError(f"unknown attachment mode {mode!r}; expected one of {ATTACHMENT_MODES!r}")
    if not child or not target:
        raise RigIntentError("attachment child and target must be non-empty")
    intent = _ensure_shape(document)
    if attachment_id in intent["attachments"]:
        raise RigIntentError(f"attachment id already exists: {attachment_id!r}")
    intent["attachments"][attachment_id] = {"child": child, "target": target, "mode": mode}


def set_attachment(
    document: "AssemblyDocument",
    attachment_id: str,
    *,
    child: str,
    target: str,
    mode: str,
) -> None:
    """Create or replace one attachment intent."""
    if mode not in ATTACHMENT_MODES:
        raise RigIntentError(f"unknown attachment mode {mode!r}; expected one of {ATTACHMENT_MODES!r}")
    if not child or not target:
        raise RigIntentError("attachment child and target must be non-empty")
    _ensure_shape(document)["attachments"][attachment_id] = {
        "child": child,
        "target": target,
        "mode": mode,
    }


def remove_attachment(document: "AssemblyDocument", attachment_id: str) -> None:
    intent = _ensure_shape(document)
    if attachment_id not in intent["attachments"]:
        raise RigIntentError(f"no such attachment: {attachment_id!r}")
    del intent["attachments"][attachment_id]


# Explicit aliases make the operation names convenient for GUI/CLI adapters.
author_deformation_scope = set_deformation_scope
author_attachment = add_attachment
set_scope = set_deformation_scope
create_attachment = add_attachment
