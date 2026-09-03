from __future__ import annotations

import json
from pathlib import Path

from portrait_composer.cli import main


def test_cli_identity_validate_render(portrait_bundle: Path, tmp_path: Path, capsys):
    out_dir = tmp_path / "out.assembly"
    assert main(["identity", str(portrait_bundle), "-o", str(out_dir)]) == 0
    assert (out_dir / "reference.png").exists()

    assert main(["validate", str(out_dir)]) == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out

    assert main(["render", str(out_dir)]) == 0


def test_cli_validate_fails_on_missing_reference(portrait_bundle: Path, tmp_path: Path):
    out_dir = tmp_path / "out.assembly"
    main(["identity", str(portrait_bundle), "-o", str(out_dir)])
    (out_dir / "reference.png").unlink()

    assert main(["validate", str(out_dir)]) == 1


def test_cli_apply_recipe_hides_a_layer(portrait_bundle: Path, tmp_path: Path):
    recipe = {"operations": [{"op": "set_visible", "instance": "topwear__instance", "value": False}]}
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    out_dir = tmp_path / "out.assembly"
    assert main(["apply", str(portrait_bundle), str(recipe_path), "-o", str(out_dir)]) == 0

    from portrait_composer.bundle import read_assembly_bundle
    document = read_assembly_bundle(out_dir)
    assert document.instances["topwear__instance"].visible is False


def test_cli_apply_rejects_unknown_op(portrait_bundle: Path, tmp_path: Path):
    recipe = {"operations": [{"op": "not_a_real_op"}]}
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    out_dir = tmp_path / "out.assembly"
    assert main(["apply", str(portrait_bundle), str(recipe_path), "-o", str(out_dir)]) != 0
    assert not out_dir.exists()


def test_cli_remap_reports_unresolved_and_exits_nonzero(portrait_bundle: Path, tmp_path: Path):
    from .conftest import make_portrait_bundle

    out_dir = tmp_path / "out.assembly"
    main(["identity", str(portrait_bundle), "-o", str(out_dir)])

    new_root = make_portrait_bundle(
        tmp_path / "new.portrait",
        layers=[
            ("body", "body", 10, (255, 0, 0, 255)),
            ("head", "head", 60, (0, 0, 255, 255)),
        ],
    )

    assert main(["remap", str(out_dir), str(new_root)]) == 1


def test_cli_remap_exits_zero_when_fully_resolved(portrait_bundle: Path, tmp_path: Path):
    out_dir = tmp_path / "out.assembly"
    main(["identity", str(portrait_bundle), "-o", str(out_dir)])

    assert main(["remap", str(out_dir), str(portrait_bundle)]) == 0
