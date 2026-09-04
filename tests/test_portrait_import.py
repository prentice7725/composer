from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from portrait_composer.bundle import BundleError
from portrait_composer.ui.portrait_import import PortraitInputWorkspace


def test_portrait_input_reads_directory_and_zip(portrait_bundle: Path, tmp_path: Path):
    workspace = PortraitInputWorkspace()
    directory_input = workspace.read(portrait_bundle)
    assert directory_input.root == portrait_bundle
    assert directory_input.label == "sample"

    archive = tmp_path / "A001.portrait.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in portrait_bundle.rglob("*"):
            if path.is_file():
                output.write(path, Path("A001.portrait") / path.relative_to(portrait_bundle))
    zip_input = workspace.read(archive)
    assert zip_input.root != archive
    assert zip_input.root.joinpath("manifest.json").exists()
    assert zip_input.label == "A001"
    workspace.cleanup()


def test_portrait_zip_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "no")
    workspace = PortraitInputWorkspace()
    with pytest.raises(BundleError, match="unsafe path"):
        workspace.prepare(archive)
    workspace.cleanup()

