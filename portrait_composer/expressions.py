"""Expression authoring as a thin VariantSet layer (C3).

There is intentionally no expression parameter system here.  An expression
preset only selects members from existing VariantSets; runtime parameter
binding and crossfade compilation belong to AutoRig.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument


class ExpressionError(ValueError):
    pass


def _run_authoring(document: "AssemblyDocument", operation):
    if document.in_transaction:
        return operation()
    with document.transaction():
        return operation()


def create_expression_preset(
    document: "AssemblyDocument",
    preset_id: str,
    variants: dict[str, str],
    *,
    metadata: dict | None = None,
) -> dict:
    """Create ``{variant_set_id: member_id}`` selections.

    ``metadata`` is authoring metadata only.  It is not interpreted as an
    AutoRig parameter binding.
    """
    if not preset_id:
        raise ExpressionError("expression preset id must be non-empty")
    if not isinstance(variants, dict) or not variants:
        raise ExpressionError("expression preset needs at least one VariantSet selection")
    canonical_variants = {}
    aliases = {
        "eye_state": "eyes_state",
        "eyes_state": "eye_state",
        "mouth_viseme": "mouth_state",
        "mouth_state": "mouth_viseme",
        "eyes": "eyes_state",
        "brows": "brow_state",
    }
    for set_id, member_id in variants.items():
        lookup_id = set_id if set_id in document.variant_sets else aliases.get(set_id, set_id)
        variant_set = document.variant_sets.get(lookup_id)
        if variant_set is None:
            raise ExpressionError(f"no such variant set: {set_id!r}")
        if member_id not in variant_set.get("members", []):
            raise ExpressionError(f"{member_id!r} is not a member of variant set {set_id!r}")
        canonical_variants[lookup_id] = member_id
    preset = {"variants": canonical_variants}
    if metadata:
        preset["metadata"] = dict(metadata)
    def mutate():
        if preset_id in document.expressions:
            raise ExpressionError(f"expression preset id already exists: {preset_id!r}")
        document.expressions[preset_id] = preset
    _run_authoring(document, mutate)
    return preset


def update_expression_preset(
    document: "AssemblyDocument", preset_id: str, variants: dict[str, str], *, metadata: dict | None = None
) -> dict:
    if preset_id not in document.expressions:
        raise ExpressionError(f"no such expression preset: {preset_id!r}")
    # Validate through the same rules as create, without deleting the old
    # preset first.  This keeps a failed direct edit atomic as well as when
    # the caller wraps it in AssemblyDocument.transaction().
    aliases = {
        "eye_state": "eyes_state",
        "eyes_state": "eye_state",
        "mouth_viseme": "mouth_state",
        "mouth_state": "mouth_viseme",
        "eyes": "eyes_state",
        "brows": "brow_state",
    }
    canonical_variants = {}
    for set_id, member_id in variants.items():
        lookup_id = set_id if set_id in document.variant_sets else aliases.get(set_id, set_id)
        variant_set = document.variant_sets.get(lookup_id)
        if variant_set is None or member_id not in variant_set.get("members", []):
            raise ExpressionError(f"{member_id!r} is not a member of variant set {set_id!r}")
        canonical_variants[lookup_id] = member_id
    updated = {"variants": canonical_variants}
    if metadata:
        updated["metadata"] = dict(metadata)
    _run_authoring(document, lambda: document.expressions.__setitem__(preset_id, updated))
    return updated


def remove_expression_preset(document: "AssemblyDocument", preset_id: str) -> None:
    if preset_id not in document.expressions:
        raise ExpressionError(f"no such expression preset: {preset_id!r}")
    _run_authoring(document, lambda: document.expressions.__delitem__(preset_id))


def apply_expression_preset(document: "AssemblyDocument", preset_id: str) -> None:
    """Select the preset's VariantSet members for authoring/reference render."""
    from .variants import set_active

    preset = document.expressions.get(preset_id)
    if preset is None:
        raise ExpressionError(f"no such expression preset: {preset_id!r}")
    def mutate():
        for set_id, member_id in preset["variants"].items():
            set_active(document, set_id, member_id)
    _run_authoring(document, mutate)


add_expression_preset = create_expression_preset
