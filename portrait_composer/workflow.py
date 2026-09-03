"""Workflow.

Status: NOT IMPLEMENTED -- deferred to phase GUI-facing.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #4

Save/dirty-state/undo-redo workflow glue for an interactive editor (gui.py).
document.py's transaction model + history.py already provide the primitives
this orchestrates.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "workflow.py is phase GUI-facing scope (see module docstring); "
        "not part of the C0 implementation."
    )
