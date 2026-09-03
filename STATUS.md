# Implementation Status

Tracks directive exit checklists (`PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md`
#32-34). Only **C0** is implemented.

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

## Known gap: Portrait Bundle input contract

`seethrough-portrait` doesn't exist yet, so `bundle.py` defines an interim
Portrait Bundle shape (manifest.json + layers/*.png) that Composer's C0
needs. This should be reconciled against the real upstream format once
that project lands -- see the docstring at the top of `bundle.py`.

## Not implemented at all

`gui.py`, `workflow.py`, `compatibility.py`, `donors.py`, `expressions.py`,
`secondary_regions.py` are present as stub modules (matching the directive's
repository layout, #2) that raise `NotImplementedError` -- each one's
docstring names the phase and directive section it belongs to.
