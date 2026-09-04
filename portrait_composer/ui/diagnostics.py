"""Read-only diagnostics and provenance presentation helpers for C5-H."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    message: str
    target_id: str | None = None
    context: str = "ASSEMBLE"

    @property
    def label(self) -> str:
        return self.target_id or "Assembly"


def _target_for_message(document, message: str) -> str | None:
    """Resolve the most specific instance/asset/semantic named in a message."""
    if document is None:
        return None
    instance_ids = sorted(document.instances, key=len, reverse=True)
    for instance_id in instance_ids:
        if instance_id in message:
            return instance_id

    asset_ids = sorted(document.assets, key=len, reverse=True)
    for asset_id in asset_ids:
        if asset_id in message:
            return asset_id

    quoted = re.findall(r"'([^']+)'", message)
    for token in quoted:
        for asset_id, asset in document.assets.items():
            if token in (asset_id, asset.semantic):
                instances = [
                    instance_id
                    for instance_id, instance in document.instances.items()
                    if instance.asset_ref == asset_id
                ]
                return instances[0] if instances else asset_id
        for instance_id, instance in document.instances.items():
            if token == instance.slot:
                return instance_id
    return None


def _context_for_message(message: str) -> str:
    """Route a diagnostic to the authoring surface that can resolve it."""
    lowered = message.lower()
    if any(token in lowered for token in ("rigintent", "deformation_scope", "attachment", "secondary region", "secondary_region")):
        return "RIG INTENT"
    if any(token in lowered for token in ("variant", "expression")):
        return "VARIANTS"
    if any(token in lowered for token in ("donor", "alignment", "drift")):
        return "DONOR"
    if any(token in lowered for token in ("bake", "derived")):
        return "BAKE"
    return "ASSEMBLE"


def collect_diagnostics(document, import_warnings: list[str] | None = None) -> list[Diagnostic]:
    """Collect validation and import warnings without mutating the document."""
    if document is None:
        return []
    result = document.validate()
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()
    for severity, messages in (("ERROR", result.errors), ("WARN", result.warnings)):
        for message in messages:
            key = (severity, str(message))
            if key in seen:
                continue
            seen.add(key)
            text = str(message)
            diagnostics.append(Diagnostic(severity, text, _target_for_message(document, text), _context_for_message(text)))
    for message in import_warnings or []:
        key = ("WARN", str(message))
        if key in seen:
            continue
        seen.add(key)
        text = str(message)
        diagnostics.append(Diagnostic("WARN", text, _target_for_message(document, text), _context_for_message(text)))
    return diagnostics


def provenance_text(document, target_id: str) -> str:
    """Format instance and asset provenance as a read-only human summary."""
    if document is None:
        return "No document open."
    targets = [target_id]
    instance = document.instances.get(target_id)
    if instance is not None and instance.asset_ref not in targets:
        targets.append(instance.asset_ref)
    lines: list[str] = []
    for target in targets:
        records = document.provenance.for_target(target)
        asset = document.assets.get(target)
        if not records and asset is not None and asset.provenance:
            records = []
            lines.append(f"{target}\n  Derived provenance")
            for key, value in asset.provenance.items():
                lines.append(f"  {key}: {value}")
            continue
        if not records:
            continue
        lines.append(target)
        for record in records:
            lines.append(f"  Operation: {record.operation}")
            if record.sources:
                lines.append(f"  Source: {', '.join(map(str, record.sources))}")
            for key, value in record.extra.items():
                if key in {"generation", "detail"} and isinstance(value, dict):
                    lines.append(f"  {key}: {value}")
                else:
                    lines.append(f"  {key}: {value}")
    return "\n".join(lines) if lines else "No provenance recorded."
