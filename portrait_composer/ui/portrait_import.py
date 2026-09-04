"""Portrait Bundle input preparation for the optional GUI.

The core reader remains directory-based.  This adapter adds the WebUI-friendly
``.zip`` input without changing the Portrait Bundle contract or the headless
Composer APIs.
"""
from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..bundle import BundleError, PortraitBundle, read_portrait_bundle


@dataclass(frozen=True)
class PreparedPortraitInput:
    """A validated input root and its stable run label."""

    source_path: Path
    root: Path
    label: str
    bundle: PortraitBundle


class PortraitInputWorkspace:
    """Owns temporary extraction directories for the lifetime of the GUI."""

    def __init__(self) -> None:
        self._temporary_directories: list[tempfile.TemporaryDirectory] = []

    def prepare(self, source_path: Path) -> Path:
        source_path = Path(source_path)
        if source_path.is_dir():
            return source_path
        if not source_path.is_file() or source_path.suffix.lower() != ".zip":
            raise BundleError(f"Portrait input must be a .portrait directory or .zip: {source_path}")

        temporary = tempfile.TemporaryDirectory(prefix="portrait-composer-input-")
        self._temporary_directories.append(temporary)
        destination = Path(temporary.name)
        self._extract_zip_safely(source_path, destination)
        manifests = list(destination.rglob("manifest.json"))
        if len(manifests) != 1:
            raise BundleError(
                f"Portrait ZIP must contain exactly one Bundle manifest.json; found {len(manifests)}"
            )
        return manifests[0].parent

    @staticmethod
    def _extract_zip_safely(source_path: Path, destination: Path) -> None:
        destination = destination.resolve()
        with zipfile.ZipFile(source_path) as archive:
            for member in archive.infolist():
                # Reject Unix symlink entries; resolving a symlink after extraction
                # could escape the temporary workspace.
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise BundleError(f"Portrait ZIP contains an unsupported symlink: {member.filename!r}")
                target = (destination / member.filename).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise BundleError(f"Portrait ZIP contains an unsafe path: {member.filename!r}") from exc
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))

    def read(self, source_path: Path) -> PreparedPortraitInput:
        root = self.prepare(source_path)
        bundle = read_portrait_bundle(root)
        source_path = Path(source_path)
        label = source_path.stem
        if label.lower().endswith(".portrait"):
            label = label[: -len(".portrait")]
        label = label or root.name
        return PreparedPortraitInput(source_path, root, label, bundle)

    def cleanup(self) -> None:
        for temporary in reversed(self._temporary_directories):
            temporary.cleanup()
        self._temporary_directories.clear()

