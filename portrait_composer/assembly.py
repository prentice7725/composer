"""C0 Identity Composer, C1 Multi-Source Harvest, + minimal recipe apply.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #9-10,
#15, #31.

``identity_assembly`` turns one Portrait Bundle (real Portrait Bundle v1 --
see bundle.py's module docstring) into an AssemblyDocument with no changes:
every canonical (``layers/``) entry becomes one AssetDefinition + one
identity-transform LayerInstance, ordered by the bundle's own
``semantics.z_order``. Acceptance (#9): Composer's rendered reference must
equal SeeThrough's canonical composite -- i.e. compositing exactly
``layers/*.png`` in z_order, nothing from ``raw_layers/``.

``harvest_assembly`` is C1 Multi-Source Harvesting (#10): pick, per
semantic tag, which of several already-read Portrait Bundles (e.g. several
seeds/attempts of the same character) supplies that tag's canonical layer
-- never from any bundle's ``raw_layers/``. This is choosing between
several producer *runs'* ``layers/``, not a fallback into forensic data;
see the module docstring on that distinction.

``apply_recipe`` covers the C0 slice of "WHAT TO USE / WHERE TO PLACE /
WHAT MAY MOVE" editing (mission statement, #0): visibility, opacity,
transform, draw order, duplicating an existing instance, and removing an
instance. Bake is explicitly out of scope here -- that's C2 (bake.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .assets import AssetDefinition
from .bundle import PortraitBundle, source_id_for
from .document import AssemblyDocument
from .instances import LayerInstance, Transform
from .sources import SourceAsset, SourceBinding, content_hash


def instance_id_for(layer_id: str) -> str:
    return f"{layer_id}__instance"


def identity_assembly(bundle: PortraitBundle) -> tuple[AssemblyDocument, dict, list]:
    """Returns (document, image_sources, import_warnings).

    ``image_sources`` maps instance id -> Path to the source layer PNG to
    copy into the bundle. ``import_warnings`` forwards ``bundle.warnings``
    (semantics.warnings, non-"pass" validation statuses, high-risk
    occlusion edges) -- never used to block the import, only surfaced.
    """
    document = AssemblyDocument()
    image_sources: dict[str, Path] = {}

    source_id = source_id_for(bundle)
    revision = content_hash(bundle.root / "manifest.json")

    with document.transaction():
        document.sources[source_id] = SourceAsset(
            source_id=source_id,
            path=str(bundle.root),
            metadata={
                "generation": dict(bundle.generation),
                "canvas": dict(bundle.canvas),
                "validation": dict(bundle.validation),
            },
        )

        draw_order = []
        for layer in bundle.layers:  # already sorted by z_order-derived draw_order
            asset = AssetDefinition(
                id=layer.tag,
                semantic=layer.tag,
                source_binding=SourceBinding(
                    source_id=source_id,
                    revision=revision,
                    source_layer_id=layer.tag,
                    fallback_semantic=layer.source_tag,
                ),
                planes=[layer.tag],
            )
            document.add_asset(asset)

            inst_id = instance_id_for(layer.tag)
            instance = LayerInstance(
                id=inst_id,
                asset_ref=asset.id,
                slot=layer.tag,  # placeholder pending C1 slot-vocabulary mapping (slots.py)
                draw_order=layer.draw_order,
                transform=Transform(),
            )
            document.add_instance(instance)
            draw_order.append(inst_id)

            # canonical layers/ only -- raw_layers/ is never read here (forensic-only,
            # never a fallback for a missing canonical layer, per PORTRAIT_BUNDLE_V1.md).
            image_sources[inst_id] = bundle.layer_path(layer)
            document.provenance.record(
                inst_id,
                operation="identity_import",
                sources=[source_id],
                source_layer_id=layer.tag,
                source_tag=layer.source_tag,
                revision=revision,
                generation=dict(bundle.generation),
            )

        document.composition["draw_order"] = draw_order
        document.composition["canvas"] = dict(bundle.canvas)

    return document, image_sources, list(bundle.warnings)


class HarvestError(Exception):
    pass


def harvest_assembly(bundles: dict, selections: dict) -> tuple[AssemblyDocument, dict, list]:
    """C1 Multi-Source Harvesting (directive #10).

    ``bundles``: {run_label: PortraitBundle} -- several already-read runs of
    (typically) the same character, e.g. different seeds/attempts.
    ``selections``: {target_tag: run_label} -- which run supplies each
    canonical tag's LayerInstance. The tag is looked up in that run's own
    ``layers/`` (never ``raw_layers/``) under the same tag name; picking a
    layer under a *different* tag than the target is a rename and belongs
    to remap.py, not harvesting.

    Every run actually referenced by ``selections`` registers its own
    SourceAsset under its run_label (not its ``source_identity`` -- several
    runs of the same character share a source_identity but are distinct
    revisions/attempts, and must stay distinguishable, directive #10:
    "UI는 source badge 표시"). Provenance on each harvested instance records
    the run_label, the bundle's full ``generation`` (seed, attempt_index,
    ...), and the source layer tag -- directive: "각 선택은 provenance에
    기록".

    All runs a selection actually draws from must share one canvas --
    directive #17's "canvas" dry-run-bake check applied proactively here,
    since compositing mismatched canvases is meaningless.
    """
    document = AssemblyDocument()
    image_sources: dict[str, Path] = {}
    warnings: list[str] = []
    seen_run_labels: set[str] = set()
    canvas: Optional[dict] = None

    with document.transaction():
        draw_order_pairs = []  # (draw_order, inst_id) to sort by the originating run's z_order
        for target_tag, run_label in selections.items():
            bundle = bundles.get(run_label)
            if bundle is None:
                raise HarvestError(f"selection for {target_tag!r} names unknown run {run_label!r}")

            layer = next((l for l in bundle.layers if l.tag == target_tag), None)
            if layer is None:
                raise HarvestError(
                    f"run {run_label!r} has no canonical layer {target_tag!r} in layers/ "
                    "(raw_layers/ is never a harvesting candidate)"
                )

            if canvas is None:
                canvas = dict(bundle.canvas)
            elif canvas != dict(bundle.canvas):
                raise HarvestError(
                    f"canvas mismatch: run {run_label!r} does not match the canvas already "
                    "established by an earlier selection"
                )

            if run_label not in seen_run_labels:
                seen_run_labels.add(run_label)
                document.sources[run_label] = SourceAsset(
                    source_id=run_label,
                    path=str(bundle.root),
                    metadata={
                        "source_identity": bundle.source_identity,
                        "generation": dict(bundle.generation),
                        "canvas": dict(bundle.canvas),
                        "validation": dict(bundle.validation),
                    },
                )
                warnings.extend(f"[{run_label}] {w}" for w in bundle.warnings)

            revision = content_hash(bundle.root / "manifest.json")
            asset = AssetDefinition(
                id=target_tag,
                semantic=target_tag,
                source_binding=SourceBinding(
                    source_id=run_label,
                    revision=revision,
                    source_layer_id=layer.tag,
                    fallback_semantic=layer.source_tag,
                ),
                planes=[target_tag],
            )
            document.add_asset(asset)

            inst_id = instance_id_for(target_tag)
            instance = LayerInstance(
                id=inst_id,
                asset_ref=asset.id,
                slot=target_tag,  # placeholder pending C1 slot-vocabulary mapping (slots.py)
                draw_order=layer.draw_order,
                transform=Transform(),
            )
            document.add_instance(instance)
            draw_order_pairs.append((layer.draw_order, inst_id))

            image_sources[inst_id] = bundle.layer_path(layer)
            document.provenance.record(
                inst_id,
                operation="multi_source_harvest",
                sources=[run_label],
                run_label=run_label,
                source_layer_id=layer.tag,
                source_tag=layer.source_tag,
                revision=revision,
                generation=dict(bundle.generation),
            )

        draw_order_pairs.sort(key=lambda pair: pair[0])
        document.composition["draw_order"] = [inst_id for _, inst_id in draw_order_pairs]
        if canvas is not None:
            document.composition["canvas"] = canvas

    return document, image_sources, warnings


def set_draw_order(document: AssemblyDocument, new_order: list) -> None:
    """Final draw order authoring (directive #15), as a standalone
    transactional call rather than only through a recipe op."""
    with document.transaction():
        document.composition["draw_order"] = list(new_order)


class RecipeError(Exception):
    pass


def apply_recipe(document: AssemblyDocument, recipe: dict, image_sources: dict) -> None:
    """Applies ``recipe["operations"]`` to ``document`` inside one transaction.

    Mutates ``image_sources`` in place for ops that introduce a new
    instance id backed by an existing instance's image (duplicate_instance).
    """
    operations = recipe.get("operations", [])

    with document.transaction():
        for op in operations:
            kind = op.get("op")
            if kind == "set_visible":
                inst = _require_instance(document, op["instance"])
                inst.visible = bool(op["value"])
            elif kind == "set_opacity":
                inst = _require_instance(document, op["instance"])
                inst.opacity = float(op["value"])
            elif kind == "set_transform":
                inst = _require_instance(document, op["instance"])
                t = op.get("transform", {})
                for field_name in ("x", "y", "scale_x", "scale_y", "rotation"):
                    if field_name in t:
                        setattr(inst.transform, field_name, t[field_name])
            elif kind == "reorder_draw_order":
                new_order = op["draw_order"]
                document.composition["draw_order"] = list(new_order)
            elif kind == "duplicate_instance":
                src = _require_instance(document, op["from_instance"])
                new_id = op["new_id"]
                overrides = op.get("overrides", {})
                new_inst = LayerInstance.from_dict(src.to_dict())
                new_inst.id = new_id
                for k, v in overrides.items():
                    if k == "transform":
                        new_inst.transform = Transform.from_dict(v)
                    else:
                        setattr(new_inst, k, v)
                document.add_instance(new_inst)
                document.composition.setdefault("draw_order", []).append(new_id)
                if op["from_instance"] in image_sources:
                    image_sources[new_id] = image_sources[op["from_instance"]]
                document.provenance.record(
                    new_id, operation="duplicate_instance", sources=[op["from_instance"]]
                )
            elif kind == "remove_instance":
                document.remove_instance(op["instance"])
                image_sources.pop(op["instance"], None)
            else:
                raise RecipeError(f"unknown recipe operation: {kind!r}")


def _require_instance(document: AssemblyDocument, instance_id: str) -> LayerInstance:
    inst = document.instances.get(instance_id)
    if inst is None:
        raise RecipeError(f"recipe references unknown instance: {instance_id!r}")
    return inst
