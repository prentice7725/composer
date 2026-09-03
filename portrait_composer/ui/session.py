"""Ephemeral GUI session state (never written to Assembly manifests)."""
from __future__ import annotations

from dataclasses import dataclass, field

CONTEXTS = ("ASSEMBLE", "HARVEST", "VARIANTS", "DONOR", "RIG INTENT", "BAKE")


@dataclass
class UISessionState:
    selected_instance_ids: list[str] = field(default_factory=list)
    selected_asset_id: str | None = None
    active_context: str = "ASSEMBLE"
    canvas_zoom: float = 1.0
    canvas_pan: tuple[float, float] = (0.0, 0.0)
    tree_filter: str = ""
    tree_expansion: set[str] = field(default_factory=set)
    preview_mode: str = "Composite"
    transient_candidate: object | None = None
    open_docks: set[str] = field(default_factory=lambda: {"tree", "inspector", "workbench"})


class SelectionModel:
    """Small Qt-free selection model shared by Tree, Canvas and Inspector."""

    def __init__(self) -> None:
        self.instance_ids: list[str] = []
        self.asset_id: str | None = None
        self._listeners: list = []

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        snapshot = list(self.instance_ids)
        for listener in list(self._listeners):
            listener(snapshot)

    def set_instances(self, instance_ids: list[str], *, asset_id: str | None = None) -> None:
        self.instance_ids = list(dict.fromkeys(instance_ids))
        self.asset_id = asset_id
        self._notify()

    def select(self, instance_id: str, *, additive: bool = False) -> None:
        if additive:
            selected = list(self.instance_ids)
            if instance_id in selected:
                selected.remove(instance_id)
            else:
                selected.append(instance_id)
        else:
            selected = [instance_id]
        self.set_instances(selected)

    def clear(self) -> None:
        self.set_instances([])

    def contains(self, instance_id: str) -> bool:
        return instance_id in self.instance_ids


def sync_session_selection(session: UISessionState, selection: SelectionModel) -> None:
    """Copy selection into ephemeral session state without touching a document."""
    session.selected_instance_ids = list(selection.instance_ids)
    session.selected_asset_id = selection.asset_id
