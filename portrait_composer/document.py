"""AssemblyDocument -- the C0 document core.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #3-4,
SEETHROUGH_..._MASTER_v0.2.md #3.

    AssemblyDocument
    +-- sources
    +-- assets
    +-- instances
    +-- hierarchy
    +-- variant_sets
    +-- links
    +-- rig_intent
    +-- composition
    +-- provenance

Every edit goes through ``transaction()``:

    snapshot -> apply -> validate -> OK/FAIL -> commit/rollback

A validation failure (or an exception raised inside the ``with`` block)
leaves the document exactly as it was before the transaction started --
"작업 중 validation fail로 document를 반쯤 변한 상태에 두지 않는다" (#4).
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .assets import AssetDefinition
from .history import HistoryManager
from .instances import LayerInstance
from .provenance import ProvenanceLog
from .sources import SourceAsset
from .validation import ValidationResult, validate as _validate


class TransactionValidationError(Exception):
    """Raised when a transaction's changes fail validate() -- rolled back before this is raised."""

    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__("; ".join(result.errors) or "validation failed")


class DuplicateIdError(Exception):
    pass


class AssemblyDocument:
    def __init__(self) -> None:
        self.sources: dict[str, SourceAsset] = {}
        self.assets: dict[str, AssetDefinition] = {}
        self.instances: dict[str, LayerInstance] = {}
        self.hierarchy: dict = {}
        self.variant_sets: dict = {}
        self.links: dict = {}
        self.rig_intent: dict = {"regions": {}, "attachments": {}, "deformation_scopes": {}}
        # C3 ExpressionPreset storage.  Presets are only a thin mapping over
        # VariantSets; AutoRig parameter binding is intentionally absent.
        self.expressions: dict = {}
        self.composition: dict = {"draw_order": [], "canvas": {}}
        self.provenance = ProvenanceLog()
        self.history = HistoryManager()

    # ------------------------------------------------------------------
    # mutation primitives -- intended to be called from inside a
    # transaction() block. They raise immediately on a duplicate id
    # rather than waiting for validate(), since that's a programmer error
    # a caller should notice right away; missing-ref style problems are
    # left to validate() because they may be transiently true mid-transaction.
    # ------------------------------------------------------------------
    def add_asset(self, asset: AssetDefinition) -> None:
        if asset.id in self.assets:
            raise DuplicateIdError(f"asset id already exists: {asset.id!r}")
        self.assets[asset.id] = asset

    def add_instance(self, instance: LayerInstance) -> None:
        if instance.id in self.instances:
            raise DuplicateIdError(f"instance id already exists: {instance.id!r}")
        self.instances[instance.id] = instance

    def remove_asset(self, asset_id: str) -> None:
        self.assets.pop(asset_id, None)

    def remove_instance(self, instance_id: str) -> None:
        self.instances.pop(instance_id, None)
        self.composition["draw_order"] = [r for r in self.composition.get("draw_order", []) if r != instance_id]

    # ------------------------------------------------------------------
    # transaction model
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self, production: bool = False) -> Iterator["AssemblyDocument"]:
        snapshot_before = self.to_dict()
        try:
            yield self
        except Exception:
            self._restore(snapshot_before)
            raise

        result = _validate(self, production=production)
        if not result.ok:
            self._restore(snapshot_before)
            raise TransactionValidationError(result)

        self.history.record_commit(snapshot_before)

    def _restore(self, snapshot: dict) -> None:
        restored = AssemblyDocument.from_dict(snapshot)
        self.sources = restored.sources
        self.assets = restored.assets
        self.instances = restored.instances
        self.hierarchy = restored.hierarchy
        self.variant_sets = restored.variant_sets
        self.links = restored.links
        self.rig_intent = restored.rig_intent
        self.expressions = restored.expressions
        self.composition = restored.composition
        self.provenance = restored.provenance
        # history/undo state itself is NOT part of the document snapshot.

    # ------------------------------------------------------------------
    # undo / redo (operate on committed transaction boundaries only)
    # ------------------------------------------------------------------
    def undo(self) -> None:
        current = self.to_dict()
        snapshot = self.history.undo(current)
        self._restore(snapshot)

    def redo(self) -> None:
        current = self.to_dict()
        snapshot = self.history.redo(current)
        self._restore(snapshot)

    @property
    def dirty(self) -> bool:
        return self.history.dirty

    def mark_saved(self) -> int:
        return self.history.mark_saved()

    # ------------------------------------------------------------------
    def validate(self, production: bool = False) -> ValidationResult:
        return _validate(self, production=production)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "sources": {sid: s.to_dict() for sid, s in self.sources.items()},
            "assets": {aid: a.to_dict() for aid, a in self.assets.items()},
            "instances": {iid: i.to_dict() for iid, i in self.instances.items()},
            "hierarchy": copy.deepcopy(self.hierarchy),
            "variant_sets": copy.deepcopy(self.variant_sets),
            "links": copy.deepcopy(self.links),
            "rig_intent": copy.deepcopy(self.rig_intent),
            "expressions": copy.deepcopy(self.expressions),
            "composition": copy.deepcopy(self.composition),
            "provenance": self.provenance.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "AssemblyDocument":
        doc = AssemblyDocument()
        doc.sources = {sid: SourceAsset.from_dict(s) for sid, s in d.get("sources", {}).items()}
        doc.assets = {aid: AssetDefinition.from_dict(a) for aid, a in d.get("assets", {}).items()}
        doc.instances = {iid: LayerInstance.from_dict(i) for iid, i in d.get("instances", {}).items()}
        doc.hierarchy = copy.deepcopy(d.get("hierarchy", {}))
        doc.variant_sets = copy.deepcopy(d.get("variant_sets", {}))
        doc.links = copy.deepcopy(d.get("links", {}))
        doc.rig_intent = copy.deepcopy(
            d.get("rig_intent", {"regions": {}, "attachments": {}, "deformation_scopes": {}})
        )
        doc.expressions = copy.deepcopy(d.get("expressions", {}))
        doc.composition = copy.deepcopy(d.get("composition", {"draw_order": [], "canvas": {}}))
        doc.provenance = ProvenanceLog.from_dict(d.get("provenance", {}))
        return doc

    @property
    def expression_presets(self) -> dict:
        """Compatibility/readability alias for the C3 preset map."""
        return self.expressions
