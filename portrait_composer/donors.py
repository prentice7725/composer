"""Donors.

Status: NOT IMPLEMENTED -- deferred to phase C3.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #19

Donor pipeline: donor -> matte -> align -> semantic ROI -> drift check ->
AssetDefinition -> VariantSet member. Composer processes donors; AutoRig never
sees the donor original.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "donors.py is phase C3 scope (see module docstring); "
        "not part of the C0/C0.5/C1 implementation."
    )
