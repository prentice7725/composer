"""Profiles.

Status: NOT IMPLEMENTED -- deferred to phase C2.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #18

Export profiles: PORTRAIT_STATIC (full bake), PORTRAIT_RIG (baseline NPC
motion policy), FULL_MOTION (arm/hand/sleeve stay independent).
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "profiles.py is phase C2 scope (see module docstring); "
        "not part of the C0/C0.5/C1 implementation."
    )
