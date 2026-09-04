"""Core-rendered reference scene with a direct-manipulation transform gizmo."""
from __future__ import annotations

from time import perf_counter
from pathlib import Path

from PIL import Image, ImageChops
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene

from ...instances import Transform
from ...render import _positioned, render_reference, render_subset
from .donor_align import DonorAlignController
from .gizmos import TransformGizmo
from .region_edit import RegionEditController

INSTANCE_ROLE = 32


def _qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    return QImage(raw, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888).copy()


class CanvasScene(QGraphicsScene):
    def __init__(self, selection_model, parent=None):
        super().__init__(parent)
        self.selection_model = selection_model
        self.document = None
        self.layers_dir: Path | None = None
        self.image_sources: dict[str, Path] | None = None
        self.context = "ASSEMBLE"
        self._reference_item: QGraphicsPixmapItem | None = None
        self._hit_items: dict[str, QGraphicsRectItem] = {}
        self._image_sizes: dict[str, tuple[int, int]] = {}
        self._committed_reference: Image.Image | None = None
        self._flicker_timer: QTimer | None = None
        self._flicker_frames: tuple[Image.Image, Image.Image] | None = None
        self._flicker_phase = False
        self.last_render_ms = 0.0
        self._donor_flicker_timer: QTimer | None = None
        self._donor_flicker_phase = False
        self.gizmo = TransformGizmo(self)
        self.donor_ghost = DonorAlignController(self, _qimage)
        self.region_edit = RegionEditController(self)
        selection_model.subscribe(self._refresh_selection)
        self.setBackgroundBrush(QBrush(QColor("#20242b"), Qt.BrushStyle.Dense6Pattern))

    def load_document(
        self,
        document,
        layers_dir: Path,
        image_sources: dict[str, Path] | None = None,
    ) -> None:
        # Detach the gizmo's handle items before clear() deletes the scene's
        # graphics items out from under them.
        self.gizmo.detach()
        self.clear_donor_ghost()
        self.region_edit.clear()
        self.clear_transient_preview()
        self.document = document
        self.layers_dir = Path(layers_dir)
        self.image_sources = image_sources
        self.clear()
        self._hit_items = {}
        self._image_sizes = {}
        canvas = document.composition.get("canvas") or {}
        width, height = canvas.get("width"), canvas.get("height")
        order = document.composition.get("draw_order", [])
        render_started = perf_counter()
        if image_sources is None:
            # Written Assembly Bundles use the canonical layers/<instance>.png
            # convention and the reference renderer remains the truth source.
            reference = render_reference(document, self.layers_dir)
        else:
            # Newly imported Portrait Bundles have producer layer names, so use
            # the same core compositor through its explicit source map.
            reference = render_subset(document, image_sources, order)
        self.last_render_ms = (perf_counter() - render_started) * 1000.0
        width, height = reference.size if width is None or height is None else (width, height)
        self._committed_reference = reference
        self._reference_item = self.addPixmap(QPixmap.fromImage(_qimage(reference)))
        self._reference_item.setZValue(-1000)
        self.setSceneRect(0, 0, width, height)

        for index, instance_id in enumerate(order):
            inst = document.instances.get(instance_id)
            if inst is None or not inst.visible or inst.opacity <= 0:
                continue
            image_w, image_h = self._resolve_image_size(instance_id, width, height)
            self._image_sizes[instance_id] = (image_w, image_h)
            scaled_w = max(1.0, image_w * inst.transform.scale_x)
            scaled_h = max(1.0, image_h * inst.transform.scale_y)
            item = self.addRect(
                QRectF(0, 0, scaled_w, scaled_h),
                QPen(QColor("#59d4ff"), 1.5),
                # Transparent fill keeps the whole instance bounds clickable;
                # NoBrush would make interior hit testing implementation-dependent.
                QBrush(QColor(0, 0, 0, 0)),
            )
            item.setPos(inst.transform.x, inst.transform.y)
            item.setTransformOriginPoint(scaled_w / 2.0, scaled_h / 2.0)
            item.setRotation(inst.transform.rotation)
            item.setData(INSTANCE_ROLE, instance_id)
            item.setZValue(index)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._hit_items[instance_id] = item
        self._refresh_selection(self.selection_model.instance_ids)

    def _resolve_image_path(self, instance_id: str) -> Path | None:
        raw = (
            self.image_sources.get(instance_id)
            if self.image_sources is not None
            else (self.layers_dir / f"{instance_id}.png" if self.layers_dir is not None else None)
        )
        return Path(raw) if raw is not None else None

    def _resolve_image_size(self, instance_id: str, width: int, height: int) -> tuple[int, int]:
        image_path = self._resolve_image_path(instance_id)
        if image_path is not None and image_path.exists():
            with Image.open(image_path) as image:
                return image.size
        return width, height

    def image_size(self, instance_id: str) -> tuple[float, float]:
        return self._image_sizes.get(instance_id, (1.0, 1.0))

    def _refresh_selection(self, selected_ids: list[str]) -> None:
        for instance_id, item in self._hit_items.items():
            active = instance_id in selected_ids
            item.setPen(QPen(QColor("#ffd166" if active else "#59d4ff"), 2.0 if active else 1.0))
            item.setSelected(active)
        if len(selected_ids) == 1 and selected_ids[0] in self._hit_items:
            self.gizmo.attach(selected_ids[0], self._hit_items[selected_ids[0]])
        else:
            self.gizmo.detach()

    def set_context(self, context: str) -> None:
        self.context = context

    # -- transient previews (directive #8.2, #9.3, #18) --------------------
    # Hover/Expression previews are pure Qt-side pixmap swaps: they read the
    # document (existing transforms, variant membership) but never write to
    # it. Every mode renders starting from self._committed_reference, the
    # same pixels the core renderer produced at the last commit -- never a
    # second, separately-drifting compositor.
    def preview_harvest_candidate(self, target_tag: str, candidate_path: Path, mode: str) -> None:
        if self._reference_item is None or self._committed_reference is None:
            return
        self._stop_flicker()
        inst_id = f"{target_tag}__instance"
        existing = self.document.instances.get(inst_id) if self.document is not None else None
        transform = existing.transform if existing is not None else Transform()
        try:
            with Image.open(candidate_path) as raw:
                candidate = raw.convert("RGBA")
                positioned, offset = _positioned(candidate, transform)
        except (FileNotFoundError, OSError):
            return
        base = self._committed_reference
        overlaid = base.copy()
        overlaid.alpha_composite(positioned, dest=offset)

        if mode == "solo":
            preview = Image.new("RGBA", base.size, (0, 0, 0, 0))
            preview.alpha_composite(positioned, dest=offset)
            self._set_preview_pixmap(preview)
        elif mode == "difference":
            diff = ImageChops.difference(base.convert("RGB"), overlaid.convert("RGB"))
            self._set_preview_pixmap(diff.convert("RGBA"))
        elif mode == "flicker":
            self._flicker_frames = (base, overlaid)
            self._flicker_phase = False
            self._flicker_timer = QTimer()
            self._flicker_timer.timeout.connect(self._flicker_tick)
            self._flicker_timer.start(450)
            self._set_preview_pixmap(base)
        else:  # "composite" / "overlay" -- the common default
            self._set_preview_pixmap(overlaid)

    def _flicker_tick(self) -> None:
        if self._flicker_frames is None:
            return
        self._flicker_phase = not self._flicker_phase
        self._set_preview_pixmap(self._flicker_frames[1 if self._flicker_phase else 0])

    def _set_preview_pixmap(self, image: Image.Image) -> None:
        if self._reference_item is not None:
            self._reference_item.setPixmap(QPixmap.fromImage(_qimage(image)))

    def _stop_flicker(self) -> None:
        if self._flicker_timer is not None:
            self._flicker_timer.stop()
            self._flicker_timer.deleteLater()
            self._flicker_timer = None
        self._flicker_frames = None

    def clear_transient_preview(self) -> None:
        self._stop_flicker()
        if self._committed_reference is not None:
            self._set_preview_pixmap(self._committed_reference)

    def preview_variant_selection(self, overrides: dict[str, str]) -> None:
        """Transient preview of applying ``{vs_id: member_id}`` picks
        (directive #9.3's Expression Preview), computed without calling
        variants.set_active -- LayerInstance.visible is never touched."""
        if self.document is None or self._committed_reference is None:
            return
        self._stop_flicker()
        document = self.document
        canvas = document.composition.get("canvas") or {}
        width = canvas.get("width", self._committed_reference.width)
        height = canvas.get("height", self._committed_reference.height)

        resolved_active = {
            vs_id: overrides.get(vs_id, vs.get("active")) for vs_id, vs in document.variant_sets.items()
        }
        member_of: dict[str, str] = {}
        for vs_id, vs in document.variant_sets.items():
            for member_id in vs.get("members", []):
                member_of[member_id] = vs_id

        preview = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for instance_id in document.composition.get("draw_order", []):
            inst = document.instances.get(instance_id)
            if inst is None or inst.opacity <= 0:
                continue
            vs_id = member_of.get(instance_id)
            visible = (instance_id == resolved_active.get(vs_id)) if vs_id is not None else inst.visible
            if not visible:
                continue
            path = self._resolve_image_path(instance_id)
            if path is None or not path.exists():
                continue
            with Image.open(path) as raw:
                layer = raw.convert("RGBA")
                if inst.opacity < 1.0:
                    r, g, b, a = layer.split()
                    a = a.point(lambda v, opacity=inst.opacity: round(v * opacity))
                    layer = Image.merge("RGBA", (r, g, b, a))
                positioned, offset = _positioned(layer, inst.transform)
                preview.alpha_composite(positioned, dest=offset)
        self._set_preview_pixmap(preview)

    # -- C5-E donor align preview modes (directive #10.4) -------------------
    # Target Only / Donor Only / Flicker toggle plain item visibility --
    # the ghost item already tracks the live drag in real time, so no PIL
    # recompositing is needed for those. Difference is the one mode that
    # needs a pixel comparison, computed once per click (a static "visual
    # aid" snapshot, same as Harvest's Difference mode) via the exact same
    # _positioned() placement math the core renderer itself uses.
    def clear_donor_ghost(self) -> None:
        self._stop_donor_flicker()
        self.donor_ghost.clear()
        if self._reference_item is not None:
            self._reference_item.setVisible(True)
        if self._committed_reference is not None:
            self._set_preview_pixmap(self._committed_reference)

    def set_donor_preview_mode(self, mode: str) -> None:
        self._stop_donor_flicker()
        if not self.donor_ghost.active or self._reference_item is None:
            return
        if self._committed_reference is not None:
            self._set_preview_pixmap(self._committed_reference)
        if mode == "target_only":
            self._reference_item.setVisible(True)
            self.donor_ghost.set_visible(False)
        elif mode == "donor_only":
            self._reference_item.setVisible(False)
            self.donor_ghost.set_visible(True)
            self.donor_ghost.set_opacity(1.0)
        elif mode == "flicker":
            self.donor_ghost.set_visible(False)
            self._donor_flicker_phase = False
            self._donor_flicker_timer = QTimer()
            self._donor_flicker_timer.timeout.connect(self._donor_flicker_tick)
            self._donor_flicker_timer.start(450)
            self._donor_flicker_tick()
        elif mode == "difference":
            self._reference_item.setVisible(True)
            self.donor_ghost.set_visible(False)
            self._show_donor_difference()
        else:  # "composite" -- the common default
            self._reference_item.setVisible(True)
            self.donor_ghost.set_visible(True)
            self.donor_ghost.set_opacity(self.donor_ghost.opacity)

    def _donor_flicker_tick(self) -> None:
        if self._reference_item is None:
            return
        self._donor_flicker_phase = not self._donor_flicker_phase
        self._reference_item.setVisible(not self._donor_flicker_phase)

    def _stop_donor_flicker(self) -> None:
        if self._donor_flicker_timer is not None:
            self._donor_flicker_timer.stop()
            self._donor_flicker_timer.deleteLater()
            self._donor_flicker_timer = None

    def _show_donor_difference(self) -> None:
        if self.donor_ghost.image is None or self._committed_reference is None:
            return
        base = self._committed_reference
        positioned, offset = _positioned(self.donor_ghost.image.convert("RGBA"), Transform(**self.donor_ghost.transform))
        overlaid = base.copy()
        overlaid.alpha_composite(positioned, dest=offset)
        diff = ImageChops.difference(base.convert("RGB"), overlaid.convert("RGB"))
        self._set_preview_pixmap(diff.convert("RGBA"))

    # -- C5-G bake Before/After preview (directive #13.3) -------------------
    # Every mode here is read-only: it renders through the exact same core
    # render_subset() apply_bake_plan itself uses for the derived composite,
    # never a document mutation -- analyze/preview never bakes.
    def preview_bake_candidate(self, instance_ids: list, mode: str, wipe_fraction: float = 0.5) -> None:
        if self.document is None or self._committed_reference is None:
            return
        self._stop_flicker()
        before = self._committed_reference
        if mode == "before":
            self._set_preview_pixmap(before)
            return
        after = self._bake_after_image(instance_ids)
        if after is None:
            self._set_preview_pixmap(before)
            return
        if mode == "after":
            self._set_preview_pixmap(after)
        elif mode == "difference":
            diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
            self._set_preview_pixmap(diff.convert("RGBA"))
        elif mode == "flicker":
            self._flicker_frames = (before, after)
            self._flicker_phase = False
            self._flicker_timer = QTimer()
            self._flicker_timer.timeout.connect(self._flicker_tick)
            self._flicker_timer.start(450)
            self._set_preview_pixmap(before)
        elif mode == "wipe":
            self._set_preview_pixmap(self._wipe_image(before, after, wipe_fraction))
        else:
            self._set_preview_pixmap(before)

    def _bake_after_image(self, instance_ids: list) -> Image.Image | None:
        """The full canvas as it would render if ``instance_ids`` were
        collapsed into their single derived composite -- built by literally
        calling render_subset on just that group (the same call
        bake.apply_bake_plan itself makes) and substituting it into the
        current committed reference's layer stack, never touching the
        document. Returns None if any source image can't be resolved."""
        document = self.document
        if document is None or self._committed_reference is None:
            return None
        try:
            canvas = document.composition.get("canvas") or {}
            width = canvas.get("width", self._committed_reference.width)
            height = canvas.get("height", self._committed_reference.height)
            order = document.composition.get("draw_order", [])
            candidate_set = set(instance_ids)
            ordered_candidates = [i for i in order if i in candidate_set] or list(instance_ids)
            sources = {i: self._resolve_image_path(i) for i in ordered_candidates}
            if any(path is None or not path.exists() for path in sources.values()):
                return None
            derived = render_subset(document, sources, ordered_candidates)

            preview = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            inserted = False
            for instance_id in order:
                if instance_id in candidate_set:
                    if not inserted:
                        preview.alpha_composite(derived, dest=(0, 0))
                        inserted = True
                    continue
                inst = document.instances.get(instance_id)
                if inst is None or not inst.visible or inst.opacity <= 0:
                    continue
                path = self._resolve_image_path(instance_id)
                if path is None or not path.exists():
                    continue
                with Image.open(path) as raw:
                    layer = raw.convert("RGBA")
                    if inst.opacity < 1.0:
                        r, g, b, a = layer.split()
                        a = a.point(lambda v, opacity=inst.opacity: round(v * opacity))
                        layer = Image.merge("RGBA", (r, g, b, a))
                    positioned, offset = _positioned(layer, inst.transform)
                    preview.alpha_composite(positioned, dest=offset)
            return preview
        except Exception:
            return None

    @staticmethod
    def _wipe_image(before: Image.Image, after: Image.Image, fraction: float) -> Image.Image:
        fraction = max(0.0, min(1.0, fraction))
        result = before.copy()
        split = round(result.width * fraction)
        if split > 0:
            region = after.crop((0, 0, split, after.height))
            result.paste(region, (0, 0))
        return result
