"""portrait-composer: Semantic Portrait Assembly & Authoring Tool.

Implements C0 + C0.5 of PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md
(C0.5 = syncing the Portrait Bundle reader with the real, producer-owned
Portrait Bundle v1 contract from `prentice7725/seethrough-portrait`, see
bundle.py). See that directive (and SEETHROUGH_..._MASTER_v0.2.md) for the
full spec; see STATUS.md in the repo root for what's implemented vs.
deferred.
"""

from .document import AssemblyDocument, TransactionValidationError, DuplicateIdError
from .assets import AssetDefinition
from .instances import LayerInstance, Transform
from .sources import SourceAsset, SourceRevision, SourceBinding

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
]

__version__ = "0.2.0-c0.5"
