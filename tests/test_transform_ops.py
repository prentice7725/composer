from __future__ import annotations

from pathlib import Path

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.transform_ops import align_instance, fit_instance, flip_transform, nudge_transform, reset_transform

from .conftest import make_portrait_bundle


def _doc(tmp_path: Path):
    bundle = read_portrait_bundle(make_portrait_bundle(tmp_path / "in.portrait"))
    return identity_assembly(bundle)[0]


def test_transform_fit_flip_align_and_reset_are_transactional(tmp_path: Path):
    document = _doc(tmp_path)
    instance_id = "topwear__instance"

    fit_instance(document, instance_id, mode="bbox", image_size=(40, 20), target=(10, 20, 100, 100))
    transform = document.instances[instance_id].transform
    assert transform.scale_x == 2.5
    assert transform.scale_y == 2.5

    align_instance(document, instance_id, anchor="bottom_right", image_size=(40, 20), target=(10, 20, 100, 100))
    assert (transform.x, transform.y) == (10.0, 70.0)
    flip_transform(document, instance_id, horizontal=True)
    assert transform.scale_x == -2.5
    nudge_transform(document, instance_id, dx=3, dy=-2)
    assert (transform.x, transform.y) == (13.0, 68.0)

    reset_transform(document, instance_id)
    assert document.instances[instance_id].transform.is_identity()
    document.undo()
    assert document.instances[instance_id].transform.scale_x == -2.5

