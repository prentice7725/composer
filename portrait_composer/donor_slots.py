"""Structured face-expression donor slots owned by Composer.

The slot board is intentionally a small authoring contract.  It records which
Composer instance supplies a canonical eye/mouth state; it does not create
runtime parameters or prescribe AutoRig deformation.
"""
from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import AssemblyDocument

DONOR_PROFILE = "face_expression_core_v1"
EYE_SLOTS = ("open", "closed")
MOUTH_SLOTS = ("closed", "a", "i", "u", "e", "o")
SLOT_STATUSES = ("EMPTY", "SELECTED", "REVIEW", "READY", "WARNING")


def default_donor_slots() -> dict:
    return {
        "donor_profile": DONOR_PROFILE,
        "eyes": {slot: None for slot in EYE_SLOTS},
        "mouth": {slot: None for slot in MOUTH_SLOTS},
    }


def _canonical(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_donor_slots(value: dict | None) -> dict:
    """Return a defensive, canonical slot map and reject malformed data."""
    if value is None:
        return default_donor_slots()
    if not isinstance(value, dict):
        raise ValueError("donor_slots must be an object")
    profile = value.get("donor_profile", DONOR_PROFILE)
    if profile != DONOR_PROFILE:
        raise ValueError(f"unsupported donor profile: {profile!r}")
    result = default_donor_slots()
    result["donor_profile"] = profile
    for family, allowed in (("eyes", EYE_SLOTS), ("mouth", MOUTH_SLOTS)):
        entries = value.get(family, {})
        if not isinstance(entries, dict):
            raise ValueError(f"donor_slots.{family} must be an object")
        for slot in allowed:
            entry = entries.get(slot)
            if entry is None:
                continue
            if isinstance(entry, str):
                entry = {"source_instance": entry}
            if not isinstance(entry, dict) or not entry.get("source_instance"):
                raise ValueError(f"donor_slots.{family}.{slot} needs source_instance")
            status = entry.get("status", "READY")
            if status not in SLOT_STATUSES:
                raise ValueError(f"invalid donor slot status: {status!r}")
            result[family][slot] = copy.deepcopy(entry)
            result[family][slot]["source_instance"] = str(entry["source_instance"])
            result[family][slot]["status"] = status
    return result


def validate_donor_slots(value: dict | None, *, instance_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    try:
        normalized = normalize_donor_slots(value)
    except ValueError as exc:
        return [str(exc)]
    if instance_ids is not None:
        for family, entries in normalized.items():
            if family == "donor_profile":
                continue
            for slot, entry in entries.items():
                if entry and entry["source_instance"] not in instance_ids:
                    errors.append(
                        f"donor_slots.{family}.{slot}: unknown source_instance {entry['source_instance']!r}"
                    )
    return errors


def slot_for_donor_semantic(semantic: str) -> tuple[str, str] | None:
    """Map a semantic to the v0.1 board, or return None when ambiguous."""
    value = _canonical(semantic)
    if value in {"eye", "eyes", "eye_open", "eyes_open", "open_eye", "open_eyes"}:
        return "eyes", "open"
    if value == "blink" or re.match(r"^(eye|eyes)_(closed|close)$", value):
        return "eyes", "closed"
    if value in {"mouth", "mouth_closed", "mouth_neutral", "closed_mouth"}:
        return "mouth", "closed"
    match = re.match(r"^(?:mouth|viseme|phoneme)[_]?(a|i|u|e|o)$", value)
    if match:
        return "mouth", match.group(1)
    return None


def _set_slot_raw(
    document: "AssemblyDocument",
    family: str,
    slot: str,
    source_instance: str,
    *,
    status: str = "READY",
    source_id: str | None = None,
    source_revision: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    if family not in {"eyes", "mouth"}:
        raise ValueError(f"unknown donor slot family: {family!r}")
    allowed = EYE_SLOTS if family == "eyes" else MOUTH_SLOTS
    if slot not in allowed:
        raise ValueError(f"unknown {family} donor slot: {slot!r}")
    if source_instance not in document.instances:
        raise ValueError(f"unknown donor source instance: {source_instance!r}")
    if status not in SLOT_STATUSES or status == "EMPTY":
        raise ValueError(f"invalid assigned donor slot status: {status!r}")
    entry = {"source_instance": source_instance, "status": status}
    if source_id is not None:
        entry["source_id"] = source_id
    if source_revision is not None:
        entry["source_revision"] = source_revision
    if warnings:
        entry["warnings"] = list(warnings)
    document.donor_slots.setdefault("donor_profile", DONOR_PROFILE)
    document.donor_slots.setdefault("eyes", {})
    document.donor_slots.setdefault("mouth", {})
    document.donor_slots[family][slot] = entry


def set_donor_slot(
    document: "AssemblyDocument",
    family: str,
    slot: str,
    source_instance: str,
    *,
    status: str = "READY",
    source_id: str | None = None,
    source_revision: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    """Assign a slot as one public authoring transaction."""
    if document.in_transaction:
        _set_slot_raw(document, family, slot, source_instance, status=status, source_id=source_id, source_revision=source_revision, warnings=warnings)
    else:
        with document.transaction():
            _set_slot_raw(document, family, slot, source_instance, status=status, source_id=source_id, source_revision=source_revision, warnings=warnings)


def clear_donor_slot(document: "AssemblyDocument", family: str, slot: str) -> None:
    allowed = EYE_SLOTS if family == "eyes" else MOUTH_SLOTS if family == "mouth" else ()
    if slot not in allowed:
        raise ValueError(f"unknown donor slot: {family}.{slot}")
    if document.in_transaction:
        document.donor_slots.setdefault(family, {})[slot] = None
    else:
        with document.transaction():
            document.donor_slots.setdefault(family, {})[slot] = None


def register_expression_donor_slot(
    document: "AssemblyDocument",
    semantic: str,
    instance_id: str,
    *,
    source_id: str | None = None,
    source_revision: str | None = None,
    warnings: list[str] | None = None,
) -> tuple[str, str] | None:
    slot = slot_for_donor_semantic(semantic)
    if slot is None:
        return None
    set_donor_slot(
        document,
        *slot,
        instance_id,
        source_id=source_id,
        source_revision=source_revision,
        warnings=warnings,
    )
    return slot


def donor_slot_status(document: "AssemblyDocument", family: str, slot: str) -> str:
    entry = (document.donor_slots or {}).get(family, {}).get(slot)
    if not entry:
        return "EMPTY"
    if entry.get("warnings"):
        return "WARNING"
    if entry.get("source_instance") not in document.instances:
        return "REVIEW"
    return entry.get("status", "READY")

