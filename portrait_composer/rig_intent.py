"""Rig Intent.

Status: NOT IMPLEMENTED -- deferred to phase C4.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #21-23

Typed RigIntent authoring: deformation_scope
(baked/rigid/local/independent/secondary) and attachment intent
(weld/hinge/free/follow). document.rig_intent (raw dict, validated in
validation.py) is the C0 data slot this builds on. Composer authors intent
only -- AutoRig does the constraint math.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "rig_intent.py is phase C4 scope (see module docstring); "
        "not part of the C0/C0.5/C1 implementation."
    )
