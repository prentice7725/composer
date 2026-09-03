"""C0 Identity Composer + minimal recipe apply.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #9, #31.

``identity_assembly`` turns one Portrait Bundle (real Portrait Bundle v1 --
see bundle.py's module docstring) into an AssemblyDocument with no changes:
every canonical (``layers/``) entry becomes one AssetDefinition + one
identity-transform LayerInstance, ordered by the bundle's own
``semantics.z_order``. Acceptance (#9): Composer's rendered reference must
equal SeeThrough's canonical composite -- i.e. compositing exactly
``layers/*.png`` in z_order, nothing from ``raw_layers/``.

``apply_recipe`` covers the C0 slice of "WHAT TO USE / WHERE TO PLACE /
WHAT MAY MOVE" editing (mission statement, #0): visibility, opacity,
transform, draw order, duplicating an existing instance, and removing an
instance. It deliberately does NOT do source harvesting or bake -- that's
C1/C2 (multi-source harvest, bake.py).
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
