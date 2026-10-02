# UIUX improvement — full-body-aware phase 1

Implementation follows the approved 2026-10-02 UIUX v0.2 proposal. This is a
bounded first slice, not a replacement of the assembly or rig contracts.

## Delivered

- Visibility, opacity, mask, warp, color and layer-fitting controls are available
  without expanding Advanced. Low-level slot/plane/provenance/transform fields
  remain under Advanced. Inspector content scrolls on smaller screens.
- Prepare Rig enters the simple readiness/export workflow. Legacy torso merge
  remains explicitly available through the advanced compatibility workflow.
- Fit Canvas and Fit Selection are visible in the production toolbar, retaining
  Shift+F / F shortcuts and native aspect ratio.
- Color Match provides source/target canvas picking in a nonmodal dialog.
  Source picks use the selected layer's inverse Qt item transform; target picks
  use native canvas coordinates, independent of viewport zoom/pan. Numeric
  coordinates remain available. Esc cancels a pick and returns to the dialog.
  Preview/cancel do not author operations; Apply is a single undo transaction.
  Source PNG files remain immutable.
- Native slot, plane and opacity editor commits are deferred one event-loop turn
  to avoid destroying the editor inside its own signal callback.

## Validation and boundaries

GUI tests cover a 120×480 single-layer, unclassified image, transformed source
sampling, view-only fitting, canceled previews and one-step apply/undo. No
face donors or guessed segmentation are needed for composition. Existing rig
export validation remains unchanged; arbitrary full-body images are not thereby
promised compatible with the current portrait AutoRig compiler.

Variant/recipe redesign and configured AutoRig launch are subsequent slices.
This phase does not add limb segmentation, skeletal rigging, IK or walk cycles.
