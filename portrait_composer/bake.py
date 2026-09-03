"""Bake.

Status: NOT IMPLEMENTED -- deferred to phase C2.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #16-17

Bake/Merge: instances -> derived AssetDefinition + derived LayerInstance, with
provenance {operation, sources}. Dry-run analysis must classify CAN_BAKE /
WARN / BLOCK before any real merge runs.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "bake.py is phase C2 scope (see module docstring); "
        "not part of the C0 implementation."
    )
