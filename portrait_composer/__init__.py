"""portrait-composer: Semantic Portrait Assembly & Authoring Tool.

Implements C0 + C0.5 + C1 + C2 + C3 + C4 of PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md:

- C0.5 = syncing the Portrait Bundle reader with the real, producer-owned
  Portrait Bundle v1 contract from `prentice7725/seethrough-portrait` (bundle.py)
- C1 = multi-source harvesting (assembly.harvest_assembly), Hierarchy
  (hierarchy.py), Slot/Plane (slots.py), TransformLink (links.py),
  VariantSet (variants.py), final draw_order authoring
  (assembly.set_draw_order)
- C2 = Bake dry-run + apply (bake.py) and export profiles -- PORTRAIT_STATIC/
  PORTRAIT_RIG/FULL_MOTION (profiles.py)
- C3 = donor import and thin VariantSet-backed ExpressionPreset authoring
  (donors.py, expressions.py)
- C4 = typed RigIntent, upper_torso_secondary authoring, and visual preflight
  (rig_intent.py, secondary_regions.py)

See that directive (and SEETHROUGH_..._MASTER_v0.2.md) for the full spec;
see STATUS.md in the repo root for what's implemented vs. deferred.
"""

from .assembly import HarvestError, RecipeError, harvest_assembly, identity_assembly, set_draw_order
from .assets import AssetDefinition
from .bake import BakeBlockedError, BakeError, analyze_bake, apply_bake_plan
from .document import AssemblyDocument, DuplicateIdError, TransactionValidationError
from .donors import DonorDriftError, DonorError, DonorImportResult, import_donor
from .expressions import ExpressionError, apply_expression_preset, create_expression_preset
from .instances import LayerInstance, Transform
from .profiles import FULL_MOTION, PORTRAIT_RIG, PORTRAIT_STATIC, analyze_profile, apply_candidate
from .rig_intent import ATTACHMENT_MODES, DEFORMATION_SCOPES, add_attachment, set_deformation_scope
from .secondary_regions import (
    PREFLIGHT_DEGRADED,
    PREFLIGHT_DISABLED,
    PREFLIGHT_READY,
    UPPER_TORSO_SECONDARY,
    add_upper_torso_secondary,
    visual_preflight,
)
from .sources import SourceAsset, SourceBinding, SourceRevision

__all__ = [
    "AssemblyDocument",
    "TransactionValidationError",
    "DuplicateIdError",
    "AssetDefinition",
    "LayerInstance",
    "Transform",
    "SourceAsset",
    "SourceRevision",
    "SourceBinding",
    "identity_assembly",
    "harvest_assembly",
    "set_draw_order",
    "RecipeError",
    "HarvestError",
    "analyze_bake",
    "apply_bake_plan",
    "BakeError",
    "BakeBlockedError",
    "analyze_profile",
    "apply_candidate",
    "PORTRAIT_STATIC",
    "PORTRAIT_RIG",
    "FULL_MOTION",
    "DEFORMATION_SCOPES",
    "ATTACHMENT_MODES",
    "set_deformation_scope",
    "add_attachment",
    "UPPER_TORSO_SECONDARY",
    "add_upper_torso_secondary",
    "visual_preflight",
    "PREFLIGHT_READY",
    "PREFLIGHT_DEGRADED",
    "PREFLIGHT_DISABLED",
    "import_donor",
    "DonorError",
    "DonorDriftError",
    "DonorImportResult",
    "create_expression_preset",
    "apply_expression_preset",
    "ExpressionError",
]

__version__ = "0.2.0-c4"
