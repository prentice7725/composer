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


ARTICULATION_CHANNELS = {
    "blink": ("eyes", "open", "closed", "eyes_state"),
    "viseme": ("mouth", "closed", "a", "i", "u", "e", "o", "mouth_viseme"),
}
EMOTION_CHANNELS = ("eye_form", "brow_state", "mouth_form", "overlay_state")


def _find_variant_set_for_instance(document, instance_id: str, preferred: str) -> str | None:
    if preferred in document.variant_sets and instance_id in document.variant_sets[preferred].get("members", []):
        return preferred
    for vs_id, variant_set in document.variant_sets.items():
        if instance_id in variant_set.get("members", []):
            return vs_id
    return None


def build_expression_intent(document) -> dict:
    """Build the explicit, AutoRig-facing expression meaning map.

    Composer stores ordinary VariantSets and donor slots.  This adapter makes
    their meaning explicit at the export boundary so AutoRig never has to
    infer blink/viseme or emotion channels from filenames and draw order.
    Runtime parameters and deformation remain downstream-owned.
    """
    slots = getattr(document, "donor_slots", {}) or {}
    articulation = {}
    for channel, spec in ARTICULATION_CHANNELS.items():
        family, *states = spec
        preferred = states.pop()
        entries = slots.get(family, {})
        mapped = {}
        variant_set_id = None
        for state in states:
            entry = entries.get(state)
            if not isinstance(entry, dict):
                continue
            instance_id = entry.get("source_instance")
            if instance_id not in document.instances:
                continue
            variant_set_id = variant_set_id or _find_variant_set_for_instance(document, instance_id, preferred)
            mapped[state] = instance_id
        if mapped:
            articulation[channel] = {
                "variant_set": variant_set_id,
                "states": mapped,
            }

    emotion_channels = {}
    for channel in EMOTION_CHANNELS:
        variant_set = document.variant_sets.get(channel)
        if variant_set is not None:
            emotion_channels[channel] = {
                "mode": "overlay" if channel == "overlay_state" else "authored_state",
                "variant_set": channel,
            }

    presets = {}
    for preset_id, preset in getattr(document, "expressions", {}).items():
        variants = preset.get("variants", {}) if isinstance(preset, dict) else {}
        channels = {
            channel: variants[ channel ]
            for channel in EMOTION_CHANNELS
            if channel in variants
        }
        if channels:
            metadata = preset.get("metadata", {}) if isinstance(preset, dict) else {}
            preserve = metadata.get("preserve", ["blink", "viseme"])
            presets[preset_id] = {
                **channels,
                "preserve": {
                    "blink": "blink" in preserve,
                    "viseme": "viseme" in preserve,
                },
            }

    return {
        "profile": "face_expression_core_v2",
        "articulation": articulation,
        "emotion_channels": emotion_channels,
        "presets": presets,
    }


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
    preset_metadata = {"preserve": ["blink", "viseme"]}
    if metadata:
        preset_metadata.update(dict(metadata))
    preset["metadata"] = preset_metadata
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
    preset_metadata = {"preserve": ["blink", "viseme"]}
    if metadata:
        preset_metadata.update(dict(metadata))
    updated["metadata"] = preset_metadata
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
