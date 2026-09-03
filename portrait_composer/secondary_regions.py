"""Secondary Regions.

Status: NOT IMPLEMENTED -- deferred to phase C4.
Directive ref: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #24-28

upper_torso_secondary region authoring: geometry (two_lobe etc.), locks
(center/neckline/shoulder), response_profile (soft/firm_bounce/springy),
author_strength, and visual preflight (READY/DEGRADED/DISABLED). Composer
decides WHERE + WHAT MAY MOVE + response class only -- AutoRig computes the
physics (Final Rule, #35).
"""
from __future__ import annotations


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "secondary_regions.py is phase C4 scope (see module docstring); "
        "not part of the C0 implementation."
    )
