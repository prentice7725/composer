"""Compatibility.

Status: NOT IMPLEMENTED -- deferred to phase C1+.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #5

AssetDefinition.compatibility rule evaluation (which assets may combine). The
field exists on AssetDefinition (assets.py) from C0; this module hosts the
rule engine once assets need to declare real constraints.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "compatibility.py is phase C1+ scope (see module docstring); "
        "not part of the C0 implementation."
    )
