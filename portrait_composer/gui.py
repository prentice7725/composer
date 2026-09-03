"""Gui.

Status: NOT IMPLEMENTED -- deferred to phase GUI.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #3

Interactive editor. Explicitly deferred: "GUI보다 먼저 AssemblyDocument를 구현" (#3,
'document core first'). Nothing here until C0's document/CLI surface is
stable.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "gui.py is phase GUI scope (see module docstring); "
        "not part of the C0 implementation."
    )
