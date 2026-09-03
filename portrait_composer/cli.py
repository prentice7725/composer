"""CLI.

Directive refs: PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md #31.

    portrait-composer identity IN -o OUT
    portrait-composer validate OUT
    portrait-composer render OUT
    portrait-composer apply IN recipe.json -o OUT
    portrait-composer remap OLD NEW

``remap`` is read-only/report-only in this CLI (it never silently rewrites
a bundle -- #8: "silent guess 금지"). Applying a resolved remap is exposed
as a Python API (remap.apply_auto_resolvable_remap / apply_manual_remap)
for now; wiring that into a CLI subcommand is C1+ territory since it needs
harvesting updated layer images, not just rebinding ids.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assembly import RecipeError, apply_recipe, identity_assembly
from .bundle import BundleError, assembly_layers_dir, read_assembly_bundle, read_portrait_bundle, write_assembly_bundle
from .document import TransactionValidationError
from .remap import classify_remap
from .render import render_reference


def cmd_identity(args: argparse.Namespace) -> int:
    try:
        bundle = read_portrait_bundle(Path(args.IN))
    except BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        document, image_sources, import_warnings = identity_assembly(bundle)
    except TransactionValidationError as e:
        print("identity import failed validation:", file=sys.stderr)
        for err in e.result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    write_assembly_bundle(document, image_sources, Path(args.out))
    result = document.validate()
    print(f"wrote assembly bundle: {args.out}")
    for w in import_warnings:
        print(f"warning: {w}")
    for w in result.warnings:
        print(f"warning: {w}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    out_dir = Path(args.OUT)
    document = read_assembly_bundle(out_dir)
    result = document.validate()

    errors = list(result.errors)
    if not (out_dir / "reference.png").exists():
        errors.append("missing reference.png")

    for w in result.warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)

    if errors:
        print(f"INVALID ({len(errors)} error(s))")
        return 1
    print("OK")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    out_dir = Path(args.OUT)
    document = read_assembly_bundle(out_dir)
    layers_dir = assembly_layers_dir(out_dir)
    image = render_reference(document, layers_dir)
    ref_path = out_dir / "reference.png"
    image.save(ref_path)
    print(f"rendered: {ref_path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        bundle = read_portrait_bundle(Path(args.IN))
    except BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))

    try:
        document, image_sources, import_warnings = identity_assembly(bundle)
        apply_recipe(document, recipe, image_sources)
    except TransactionValidationError as e:
        print("apply failed validation:", file=sys.stderr)
        for err in e.result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    except RecipeError as e:
        print(f"apply failed: {e}", file=sys.stderr)
        return 1

    write_assembly_bundle(document, image_sources, Path(args.out))
    print(f"wrote assembly bundle: {args.out}")
    for w in import_warnings:
        print(f"warning: {w}")
    return 0


def cmd_remap(args: argparse.Namespace) -> int:
    old_document = read_assembly_bundle(Path(args.OLD))
    try:
        new_bundle = read_portrait_bundle(Path(args.NEW))
    except BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    report = classify_remap(old_document, new_bundle)

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.all_resolved:
        print(
            f"UNRESOLVED: {len(report.unresolved)} asset(s) need manual remap "
            "(AMBIGUOUS/ORPHANED are never auto-resolved)",
            file=sys.stderr,
        )
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portrait-composer")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("identity", help="convert one Portrait Bundle into an Assembly Bundle unchanged")
    p.add_argument("IN")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_identity)

    p = sub.add_parser("validate", help="validate an Assembly Bundle")
    p.add_argument("OUT")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("render", help="re-render reference.png for an Assembly Bundle")
    p.add_argument("OUT")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("apply", help="apply a recipe to a Portrait Bundle, producing an Assembly Bundle")
    p.add_argument("IN")
    p.add_argument("recipe")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("remap", help="classify remap status of an Assembly Bundle against an updated Portrait Bundle")
    p.add_argument("OLD")
    p.add_argument("NEW")
    p.set_defaults(func=cmd_remap)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
