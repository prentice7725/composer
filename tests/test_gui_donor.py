"""Qt-free tests for the C5-E Donor Align command layer (directive
#34.2). No PySide6 import anywhere in this module."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from portrait_composer.assembly import identity_assembly
from portrait_composer.bundle import read_portrait_bundle
from portrait_composer.donors import DonorDriftError
from portrait_composer.ui.commands import import_donor_asset


@pytest.fixture
def loaded(portrait_bundle: Path):
    bundle = read_portrait_bundle(portrait_bundle)
    document, image_sources, _warnings = identity_assembly(bundle)
    return document, image_sources


def _donor_file(tmp_path: Path, size=(20, 20)) -> Path:
    path = tmp_path / "donor.png"
    Image.new("RGBA", size, (200, 40, 40, 255)).save(path)
    return path


def test_aligned_donor_import_is_one_undo_step(loaded, tmp_path: Path):
    document, image_sources = loaded
    donor_path = _donor_file(tmp_path)
    revision_before = document.history.revision

    result = import_donor_asset(
        document,
        image_sources,
        donor_path,
        semantic="mouth",
        donor_size=(20, 20),
        alignment={"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0},
        target_roi={"x": 0, "y": 0, "width": 20, "height": 20},
        target_size=(40, 40),
        target_rotation=0.0,
        allow_drift=False,
    )

    assert result.drift.ok
    assert result.instance_id in document.instances
    assert image_sources[result.instance_id] == result.image_path
    assert document.history.revision == revision_before + 1

    document.undo()
    assert result.instance_id not in document.instances
    assert result.asset_id not in document.assets


def test_hard_drift_blocks_commit_by_default(loaded, tmp_path: Path):
    document, image_sources = loaded
    donor_path = _donor_file(tmp_path)
    revision_before = document.history.revision

    with pytest.raises(DonorDriftError):
        import_donor_asset(
            document,
            image_sources,
            donor_path,
            semantic="mouth",
            donor_size=(20, 20),
            alignment={"x": 500.0, "y": 500.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0},
            target_roi={"x": 0, "y": 0, "width": 20, "height": 20},
            target_size=(40, 40),
            target_rotation=0.0,
            allow_drift=False,
        )
    assert document.history.revision == revision_before
    assert not any(a.startswith("mouth__donor") for a in document.assets)


def test_allow_drift_override_lets_a_failing_alignment_commit(loaded, tmp_path: Path):
    document, image_sources = loaded
    donor_path = _donor_file(tmp_path)

    result = import_donor_asset(
        document,
        image_sources,
        donor_path,
        semantic="mouth",
        donor_size=(20, 20),
        alignment={"x": 500.0, "y": 500.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0},
        target_roi={"x": 0, "y": 0, "width": 20, "height": 20},
        target_size=(40, 40),
        target_rotation=0.0,
        allow_drift=True,
    )

    assert not result.drift.ok
    assert result.instance_id in document.instances


def test_import_donor_asset_records_provenance(loaded, tmp_path: Path):
    document, image_sources = loaded
    donor_path = _donor_file(tmp_path)

    result = import_donor_asset(
        document,
        image_sources,
        donor_path,
        semantic="mouth",
        donor_size=(20, 20),
        alignment={"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0},
        target_roi={"x": 0, "y": 0, "width": 20, "height": 20},
        target_size=(40, 40),
        target_rotation=0.0,
        allow_drift=False,
    )

    records = document.provenance.for_target(result.instance_id)
    assert records and records[-1].operation == "donor_import"
    assert document.assets[result.asset_id].provenance["operation"] == "donor_import"
