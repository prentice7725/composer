# Implementation Status

Tracks directive exit checklists (`PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md`
#32-34). **C0 + C0.5 + C1 + C2** are implemented; C3-C4 are not started.

## C2 -- Bake + Export Profiles

Scope was locked to Bake and Profile only -- no upper_torso_secondary (C4)
and no RigIntent authoring (C4, `rig_intent.py` stays a stub). No CLI
subcommands yet -- library API only (`portrait_composer.{bake,profiles}`).

- **Bake dry-run** (`bake.analyze_bake`, directive #17): returns a
  `BakeAnalysis(verdict, reasons, instance_ids)` with `verdict` in
  `CAN_BAKE`/`WARN`/`BLOCK`, never mutates the document. BLOCK: fewer than
  2 source instances, missing/unset `composition.canvas`, an unresolved
  `source_binding`, membership in any VariantSet (would remove independent
  switching), an `independent` RigIntent `deformation_scope`, or an
  attachment referencing a source instance/slot. WARN: a `transform_link`
  that would be dissolved, sources spanning multiple bundles/seeds, and --
  important -- **no RigIntent authored yet for these instances at all**.
  That last one is deliberate: RigIntent is C4-empty right now, and its
  absence is never read as "no conflict, safe to bake" (explicit
  instruction) -- it's surfaced as a WARN every time until C4 exists, so
  a clean 2-instance bake today reaches WARN, not CAN_BAKE, until the
  caller actually authors `rig_intent.deformation_scopes` for those
  instances (see `test_bake.py::test_analyze_bake_reaches_can_bake_once_rig_intent_is_authored_and_non_independent`).
- **Bake apply** (`bake.apply_bake_plan`): refuses to run on a BLOCK
  verdict (`BakeBlockedError`). Non-destructive (directive #16) -- source
  instances are hidden (`visible = False`) and removed from
  `composition.draw_order`, never deleted; `document.undo()` restores the
  pre-bake document exactly, byte-for-byte (`to_dict()` equality tested).
  Composites the sources' actual pixels (`render.render_subset`, a new
  sibling of `render_reference` that resolves images through a caller
  `image_sources` map instead of an on-disk `layers/` convention, since
  bake runs before any bundle is necessarily written) into one new PNG
  under a caller-given `work_dir`, and creates one derived
  `AssetDefinition` (`source_binding=None` -- a derived asset has a
  provenance chain instead of one upstream binding; `validation.py` no
  longer requires production-mode source_binding on an asset carrying
  `provenance.derived_from`) + one derived `LayerInstance` inserted into
  `draw_order` exactly where the earliest source instance was. Provenance
  is recorded on both the derived instance and the derived asset id, and
  the derived asset's own `provenance` dict carries
  `{derived_from: [{instance, asset, source_bundle}], operation, profile,
  timestamp, version}` per the requested shape.
- **Export profiles** (`profiles.py`, directive #18): a policy over one
  `AssemblyDocument`, not a separate renderer -- `analyze_profile(document,
  profile)` returns `BakeCandidate`s (each carrying its own
  `bake.BakeAnalysis`) without mutating anything; `apply_candidate`/
  `apply_non_blocking_candidates` are the separate apply step (the "analyze
  then apply, only auto-apply non-BLOCK candidates" split the directive
  asked for, e.g. for an MCP-style "bake under PORTRAIT_RIG, skip anything
  BLOCKed" call).
    - `PORTRAIT_STATIC`: one candidate grouping every visible instance
      *not* protected by VariantSet membership.
    - `PORTRAIT_RIG`: one candidate grouping instances whose `slot` is in
      the torso system (`torso_back`/`torso`/`torso_front`) -- e.g. a
      uniform's garment+arm+handwear instances sharing those slots become
      one `topwear_with_arms`-labeled candidate; `head`/`face`/`eye`/
      `mouth`/`hair_front`/`hair_back`/`headwear`/`neck` slots are never
      grouped (kept independent, per directive #18). This leaves a single
      deformable surface *available* for C4's upper_torso_secondary later
      without deciding anything about motion itself -- upper_torso_secondary
      is explicitly NOT implemented here.
    - `FULL_MOTION`: always returns `[]` -- "arm/hand/sleeve 독립 유지
      우선, Bake는 아주 보수적으로" taken literally as "recommend nothing
      automatically"; call `bake.analyze_bake` directly for a manual
      grouping under this profile if you want one.
  Note: since identity/harvest import currently places `slot = <SeeThrough
  tag>` (a C1 placeholder, see below), exercising `PORTRAIT_RIG`'s
  slot-based grouping requires first calling `slots.set_slot` to map
  instances onto real slot vocabulary -- shown in every profiles.py test.

`tests/test_c2_regression.py::test_c2_full_pipeline` runs the whole C2
exit checklist as one integration test. 118 tests passing overall.

## C1 -- Multi-Source Harvesting / Hierarchy / Slot / TransformLink / VariantSet

Scope was deliberately locked to exclude Bake (that's C2 -- "C1에서
'조립 모델'을 완전히 안정시킨 다음 C2에서 Bake dry-run으로 들어가는 편이
좋음"). No CLI subcommands were added for these yet -- library API only
(`portrait_composer.{assembly,hierarchy,slots,links,variants}`); wiring a
CLI/GUI surface onto them is later work.

- **Multi-Source Harvesting** (`assembly.harvest_assembly`, directive #10):
  picks, per target semantic tag, which of several already-read Portrait
  Bundles (e.g. different seeds/attempts of one character) supplies that
  tag's canonical layer -- e.g. `A001` seed 1843's `eyewhite`, seed 5902's
  `arm`, seed 8177's `hair_back`, combined into one document. Always reads
  from a run's own `layers/`, never `raw_layers/` (regression-tested,
  `test_harvest.py::test_harvest_never_reads_raw_layers`). Each run
  registers its own `SourceAsset` keyed by its caller-given run label (not
  its `source_identity` -- several runs share a `source_identity` but are
  distinct revisions and must stay distinguishable for the "source badge"
  UI directive #10 calls for). Every harvested instance's provenance
  records the run label, the full `generation` block (seed, attempt_index,
  ...), and the source layer tag. Rejects a canvas mismatch between
  selected runs up front (directive #17's canvas dry-run-bake check,
  applied proactively).
- **Hierarchy** (`hierarchy.py`, directive #11): an editing/organizational
  tree over instances (`{nodes: {id -> {parent, ref, label}}, children: {parent_or_"" -> [id,...]}}`),
  independent of Slot/TransformLink/VariantSet/RigIntent. `move_node` is
  the reorder/reparent operation; `remove_node` reparents (never deletes)
  its children. Integrity (missing parent, cycle, dangling `ref`) is a
  hard validation error (`validation.py`, `hierarchy.validate_hierarchy`).
- **Slot / Plane** (`slots.py`, directive #13-14): `SLOT_VOCABULARY` is the
  directive's initial 13-term vocabulary, deliberately open -- an
  unrecognized slot is a validation *warning*, not a hard error.
  `LayerInstance.plane` (new field, `instances.py`) says which of a
  multi-plane asset's declared `planes` an instance renders; membership in
  `asset.planes` is a hard error. `set_slot`/`set_plane` are the
  "슬롯 변경" operations.
- **TransformLink** (`links.py`, directive #11): `create_link`/
  `dissolve_link` are the "생성"/"해제" operations, keeping
  `document.links[id].members` and each member's
  `LayerInstance.transform_link` consistent both ways (hard-validated in
  both directions). `apply_delta` moves every member's transform together.
- **VariantSet** (`variants.py`, directive #12): C1 scope only --
  exclusive membership, default member, **active member**, validation,
  transaction/undo, serialization (expression donors adding members is C3;
  AutoRig visibility/crossfade *compilation* is downstream, MASTER #5).
  `set_active` in `exclusive` mode also drives `LayerInstance.visible` for
  every member, since Composer must always be able to render an accurate
  `reference.png` (directive #9) -- showing every variant superimposed
  would not be that. `active` not in `members` is a hard validation error,
  same as `default`.
- **Final draw_order authoring**: `assembly.set_draw_order` as a
  standalone transactional call, alongside the existing
  `reorder_draw_order` recipe op.

`tests/test_c1_regression.py::test_c1_full_pipeline` runs the whole C1
exit checklist as one integration test (3-bundle harvest -> hierarchy ->
slot -> link create/dissolve -> VariantSet switch -> draw_order -> write
-> reload -> deterministic render -> undo/redo). 92 tests passing at C1
completion (118 now that C2 is in, see above).

## C0.5 -- Portrait Bundle v1 contract sync

`portrait_composer/bundle.py`'s Portrait Bundle reader targets the real,
producer-owned contract from `prentice7725/seethrough-portrait` (P0-closed)
instead of the interim shape C0 invented before that repo's bundle format
existed. Vendored copies of the upstream contract live at
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
  every `identity_import`/`multi_source_harvest` provenance record
- `raw_layers/` is read but never harvested -- `identity_assembly` and
  `harvest_assembly` only ever build `image_sources` from `layers/`
  (regression-tested against the real "producer rejected this candidate,
  e.g. missing_eyewhite" shape)
- rig-specific subdivisions (`head_remainder`, `neck_remainder`) are
  hard-rejected in the canonical layer set via an **explicit denylist**,
  not a `*_remainder` wildcard -- `body_remainder` is itself canonical
  (SEMANTIC_Z_ORDER's first entry upstream) and is allowed; native sided
  semantic tags (`eyel`/`eyer`, `earl`/`earr`, `eyewhitel`/`eyewhiter`,
  `iridesl`/`iridesr`, `eyelashl`/`eyelashr`, `eyebrowl`/`eyebrowr`) are
  legitimate producer content and were never affected
- `semantics.warnings`, non-`pass` `validation` statuses, and high-risk
  `diagnostics/occlusion_graph.json` edges are surfaced as import
  warnings (`identity_assembly`/`harvest_assembly` return
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
- [x] v0.2 schema (`schemas/portrait-assembly-v0.2.schema.json` -- C0+C1+C2 fields shaped, C3+ fields reserved as free-form pending their own phase)
- [x] identity render (`render.py`, `assembly.identity_assembly`)
- [x] reference.png (`bundle.write_assembly_bundle`)
- [x] provenance (`provenance.py`, recorded on every identity import / harvest / bake / recipe op / remap)
- [x] CLI (`cli.py`: identity, validate, render, apply, remap)
- [x] regression (`tests/test_regression.py`)

## C1 Exit (custom checklist, superset of directive #33 minus Bake)

- [x] 서로 다른 3 Portrait Bundle 동시 로드 (`assembly.harvest_assembly`)
- [x] asset 단위 source 선택 (`selections: {tag: run_label}`)
- [x] provenance에 bundle + seed + layer 보존
- [x] hierarchy reorder (`hierarchy.move_node`)
- [x] slot 변경 (`slots.set_slot`)
- [x] transform link 생성/해제 (`links.create_link`/`dissolve_link`)
- [x] VariantSet exclusive 동작 (`variants.set_active`)
- [x] final draw_order 변경 (`assembly.set_draw_order`)
- [x] reference.png deterministic render
- [x] save -> reload -> 동일 document
- [x] undo/redo 전부 통과
- [x] raw_layers harvest 불가 회귀 테스트
- [x] identity C0/C0.5 회귀 계속 PASS

## C2 Exit (custom checklist, superset of directive #33 remainder)

- [x] dry-run CAN_BAKE/WARN/BLOCK (`bake.analyze_bake`)
- [x] source document 비파괴 (sources hidden, never deleted; undo restores byte-for-byte)
- [x] derived AssetDefinition 생성
- [x] derived LayerInstance 생성
- [x] provenance chain 보존 (on both the derived instance and the derived asset id)
- [x] bake 후 reference deterministic
- [x] undo/redo 완전 복원
- [x] save/reload 보존
- [x] VariantSet conflict BLOCK
- [x] canvas mismatch BLOCK
- [x] transform/link 관련 경고
- [x] PORTRAIT_STATIC policy
- [x] PORTRAIT_RIG policy
- [x] FULL_MOTION policy
- [x] profile analyze와 apply 분리 (`analyze_profile` vs `apply_candidate`/`apply_non_blocking_candidates`)
- [x] C0/C0.5/C1 회귀 전부 PASS

Not done (out of locked C2 scope, left for later phases):

- [ ] source remap wired into a CLI subcommand (classification + manual/auto-resolvable apply exist in `remap.py`; CLI `remap` is report-only, see its module docstring)
- [ ] CLI/GUI surface for bake/profiles (library API only so far)

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
`rig_intent.py`, `secondary_regions.py` are present as stub modules
(matching the directive's repository layout, #2) that raise
`NotImplementedError` -- each one's docstring names the phase and
directive section it belongs to. `upper_torso_secondary` itself is
deliberately not implemented anywhere yet (C4) -- PORTRAIT_RIG's torso
grouping (C2, above) only leaves a single surface *available* for it
later.
