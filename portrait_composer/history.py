"""Undo/redo + dirty-state tracking for AssemblyDocument.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #4.

This module knows nothing about documents -- it just keeps a stack of
opaque serialized snapshots (plain dicts, as produced by
``AssemblyDocument.to_dict()``) plus a revision counter used to derive
dirty state and a "saved revision token".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class NothingToUndoError(Exception):
    pass


class NothingToRedoError(Exception):
    pass


@dataclass
class HistoryManager:
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    revision: int = 0
    saved_revision: int = 0

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    def record_commit(self, snapshot_before: dict) -> None:
        """Called after a transaction commits successfully."""
        self.undo_stack.append(snapshot_before)
        self.redo_stack.clear()
        self.revision += 1

    def undo(self, current_snapshot: dict) -> dict:
        if not self.undo_stack:
            raise NothingToUndoError("no committed operations to undo")
        self.redo_stack.append(current_snapshot)
        self.revision -= 1
        return self.undo_stack.pop()

    def redo(self, current_snapshot: dict) -> dict:
        if not self.redo_stack:
            raise NothingToRedoError("no undone operations to redo")
        self.undo_stack.append(current_snapshot)
        self.revision += 1
        return self.redo_stack.pop()

    def mark_saved(self) -> int:
        """Returns the saved revision token."""
        self.saved_revision = self.revision
        return self.saved_revision

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)
