"""Portrait Bundle (input) / Assembly Bundle (output) I/O.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #29;
SEETHROUGH_..._MASTER_v0.2.md #1-2.

Portrait Bundle input is the real, producer-owned **Portrait Bundle v1**
contract from `prentice7725/seethrough-portrait`
(docs/PORTRAIT_BUNDLE_V1.md, docs/portrait-bundle-v1.schema.json in that
repo; vendored read-only copies live at
schemas/vendor/portrait-bundle-v1.schema.json and
docs/PORTRAIT_BUNDLE_V1.md in this repo -- see schemas/vendor/README.md for
provenance). This replaces the C0-era interim contract this module used to
invent. Summary of what a reader must do, per that spec:

- reject an unknown major `version` (only "1.x" is understood here);
- `canvas.coordinate_system/color_space/alpha` must be exactly
  top-left-y-down / srgb / straight -- Composer's compositor assumes this;
- `layer_contract.canonical_stage` must be `production_repaired`; Composer
  never runs fidelity repair itself, so anything else is a hard reject;
- `layers[tag]` is `{path, source_tag}`, not a bare path -- `layers/` is the
  only canonical, harvestable input;
- `raw_layers/`, when present, is forensic-only and MUST NOT be used as a
  fallback for a missing canonical layer (enforced here by simply never
  reading it into `image_sources`);
- every canonical layer tag must appear in `semantics.z_order`, which is
  the producer's *reconstruction* order, not a downstream draw order --
  Composer only uses it to seed each LayerInstance's initial `draw_order`;
- rig-specific subdivisions (`head_remainder`, `neck_remainder`) are
  forbidden in the canonical layer set -- an explicit denylist, not a
  `*_remainder` wildcard: `body_remainder` is itself a canonical producer
  tag (SEMANTIC_Z_ORDER's first entry upstream), and native sided semantic
  tags (`eyel`/`eyer`, `earl`/`earr`, `eyewhitel`/`eyewhiter`,
  `iridesl`/`iridesr`, `eyelashl`/`eyelashr`, `eyebrowl`/`eyebrowr`, ...)
  are legitimate producer content, not the "left/right eye splits" the
  spec prose means to ban -- see PORTRAIT_BUNDLE_V1.md's note reconciling
  this;
- `generation` (seed_mode/attempt_index/seed/canonical_regression_seed/
  source_identity) is reproducibility provenance and is preserved onto the
  registered SourceAsset + every provenance record, not discarded;
- `semantics.warnings`, non-"pass" `validation` statuses, and high-risk
  edges in `diagnostics/occlusion_graph.json` (when present) are surfaced
  as import warnings -- never as hard errors, and never synthesized when
  the occlusion diagnostic is simply absent ("not computed" != "no risk").

Assembly Bundle (output, directive #29) is unrelated and unchanged by this
sync -- it's Composer's own v0.2 output contract:

    A001.assembly/
        manifest.json
        reference.png
        layers/
        expressions/
        masks/
        diagnostics/
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .document import AssemblyDocument
from .render import render_reference

ASSEMBLY_FORMAT = "portrait-assembly"
ASSEMBLY_VERSION = "0.2"

PORTRAIT_FORMAT = "portrait-bundle"
PORTRAIT_MAJOR_VERSION = "1"
_VERSION_RE = re.compile(r"^(\d+)\.\d+$")

_REQUIRED_CANVAS = {
    "coordinate_system": "top-left-y-down",
    "color_space": "srgb",
    "alpha": "straight",
}
_CANONICAL_STAGE = "production_repaired"

# Rig-specific subdivisions are forbidden in the canonical layer set
# (PORTRAIT_BUNDLE_V1.md) -- an explicit denylist, not a "*_remainder"
# wildcard: "body_remainder" is itself a canonical producer tag (unresolved
# semantic-ownership residual, first entry of SEMANTIC_Z_ORDER upstream),
# and nothing rules out the producer sanctioning another *_remainder tag
# later. Only these two are known Composer/AutoRig-invented rig-specific
# subdivisions today; extend this set, don't wildcard it.
_FORBIDDEN_TAGS = {"head_remainder", "neck_remainder"}

# Above this measured disocclusion_risk, an occlusion_graph.json edge is
# surfaced as an import warning. This threshold is Composer's own display
# choice, not part of the producer contract -- the producer explicitly
# emits no verdict, only a measured score (PORTRAIT_BUNDLE_V1.md).
_OCCLUSION_RISK_WARNING_THRESHOLD = 0.5


class BundleError(Exception):
    pass


@dataclass
class PortraitBundleLayer:
    """One canonical (``layers/``) entry.

    ``id`` is a compatibility alias for ``tag`` (the exact dict key/binding
    identity -- what EXACT_MATCH in remap.py compares). ``semantic`` aliases
    ``source_tag``: today's single producer always sets ``source_tag ==
    tag``, but the schema keeps them independently meaningful (a future
    producer, or a manually-remapped layer, may key a layer under a new
    ``tag`` while recording the semantic it originated from in
    ``source_tag``) -- that's the field remap.py's SEMANTIC_MATCH/AMBIGUOUS
    classify against when an exact id match fails.
    """

    tag: str
    path: str  # "layers/<tag>.png", relative to the bundle root
    source_tag: str
    draw_order: int  # seeded from position in semantics.z_order (index * 10)

    @property
    def id(self) -> str:
        return self.tag

    @property
    def semantic(self) -> str:
        return self.source_tag


@dataclass
class PortraitBundle:
    root: Path
    version: str
    canvas: dict
    semantics: dict
    generation: dict
    layers: list  # list[PortraitBundleLayer], sorted by draw_order
    raw_layers: dict  # tag -> "raw_layers/<tag>.png" -- forensic only, never harvested
    layer_contract: dict
    diagnostics: dict  # name -> relative path
    validation: dict
    source: dict
    warnings: list  # import-time warnings surfaced from the bundle's own diagnostics

    def layer_path(self, layer: PortraitBundleLayer) -> Path:
        return self.root / layer.path

    @property
    def source_identity(self) -> Optional[str]:
        return self.generation.get("source_identity")


def source_id_for(bundle: PortraitBundle) -> str:
    """The SourceAsset id a bundle registers under.

    Prefers ``generation.source_identity`` (present for
    ``deterministic_auto`` seed mode), falls back to the source filename
    stem, then to the bundle directory name. Centralized here so
    assembly.py's identity import and remap.py's reimport agree on it.
    """
    return bundle.source_identity or Path(bundle.source.get("filename", "")).stem or bundle.root.name


def _require(manifest: dict, key: str, manifest_path: Path) -> object:
    if key not in manifest:
        raise BundleError(f"{manifest_path}: missing required field {key!r}")
    return manifest[key]


def read_portrait_bundle(path: Path) -> PortraitBundle:
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise BundleError(f"not a portrait bundle (missing manifest.json): {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    fmt = _require(manifest, "format", manifest_path)
    if fmt != PORTRAIT_FORMAT:
        raise BundleError(f"{manifest_path}: unexpected format {fmt!r}")

    version = str(_require(manifest, "version", manifest_path))
    m = _VERSION_RE.match(version)
    if not m or m.group(1) != PORTRAIT_MAJOR_VERSION:
        raise BundleError(
            f"{manifest_path}: unsupported major version {version!r} "
            f"(this reader only understands Portrait Bundle v{PORTRAIT_MAJOR_VERSION}.x)"
        )

    canvas = dict(_require(manifest, "canvas", manifest_path))
    for key, expected in _REQUIRED_CANVAS.items():
        actual = canvas.get(key)
        if actual != expected:
            raise BundleError(
                f"{manifest_path}: canvas.{key} = {actual!r}, expected {expected!r} "
                "(Composer's compositor assumes this contract)"
            )
    if "width" not in canvas or "height" not in canvas:
        raise BundleError(f"{manifest_path}: canvas missing width/height")

    layer_contract = dict(_require(manifest, "layer_contract", manifest_path))
    stage = layer_contract.get("canonical_stage")
    if stage != _CANONICAL_STAGE:
        raise BundleError(
            f"{manifest_path}: layer_contract.canonical_stage = {stage!r}, "
            f"expected {_CANONICAL_STAGE!r} -- Composer never runs fidelity "
            "repair itself and refuses a bundle that hasn't already had it"
        )

    semantics = dict(_require(manifest, "semantics", manifest_path))
    z_order = list(semantics.get("z_order", []))

    generation = dict(_require(manifest, "generation", manifest_path))
    validation = dict(_require(manifest, "validation", manifest_path))
    source = dict(manifest.get("source", {}))
    diagnostics = dict(manifest.get("diagnostics", {}))

    raw_layers = dict(manifest.get("raw_layers", {}))  # forensic only -- never harvested

    layers_raw = dict(_require(manifest, "layers", manifest_path))
    layers: list[PortraitBundleLayer] = []
    for tag, entry in layers_raw.items():
        if tag in _FORBIDDEN_TAGS:
            raise BundleError(
                f"{manifest_path}: canonical layer {tag!r} is a rig-specific subdivision "
                "forbidden in the canonical layer set (PORTRAIT_BUNDLE_V1.md)"
            )
        if tag not in z_order:
            raise BundleError(
                f"{manifest_path}: canonical layer {tag!r} has no position in semantics.z_order"
            )
        rel_path = entry["path"]
        if not (path / rel_path).exists():
            raise BundleError(f"{manifest_path}: layer {tag!r} file missing: {rel_path}")
        layers.append(
            PortraitBundleLayer(
                tag=tag,
                path=rel_path,
                source_tag=entry.get("source_tag", tag),
                draw_order=z_order.index(tag) * 10,
            )
        )
    layers.sort(key=lambda l: l.draw_order)

    warnings: list[str] = []
    for w in semantics.get("warnings", []):
        warnings.append(f"semantic warning: {w}")
    for check in ("static_reconstruction", "seams", "local_fidelity"):
        status = validation.get(check)
        if status is not None and status != "pass":
            warnings.append(f"validation.{check} = {status!r}")

    occlusion_rel = diagnostics.get("occlusion_graph")
    if occlusion_rel:
        occlusion_path = path / occlusion_rel
        if occlusion_path.exists():
            occlusion = json.loads(occlusion_path.read_text(encoding="utf-8"))
            for edge in occlusion.get("edges", []):
                risk = edge.get("disocclusion_risk", 0.0)
                if risk >= _OCCLUSION_RISK_WARNING_THRESHOLD:
                    warnings.append(
                        f"occlusion risk: {edge.get('front')!r} over {edge.get('back')!r} "
                        f"(disocclusion_risk={risk})"
                    )
        # absent occlusion_graph.json means "not computed" -- never synthesize a warning for it.

    return PortraitBundle(
        root=path,
        version=version,
        canvas=canvas,
        semantics=semantics,
        generation=generation,
        layers=layers,
        raw_layers=raw_layers,
        layer_contract=layer_contract,
        diagnostics=diagnostics,
        validation=validation,
        source=source,
        warnings=warnings,
    )


def write_assembly_bundle(
    document: AssemblyDocument,
    image_sources: dict,  # instance_id -> Path to source PNG
    out_dir: Path,
    reference_image=None,
) -> Path:
    """Writes a v0.2 Assembly Bundle to ``out_dir``.

    ``image_sources`` maps instance id -> a source PNG path to copy into
    ``layers/<instance_id>.png``. If ``reference_image`` (a PIL Image) is
    not given, it is rendered from ``document`` + the copied layer images.
    """
    out_dir = Path(out_dir)
    layers_dir = out_dir / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("expressions", "masks", "diagnostics"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    for inst_id, src_path in image_sources.items():
        shutil.copyfile(src_path, layers_dir / f"{inst_id}.png")

    if reference_image is None:
        reference_image = render_reference(document, layers_dir)
    reference_image.save(out_dir / "reference.png")

    manifest = {"format": ASSEMBLY_FORMAT, "version": ASSEMBLY_VERSION}
    manifest.update(document.to_dict())
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return out_dir


def read_assembly_bundle(path: Path) -> AssemblyDocument:
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise BundleError(f"not an assembly bundle (missing manifest.json): {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != ASSEMBLY_FORMAT:
        raise BundleError(f"unexpected format in {manifest_path}: {manifest.get('format')!r}")
    if manifest.get("version") != ASSEMBLY_VERSION:
        raise BundleError(
            f"unsupported assembly version in {manifest_path}: {manifest.get('version')!r}; "
            f"this Composer reads exactly {ASSEMBLY_VERSION!r}"
        )
    return AssemblyDocument.from_dict(manifest)


def assembly_layers_dir(path: Path) -> Path:
    return Path(path) / "layers"
