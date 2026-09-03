"""Provenance log.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #10, #16,
#29-30.

Append-only record of "how did this instance/asset come to exist". Every
harvest (#10) and every bake (#16) operation must append a record here --
that is what lets the UI show a source badge and lets validation reason
about unresolved bindings.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvenanceRecord:
    operation: str
    sources: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"operation": self.operation, "sources": list(self.sources), "timestamp": self.timestamp}
        d.update(self.extra)
        return d

    @staticmethod
    def from_dict(d: dict) -> "ProvenanceRecord":
        d = dict(d)
        operation = d.pop("operation")
        sources = d.pop("sources", [])
        timestamp = d.pop("timestamp", time.time())
        return ProvenanceRecord(operation=operation, sources=list(sources), timestamp=timestamp, extra=d)


class ProvenanceLog:
    """Maps a target id (instance or asset id) -> ordered list of records."""

    def __init__(self) -> None:
        self._log: dict[str, list[ProvenanceRecord]] = {}

    def record(self, target_id: str, operation: str, sources: list | None = None, **extra: Any) -> None:
        self._log.setdefault(target_id, []).append(
            ProvenanceRecord(operation=operation, sources=list(sources or []), extra=dict(extra))
        )

    def for_target(self, target_id: str) -> list[ProvenanceRecord]:
        return list(self._log.get(target_id, []))

    def to_dict(self) -> dict:
        return {tid: [r.to_dict() for r in records] for tid, records in self._log.items()}

    @staticmethod
    def from_dict(d: dict) -> "ProvenanceLog":
        log = ProvenanceLog()
        for tid, records in d.items():
            log._log[tid] = [ProvenanceRecord.from_dict(r) for r in records]
        return log

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProvenanceLog):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def copy(self) -> "ProvenanceLog":
        return ProvenanceLog.from_dict(self.to_dict())
