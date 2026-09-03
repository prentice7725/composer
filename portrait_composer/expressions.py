"""Expressions.

Status: NOT IMPLEMENTED -- deferred to phase C3.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #20

Expression as VariantSet: eye_state / mouth_viseme / brow_state members, plus
composite expression presets bundling multiple VariantSets + parameter hints.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "expressions.py is phase C3 scope (see module docstring); "
        "not part of the C0/C0.5/C1 implementation."
    )
