"""portrait-composer: Semantic Portrait Assembly & Authoring Tool.

Implements C0 + C0.5 + C1 of PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md:

- C0.5 = syncing the Portrait Bundle reader with the real, producer-owned
  Portrait Bundle v1 contract from `prentice7725/seethrough-portrait` (bundle.py)
- C1 = multi-source harvesting (assembly.harvest_assembly), Hierarchy
  (hierarchy.py), Slot/Plane (slots.py), TransformLink (links.py),
  VariantSet (variants.py), final draw_order authoring
  (assembly.set_draw_order)

See that directive (and SEETHROUGH_..._MASTER_v0.2.md) for the full spec;
see STATUS.md in the repo root for what's implemented vs. deferred.
"""

from .assembly import HarvestError, RecipeError, harvest_assembly, identity_assembly, set_draw_order
from .assets import AssetDefinition
from .document import AssemblyDocument, DuplicateIdError, TransactionValidationError
from .instances import LayerInstance, Transform
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
]

__version__ = "0.2.0-c1"
