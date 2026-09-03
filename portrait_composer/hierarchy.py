"""Hierarchy.

Status: NOT IMPLEMENTED -- deferred to phase C1.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #11

Hierarchy relation (parent/child editing/organizational tree). One of the five
relation types that must stay separate from
Slot/TransformLink/VariantSet/RigIntent -- see MASTER #4.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "hierarchy.py is phase C1 scope (see module docstring); "
        "not part of the C0 implementation."
    )
