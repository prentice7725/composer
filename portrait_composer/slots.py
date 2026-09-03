"""Slots.

Status: NOT IMPLEMENTED -- deferred to phase C1.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #13-14

Slot vocabulary (body_back, hair_back, torso_back, torso, torso_front, neck,
head, face, eye, mouth, accessory_front, hair_front, headwear) and multi-plane
asset -> slot resolution. Slot is placement, not semantic (#13).
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "slots.py is phase C1 scope (see module docstring); "
        "not part of the C0 implementation."
    )
