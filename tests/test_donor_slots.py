from __future__ import annotations

from pathlib import Path

from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from portrait_composer.donor_slots import donor_slot_status, slot_for_donor_semantic
from portrait_composer.donors import import_donor


def test_face_expression_core_slot_vocabulary_is_canonical():
    assert slot_for_donor_semantic("eyes_closed") == ("eyes", "closed")
    assert slot_for_donor_semantic("blink") == ("eyes", "closed")
    assert slot_for_donor_semantic("mouth_a") == ("mouth", "a")
    assert slot_for_donor_semantic("viseme_o") == ("mouth", "o")
    assert slot_for_donor_semantic("mouth_open") is None


def test_expression_donor_registers_slot_and_survives_assembly_reload(portrait_bundle, tmp_path: Path):
    document, image_sources, _warnings = identity_assembly(read_portrait_bundle(portrait_bundle))
    donor_path = tmp_path / "mouth-a.png"
    Image.new("RGBA", (20, 20), (220, 80, 80, 255)).save(donor_path)

    result = import_donor(
        document,
        donor_path,
        semantic="mouth_a",
        image_sources=image_sources,
        work_dir=tmp_path / "donor-work",
    )

    assert donor_slot_status(document, "mouth", "a") == "READY"
    assert document.donor_slots["mouth"]["a"]["source_instance"] == result.instance_id
    assert document.variant_sets["mouth_state"]["state_labels"][result.instance_id] == "a"

    out_dir = write_assembly_bundle(document, image_sources, tmp_path / "assembly")
    reloaded = read_assembly_bundle(out_dir)
    assert reloaded.donor_slots == document.donor_slots

