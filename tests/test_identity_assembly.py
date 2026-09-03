from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly, instance_id_for
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.render import render_reference

from .conftest import make_portrait_bundle

TAGS = ("neck", "topwear", "head")


def test_identity_assembly_preserves_layers_and_order(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, warnings = identity_assembly(bundle)

    assert set(document.assets.keys()) == set(TAGS)
    assert document.composition["draw_order"] == [instance_id_for(t) for t in TAGS]
    assert document.composition["canvas"]["width"] == 40
    assert document.composition["canvas"]["height"] == 40
    assert warnings == []

    for tag in TAGS:
        inst_id = instance_id_for(tag)
        inst = document.instances[inst_id]
        assert inst.asset_ref == tag
        assert inst.transform.is_identity()
        assert inst_id in image_sources

        records = document.provenance.for_target(inst_id)
        assert len(records) == 1
        assert records[0].operation == "identity_import"
        assert records[0].sources == ["A001"]
        assert records[0].extra["generation"]["source_identity"] == "A001"

    assert document.validate().ok


def test_identity_never_reads_raw_layers(tmp_path: Path):
    """The 'layers/ is canonical, raw_layers/ is forensic-only' rule
    (PORTRAIT_BUNDLE_V1.md), reproducing the real missing_eyewhite scenario:
    raw_layers has a candidate the producer's recovery ladder rejected, and
    it must never become a Composer asset."""
    root = make_portrait_bundle(
        tmp_path / "a.portrait",
        raw_layers={"eyewhite": (250, 250, 250, 255)},
        semantic_warnings=["missing_eyewhite"],
    )
    bundle = read_portrait_bundle(root)
    document, image_sources, warnings = identity_assembly(bundle)

    assert "eyewhite" not in document.assets
    assert not any("eyewhite" in str(p) for p in image_sources.values())
    assert not any("raw_layers" in str(p) for p in image_sources.values())
    assert warnings == ["semantic warning: missing_eyewhite"]


def test_identity_reference_matches_seethrough_canonical_composite(portrait_bundle: Path, tmp_path: Path):
    """Acceptance criterion, directive #9: Composer reference == SeeThrough
    canonical composite. We approximate "the canonical composite" as a
    plain alpha-composite of the bundle's own layers/ in semantics.z_order --
    exactly what identity import must reproduce unchanged."""
    bundle = read_portrait_bundle(portrait_bundle)

    expected = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for layer in bundle.layers:  # already z_order-sorted
        with Image.open(bundle.layer_path(layer)) as im:
            expected.alpha_composite(im.convert("RGBA"))

    document, image_sources, _ = identity_assembly(bundle)
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)

    actual = Image.open(out_dir / "reference.png").convert("RGBA")
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()


def test_write_then_read_assembly_bundle_round_trips(portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _ = identity_assembly(bundle)
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)

    assert (out_dir / "reference.png").exists()
    assert (out_dir / "manifest.json").exists()
    for sub in ("layers", "expressions", "masks", "diagnostics"):
        assert (out_dir / sub).is_dir()

    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.to_dict() == document.to_dict()

    # render.py must be independently able to reproduce reference.png from
    # the written bundle (not just from the in-memory document).
    rerendered = render_reference(reloaded, out_dir / "layers")
    original = Image.open(out_dir / "reference.png").convert("RGBA")
    assert rerendered.tobytes() == original.tobytes()
