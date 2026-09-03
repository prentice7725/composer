"""Links.

Status: NOT IMPLEMENTED -- deferred to phase C1.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #11

TransformLink relation: instances that move/align together during editing.
LayerInstance.transform_link (instances.py) is the field; this module owns
link-group resolution and propagation.
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "links.py is phase C1 scope (see module docstring); "
        "not part of the C0 implementation."
    )
