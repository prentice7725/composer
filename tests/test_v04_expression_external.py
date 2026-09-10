from pathlib import Path

from PIL import Image

from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.assembly import identity_assembly
from portrait_composer.donor_slots import set_donor_slot
from portrait_composer.expressions import build_expression_intent
from portrait_composer.external_edit import export_ora, inspect_ora, apply_ora_reimport


def _loaded(portrait_bundle):
    bundle = read_portrait_bundle(portrait_bundle)
    return identity_assembly(bundle)[:2]


def test_expression_intent_is_explicit_and_preserves_articulation(portrait_bundle):
    document, _sources = _loaded(portrait_bundle)
    eyes, mouth = list(document.instances)[:2]
    set_donor_slot(document, "eyes", "open", eyes)
    set_donor_slot(document, "eyes", "closed", eyes)
    set_donor_slot(document, "mouth", "closed", mouth)
    intent = build_expression_intent(document)
    assert intent["profile"] == "face_expression_core_v2"
    assert intent["articulation"]["blink"]["states"]["open"] == eyes
    assert intent["articulation"]["viseme"]["states"]["closed"] == mouth


def test_ora_roundtrip_classifies_pixel_change_and_applies_only_matching_layer(portrait_bundle, tmp_path: Path):
    document, sources = _loaded(portrait_bundle)
    ora, sidecar = export_ora(document, sources, tmp_path / "edit.ora")
    report = inspect_ora(ora, sidecar)
    assert report["layers"]
    instance_id = next(iter(report["layers"]))
    assert report["layers"][instance_id] == "UNCHANGED"

    import zipfile
    changed = Image.new("RGBA", (16, 16), (255, 20, 20, 255))
    import io
    payload = io.BytesIO()
    changed.save(payload, format="PNG")
    rewritten = tmp_path / "changed.ora"
    with zipfile.ZipFile(ora) as source, zipfile.ZipFile(rewritten, "w") as target:
        for item in source.infolist():
            data = payload.getvalue() if item.filename == report["external"][instance_id]["src"] else source.read(item.filename)
            target.writestr(item, data)
    report = inspect_ora(rewritten, sidecar)
    assert report["layers"][instance_id] == "PIXELS_CHANGED"
    applied = apply_ora_reimport(document, sources, rewritten, sidecar, tmp_path / "reimport")
    assert instance_id in applied["applied"]
