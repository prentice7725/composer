# portrait-composer

Semantic Portrait Assembly & Authoring Tool.

Composer sits between `seethrough-portrait` (source truth) and
`portrait-autorig` (rig truth) in the pipeline described in
[docs/SEETHROUGH_COMPOSER_AUTORIG_RESPONSIBILITY_VERSIONUP_MASTER_v0.2.md](docs/SEETHROUGH_COMPOSER_AUTORIG_RESPONSIBILITY_VERSIONUP_MASTER_v0.2.md).
Its responsibility is **assembly truth**: what a character is built from,
where it's placed, and what may move -- never mesh/deformation/physics.

Full spec: [docs/PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md](docs/PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md).
Current implementation status: [STATUS.md](STATUS.md) (**C0 only** -- see
there before assuming C1-C4 features exist).

## Install

```sh
pip install -e ".[dev]"
```

## CLI

```sh
portrait-composer identity IN.portrait -o OUT.assembly
portrait-composer validate OUT.assembly
portrait-composer render OUT.assembly
portrait-composer apply IN.portrait recipe.json -o OUT.assembly
portrait-composer remap OUT.assembly NEW.portrait
```

`IN.portrait` is a **Portrait Bundle v1**, the real contract produced by
[`prentice7725/seethrough-portrait`](https://github.com/prentice7725/seethrough-portrait)
-- see [docs/PORTRAIT_BUNDLE_V1.md](docs/PORTRAIT_BUNDLE_V1.md) and the
reader's own notes at the top of
[portrait_composer/bundle.py](portrait_composer/bundle.py).

## Tests

```sh
python -m pytest
```
