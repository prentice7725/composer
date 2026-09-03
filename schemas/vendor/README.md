# Vendored: Portrait Bundle v1 (upstream contract)

`portrait-bundle-v1.schema.json` in this directory is a **verbatim copy** of
the producer-owned contract from `prentice7725/seethrough-portrait`:

- Source: `docs/portrait-bundle-v1.schema.json`
- Pinned at commit: `74fecfd9ddd2a9ed2f6d34d5baa93ba3a84d96a5` (`main`)
- Companion prose spec vendored alongside it at
  [../../docs/PORTRAIT_BUNDLE_V1.md](../../docs/PORTRAIT_BUNDLE_V1.md)
  (same commit).

Composer does **not** own this schema -- `seethrough-portrait` does. It is
vendored here only so `portrait_composer/bundle.py`'s reader and the fixtures
under `tests/fixtures/portrait_bundles/` can be checked against it (and so
CI doesn't need network access to `seethrough-portrait` to run). If
`seethrough-portrait` bumps the schema, re-pull both files from that repo at
the new commit and update the pinned SHA above -- do not hand-edit this copy.
