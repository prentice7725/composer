from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly, instance_id_for
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.render import render_reference


def test_identity_assembly_preserves_layers_and_order(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources = identity_assembly(bundle)

    assert set(document.assets.keys()) == {"body", "topwear", "head"}
    assert document.composition["draw_order"] == [
        instance_id_for("body"),
        instance_id_for("topwear"),
        instance_id_for("head"),
    ]
    assert document.composition["canvas"] == {"width": 40, "height": 40}

    for layer_id in ("body", "topwear", "head"):
        inst_id = instance_id_for(layer_id)
        inst = document.instances[inst_id]
        assert inst.asset_ref == layer_id
        assert inst.transform.is_identity()
        assert inst_id in image_sources

        records = document.provenance.for_target(inst_id)
        assert len(records) == 1
        assert records[0].operation == "identity_import"
        assert records[0].sources == ["A001"]

    assert document.validate().ok


def test_identity_reference_matches_seethrough_canonical_composite(portrait_bundle: Path, tmp_path: Path):
    """Acceptance criterion, directive #9: Composer reference == SeeThrough
    canonical composite. We approximate "the canonical composite" as a
    plain alpha-composite of the portrait bundle's own layers in its own
    draw order -- exactly what identity import must reproduce unchanged."""
    bundle = read_portrait_bundle(portrait_bundle)

    expected = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for layer in sorted(bundle.layers, key=lambda l: l.draw_order):
        with Image.open(bundle.layer_path(layer)) as im:
            expected.alpha_composite(im.convert("RGBA"))

    document, image_sources = identity_assembly(bundle)
    out_dir = tmp_path / "out.assembly"
    write_assembly_bundle(document, image_sources, out_dir)

    actual = Image.open(out_dir / "reference.png").convert("RGBA")
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()


def test_write_then_read_assembly_bundle_round_trips(portrait_bundle: Path, tmp_path: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources = identity_assembly(bundle)
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
