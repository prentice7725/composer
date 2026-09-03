# Implementation Status

Tracks directive exit checklists (`PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md`
#32-34). **C0 + C0.5** are implemented; C1-C4 are not started.

## C0.5 -- Portrait Bundle v1 contract sync

`portrait_composer/bundle.py`'s Portrait Bundle reader now targets the
real, producer-owned contract from `prentice7725/seethrough-portrait`
(P0-closed) instead of the interim shape C0 invented before that repo's
bundle format existed. Vendored copies of the upstream contract live at
`schemas/vendor/portrait-bundle-v1.schema.json` and
`docs/PORTRAIT_BUNDLE_V1.md` (see `schemas/vendor/README.md` for the
pinned source commit).

Covered:

- reject unknown major `version`, non-`production_repaired`
  `layer_contract.canonical_stage`, and an unsupported
  `canvas.{coordinate_system,color_space,alpha}`
- consume `layers[tag] = {path, source_tag}` (not a bare path)
- `semantics.z_order` used only to seed each instance's *initial*
  `draw_order` -- never treated as a downstream draw-order policy
- `generation` (seed_mode/attempt_index/seed/canonical_regression_seed/
  source_identity) preserved onto the registered `SourceAsset` and onto
  every `identity_import` provenance record
- `raw_layers/` is read but never harvested -- `identity_assembly` only
  ever builds `image_sources` from `layers/` (regression-tested against
  the real "producer rejected this candidate, e.g. missing_eyewhite"
  shape, see `test_identity_never_reads_raw_layers`)
- rig-specific subdivisions (`head_remainder`, `neck_remainder`, any other
  `*_remainder`) are hard-rejected in the canonical layer set; genuine
  semantic left/right splits (`eyel`/`eyer` etc.) are not affected
- `semantics.warnings`, non-`pass` `validation` statuses, and high-risk
  `diagnostics/occlusion_graph.json` edges are surfaced as import
  warnings (`identity_assembly` returns a 3-tuple now:
  `(document, image_sources, import_warnings)`) -- never as hard errors,
  and never synthesized when the occlusion diagnostic is simply absent
- `tests/fixtures/portrait_bundles/` holds two committed, schema-conformant
  static bundles (one `regression` seed mode, one `deterministic_auto`
  with warnings + raw_layers + an occlusion edge) as a bit-rot guard;
  `tests/test_portrait_bundle_contract.py::test_fixture_conforms_to_the_vendored_upstream_schema`
  keeps the fixture builder itself honest against the vendored JSON Schema

Known limitation: fixtures are hand-built directly against the vendored
schema/doc and cross-checked against the real exporter's own test suite
(`seethrough_engine/export.py`, `tests/unit/seethrough_engine/test_bundle.py`
in that repo), not produced by running the real pipeline (which needs
diffusers/torch/opencv and a real portrait image). Swap in true exporter
output where convenient.

Also: with today's single producer, `source_layer_id` and
`fallback_semantic` (SourceBinding) always coincide in practice (both
derive from the same tag), so remap's `SEMANTIC_MATCH`/`AMBIGUOUS`
statuses only fire when a layer's `tag` and `source_tag` genuinely diverge
-- schema-legal, but not something the current producer does yet. See
`remap.py`'s module docstring.

## C0 Exit (directive #32)

- [x] AssemblyDocument (`document.py`)
- [x] transaction/history (`document.py` transaction model, `history.py` undo/redo + dirty state + saved revision token)
- [x] AssetDefinition (`assets.py`)
- [x] LayerInstance (`instances.py`)
- [x] SourceBinding (`sources.py`)
- [x] v0.2 schema (`schemas/portrait-assembly-v0.2.schema.json` -- C0 fields fully shaped, C1+ fields reserved as free-form pending their own phase)
- [x] identity render (`render.py`, `assembly.identity_assembly`)
- [x] reference.png (`bundle.write_assembly_bundle`)
- [x] provenance (`provenance.py`, recorded on every identity import / recipe op / remap)
- [x] CLI (`cli.py`: identity, validate, render, apply, remap)
- [x] regression (`tests/test_regression.py`)

## C1/C2 Exit (directive #33) -- not started

- [ ] multi-source harvest
- [ ] hierarchy
- [ ] slot (vocabulary exists conceptually via `LayerInstance.slot`; `slots.py` itself is a stub)
- [ ] transform link (`LayerInstance.transform_link` field exists; `links.py` resolution logic is a stub)
- [ ] VariantSet (raw dict data model + validation exist in `document.py`/`validation.py`; typed helpers in `variants.py` are a stub)
- [ ] reorder (basic `reorder_draw_order` recipe op exists in `assembly.py`; no dedicated hierarchy-aware reorder tooling yet)
- [ ] bake dry-run
- [ ] bake provenance
- [ ] profiles
- [ ] source remap (classification + manual/auto-resolvable apply exist in `remap.py`; CLI `remap` is report-only, see its module docstring)

## C3/C4 Exit (directive #34) -- not started

- [ ] donor
- [ ] expression assets
- [ ] rig intent (raw dict data model + validation exist; typed authoring helpers in `rig_intent.py` are a stub)
- [ ] attachment (validated as broken/valid target only; no authoring helpers)
- [ ] upper_torso_secondary
- [ ] soft/firm_bounce/springy
- [ ] manual region edit
- [ ] visual preflight

## Not implemented at all

`gui.py`, `workflow.py`, `compatibility.py`, `donors.py`, `expressions.py`,
`secondary_regions.py` are present as stub modules (matching the directive's
repository layout, #2) that raise `NotImplementedError` -- each one's
docstring names the phase and directive section it belongs to.
