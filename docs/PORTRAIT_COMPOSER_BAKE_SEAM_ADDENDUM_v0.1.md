# Bake Seam Repair / Semantic Merge Bake Addendum v0.1

This addendum extends `PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.3.md`.

## Contract

Bake has two modes:

- `flatten`: ordinary alpha composite; seam repair is off by default.
- `semantic_merge`: creates a new semantic layer and applies deterministic
  contact-zone seam repair.

Semantic merge never mutates source PNGs or source masks. Its output records
the selected `mode`, `seam_policy`, and deterministic repair report in derived
asset provenance.

## Seam policy

```json
{
  "cleanup": "auto",
  "expand_under": 1,
  "remove_internal_lines": true,
  "contact_band_px": 1,
  "ownership_rule": "topwear_with_arms"
}
```

`cleanup` is `off | auto | aggressive`; `expand_under` is `0..2` and
`contact_band_px` is `1..2`. Named profiles currently include
`topwear_with_arms`, `body_with_sleeves`, and `coat_full`.

The implementation performs source composite, contact-zone detection,
under-layer expansion, optional internal-line cleanup, and canonical raster
output. Mesh inversion/stretch, physics constants, and deformer calculations
remain AutoRig responsibilities.

## Exit criteria

- seam policy serializes through Bake Plan save/reload
- source hashes remain unchanged
- derived output changes for expansion and cleanup settings
- Bake remains one undo/redo transaction
- merged output remains eligible for Rig Bundle export
