"""Public GUI launcher facade.

PySide6 is intentionally imported only when the GUI is launched, so all
headless CLI/core commands remain usable without the optional GUI extra.
"""
from __future__ import annotations


class GuiUnavailableError(RuntimeError):
    pass


def launch(argv: list[str] | None = None) -> int:
    """Launch C5-A without importing PySide6 at module import time."""
    try:
        from .ui.app import run_gui
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise GuiUnavailableError(
                "PySide6 is required for the GUI; install with `pip install -e .[gui]`"
            ) from exc
        raise
    return run_gui(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return launch(argv)
    except GuiUnavailableError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
