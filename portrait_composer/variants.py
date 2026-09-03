"""Variants.

Status: NOT IMPLEMENTED -- deferred to phase C1.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #12

Typed VariantSet helpers (exclusive-mode selection, default resolution,
crossfade parameter binding for AutoRig). document.variant_sets (raw dict,
validated in validation.py) is the C0 data slot this builds on.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "variants.py is phase C1 scope (see module docstring); "
        "not part of the C0 implementation."
    )
