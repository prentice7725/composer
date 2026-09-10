# PORTRAIT COMPOSER UI SIMPLIFICATION & EXPRESSION v0.4 DESIGN

**Status:** Design proposal / implementation directive candidate  
**Target:** `prentice7725/composer` v0.4  
**Date:** 2026-09-10  
**Primary theme:** **Canvas-first authoring + progressive disclosure + expression recipe authoring + external-edit escape hatch**

---

## 0. Executive Decision

Portrait Composer should **not** evolve into a small Photoshop, a small Live2D Editor, or a general-purpose rigging package.

Its product role remains:

> **A production workbench that visually assembles layered portraits, performs limited non-destructive cleanup, authors expression ingredients/presets, and hands a deterministic assembly contract to Portrait AutoRig.**

The v0.4 goal is therefore not “more functions”. It is to make the functions already implemented feel like a small, obvious production tool.

The default user path should become:

```text
COMPOSE  →  EXPRESSIONS  →  PREPARE RIG
```

Everything else remains available but moves behind contextual or Advanced surfaces.

The three strongest decisions are:

1. **Position / scale / rotation become canvas-first direct manipulation.** Inspector numeric fields remain precision controls, not the primary workflow.
2. **Composer gets Color Match and Mask Repair, but not a general paint engine.** Serious pixel editing exits to Krita / Photoshop through an external-edit round trip.
3. **Expression authoring is split into articulation and emotion.** Blink and viseme are preserved independently from emotional presets, and Composer exports the semantic recipe while AutoRig owns runtime parameters/deformation.

---

# 1. Existing Contract That Must Not Be Broken

The current repository already has the right architectural boundary:

```text
seethrough-portrait
        │
        ▼
     Composer
  assembly truth
        │
        ▼
  portrait-autorig
     rig truth
```

Composer owns:

- source/layer selection
- layer instances
- hierarchy and draw order
- transform placement
- visibility and VariantSet membership
- non-destructive VisualOps
- donor registration/alignment
- expression preset composition
- RigIntent authoring
- Bake plans and prepared canonical output
- provenance and preflight

AutoRig owns:

- mesh generation
- deformation
- constraints
- physics
- runtime parameter compilation
- blink/lip-sync implementation
- crossfade/runtime visibility execution
- game-facing rig manifest/runtime behavior

This boundary is good and should be preserved in v0.4.

The current code already supports a strong implementation base:

- `ui/canvas/gizmos.py`: direct move/scale/rotate with transient preview and one-drag/one-transaction commit
- `preview.py`: transient preview state separate from document history
- `visual_ops.py`: non-destructive visual operation stack
- `mask_ops.py`: mask erase/restore authoring
- `donor_slots.py`: structured eye/mouth donor slot board
- `expressions.py`: expression presets as thin mappings over VariantSets
- `rig_bundle.py`: AutoRig-facing deterministic export boundary

The v0.4 work should reuse these rather than rebuild them.

---

# 2. Design Principles Learned From Other Tools

## 2.1 Direct manipulation first

Krita's transform workflow puts resize/rotate/move handles directly on the selected visual object; its tool options are used for fine tuning rather than being the main interaction.

Composer should follow the same principle:

> If the user can see the thing they want to move, they should normally move the thing itself.

Numeric values are valuable for exact correction, automation, and debugging, but they should not visually dominate the default Inspector.

Reference: Krita Transform Tool  
https://docs.krita.org/en/reference_manual/tools/transform.html

## 2.2 Progressive disclosure

Professional graphics programs expose enormous feature sets, but Composer has a much narrower production task. It should show only the controls relevant to the current context.

Default surface:

```text
COMPOSE      EXPRESSIONS      PREPARE RIG
```

Advanced surface:

```text
Harvest
Variants
Donor Align diagnostics
Rig Intent detail
Bake Plan detail
VisualOps stack
Provenance
Raw transform values
```

The recent repository change that hides advanced contexts and presents the three-step production workflow is therefore the correct direction and should be completed rather than reversed.

## 2.3 Layer groups and mutually exclusive states

Ren'Py's layered-image system handles combinatorial character sprites by grouping mutually exclusive attributes rather than defining every complete face/body permutation.

Composer's VariantSet model is already conceptually aligned with this.

Reference: Ren'Py Layered Images  
https://www.renpy.org/doc/html/layeredimage.html

The lesson for expressions is:

> Do not author `happy_face_01`, `happy_face_02`, `angry_face_01` as unrelated whole portraits. Author independent semantic families and combine them into presets.

## 2.4 Preserve articulation while applying expression

Live2D's expression guidance explicitly treats eye opening differently from ordinary expression values so that blinking remains natural, and separates expression application arithmetic from basic motion.

References:

- https://docs.live2d.com/en/cubism-editor-manual/setting-and-exporting-facial-expressions/
- https://docs.live2d.com/en/cubism-sdk-manual/expression/

The transferable principle is not “copy Live2D parameters”; it is:

> **Emotional expression must not accidentally destroy blink or speech articulation.**

This becomes a hard design rule for Composer → AutoRig.

## 2.5 External interchange beats reimplementing a paint program

OpenRaster exists specifically for exchange of layered raster images between editors. Its baseline structure is intentionally simple: layer stack metadata plus raster layer files.

References:

- https://www.openraster.org/
- https://www.openraster.org/baseline/layer-stack-spec.html

PSD remains useful because Photoshop is common, but PSD round-trip should be treated as a convenience bridge, not Composer's canonical storage format. `psd-tools` supports creation/manipulation of basic pixel layers and groups, but advanced Photoshop rendering/edit semantics are not fully reproducible outside Photoshop.

Reference:  
https://github.com/psd-tools/psd-tools/blob/main/docs/usage.rst

---

# 3. Proposed Default Window Layout

## 3.1 Primary layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│  COMPOSE                 EXPRESSIONS                 PREPARE RIG     │
├─────────────────┬────────────────────────────────┬───────────────────┤
│                 │                                │                   │
│     LAYERS      │                                │     CONTEXT       │
│                 │                                │                   │
│  👁 hair_front  │                                │  Selected:       │
│  👁 eye         │             CANVAS             │  topwear         │
│  👁 face        │                                │                   │
│  👁 topwear     │     click / drag / resize      │  Opacity         │
│  👁 handwear    │          / rotate              │  Color Match     │
│                 │                                │                   │
│  + Add Layer    │                                │  ▸ Advanced      │
│  − Delete       │                                │                   │
├─────────────────┴────────────────────────────────┴───────────────────┤
│  READY · 14 visible layers · 0 blocking issues · AutoRig preflight  │
└──────────────────────────────────────────────────────────────────────┘
```

The center canvas is the primary work area. The left panel answers **what exists and what is above/below what**. The right panel answers **what can I do to the current selection in this context**.

Diagnostics and provenance should not occupy permanent primary screen space unless they are actively needed.

## 3.2 Default panel priority

### Left: Layers

Always visible in COMPOSE.

Default controls:

- visibility toggle
- thumbnail
- semantic/display name
- warning badge
- drag reorder
- multi-select
- add
- delete
- duplicate only if there is a real production use case

Optional context menu:

- Rename display label
- Replace source
- Fit to canvas/target
- Reset transform
- Move to top/bottom
- Advanced properties

### Center: Canvas

Primary interactions:

- click layer → select
- drag selected layer body → move
- corner handle → uniform scale by default
- modifier + handle → non-uniform scale if explicitly needed
- rotate handle → rotate
- mouse wheel / trackpad → zoom
- space-drag or middle-drag → pan
- drag PNG into canvas → add/import layer
- Delete key → delete selected layer(s)
- arrow keys → nudge
- Shift+arrow → larger nudge
- Esc during gesture → cancel transient edit

### Right: Context panel

The right panel changes with production mode.

In COMPOSE default state, show only:

```text
Layer
  Semantic       topwear
  Visible        ✓
  Opacity        100%

Quick Actions
  [Color Match]
  [Fit]
  [Reset Transform]

▸ Advanced
```

Under Advanced:

- x / y
- scale_x / scale_y
- rotation
- slot
- plane
- VisualOps stack
- mask details
- provenance
- precise alignment controls

This preserves all current power without forcing the user to read it continuously.

---

# 4. Canvas-First Transform Contract

## 4.1 Primary interaction rule

The current `TransformGizmo` architecture should become the official primary transform path.

The existing behavior is already desirable:

```text
mouse down
  → capture committed transform
  → transient proxy preview
  → mouse move updates preview only
  → mouse up commits one transaction
```

This is superior to continuously mutating the AssemblyDocument during drag.

Hard UX rules:

- one drag = one undo step
- Esc = exact no-op to document
- Inspector values update after commit
- no canvas refit/recenter after normal edits
- selection remains stable after commit
- zoom/pan remain stable after document refresh

## 4.2 Scale behavior

Default corner drag should preserve aspect ratio.

Recommended modifiers:

```text
Drag corner           uniform scale
Shift + drag          optional free/non-uniform scale
Alt + drag            scale around center (if opposite-corner scaling is later implemented)
```

If implementation complexity grows, keep only uniform scaling in the default UI. Portrait parts rarely need casual destructive aspect distortion.

## 4.3 Numeric fields are secondary

Numeric transform controls remain because they are important for:

- exact parity corrections
- production troubleshooting
- scripted values
- QA
- copying transforms

But they should be collapsed by default.

---

# 5. Layer Editing Workflow

The core daily workflow should become:

```text
Import / Add
    ↓
Select
    ↓
Drag / Scale / Rotate
    ↓
Reorder
    ↓
Optional Color Match / Mask cleanup
    ↓
Bake only when logical surfaces must be merged
```

## 5.1 Add

Support these as equivalent entry points:

- `+ Add Layer`
- drag PNG/WebP onto Canvas
- drag image onto Layers panel
- paste image if clipboard support is later added

After import:

1. create instance
2. infer semantic when possible
3. center or align against a sensible target
4. immediately select it
5. show transform gizmo

Do not force the user through a modal form for ordinary imports unless semantic inference is ambiguous and consequential.

## 5.2 Delete

Current safe delete behavior should remain transactional and dependency-aware.

UI behavior:

- Delete key deletes selection
- confirmation only when deletion breaks a VariantSet, donor assignment, attachment, Bake Plan, or other authored contract
- ordinary disposable layer deletion should not require confirmation

## 5.3 Reorder

Direct drag in Layers is the primary draw-order operation.

The raw integer `draw_order` value does not need to be prominent in Inspector.

---

# 6. Color Correction: What Composer Should and Should Not Become

AI-generated donor/source mixing makes color mismatch a normal production problem, especially:

- face vs ear
- face vs neck
- face vs hand/arm
- eye-white warmth
- lip donor saturation
- imported sleeve/handwear contamination

Composer should solve the common 80% case, but should not implement a full painting stack.

## 6.1 Keep

- Color VisualOp
- opacity
- masks
- mask erase/restore brush
- source/target color sampling
- simple Color Match

## 6.2 Do not add to Composer core

- general RGB paint brush
- clone stamp
- healing brush
- smudge
- arbitrary selections
- vector paths
- full blend-mode ecosystem
- brush preset engine
- tablet pressure engine
- text tools
- general image filters

Those features create a second graphics application and dilute Composer's production role.

## 6.3 Proposed Color Match UX

```text
COLOR MATCH

Source     [ Pick from selected layer ]  ●
Target     [ Pick from reference layer ] ●

Strength   ─────────●────  75%

[ Preview ]   [ Apply ]

▸ Advanced
  Preserve luminance      ✓
  Chroma strength         80%
  Lightness strength      35%
  Restrict by mask        optional
```

Interaction:

1. user selects a problematic layer
2. clicks Source Pick and samples that layer
3. clicks Target Pick and samples nearby canonical skin/reference color
4. Composer computes a non-destructive correction
5. strength can be adjusted visually
6. Apply adds/updates a Color VisualOp

Implementation recommendation:

- sample a small patch median/trimmed mean rather than a single exact pixel
- separate lightness and chroma correction
- avoid forcing source luminance to target luminance at 100%
- store the operation non-destructively and deterministically
- allow mask restriction

The exact color-space math is an implementation choice. A perceptual space such as Lab/OKLab is preferable for matching if dependency/complexity cost is acceptable; a simpler deterministic HSL/linear-RGB implementation is acceptable for the first MVP.

---

# 7. External Edit Escape Hatch

## 7.1 Decision

Composer should support an external editor round trip instead of growing general paint functionality.

Recommended priority:

```text
1. OpenRaster (.ora) round trip
2. PSD export/reimport convenience path
```

ORA is the cleaner semantic interchange target. PSD is important for Photoshop users but should be treated as a compatibility surface.

## 7.2 Canonical rule

**Assembly Bundle remains source of truth.**

ORA/PSD is never the canonical Composer document.

External tools may edit pixels and optionally layer visibility/order, but Composer-specific contracts remain owned by Composer.

## 7.3 Export structure

Example external layer names:

```text
[PC:inst_00017] hair_front
[PC:inst_00021] eye
[PC:inst_00024] face
[PC:inst_00031] topwear
```

Export alongside:

```text
character_edit.ora
composer-roundtrip.json
```

or:

```text
character_edit.psd
composer-roundtrip.json
```

Sidecar example:

```json
{
  "format": "portrait-composer-roundtrip",
  "version": "0.1",
  "assembly_revision": "...",
  "canvas": {"width": 768, "height": 768},
  "layers": {
    "inst_00017": {
      "semantic": "hair_front",
      "source_hash": "...",
      "transform": {"x": 0, "y": 0, "scale_x": 1, "scale_y": 1, "rotation": 0},
      "draw_index": 12
    }
  }
}
```

## 7.4 Reimport rule

Reimport should primarily accept **pixel changes**, not reconstruct the entire Composer document from the external file.

Status classes:

```text
UNCHANGED
PIXELS_CHANGED
RENAMED_BUT_MATCHED_BY_ID
NEW_EXTERNAL_LAYER
MISSING_EXTERNAL_LAYER
MERGED_OR_ID_LOST
CANVAS_CHANGED
AMBIGUOUS
```

Safe automatic actions:

- matching `[PC:<instance_id>]` pixel layer changed → replace source pixels / create derived source revision
- layer unchanged → no-op
- new layer → offer import as new instance

Require review:

- Composer ID removed
- multiple Composer IDs merged into one layer
- canonical canvas size changed
- external file changed hierarchy in a way that conflicts with VariantSet/RigIntent

Do not import from PSD/ORA:

- AutoRig parameters
- RigIntent
- physics
- VariantSet meaning inferred from group names
- Composer provenance inferred from Photoshop metadata

---

# 8. Expression System: Current State

Current `face_expression_core_v1` is an articulation donor board:

```text
Eyes
  open
  closed

Mouth
  closed
  a
  i
  u
  e
  o
```

This is excellent for:

- blink source
- viseme/lip-sync source

It is **not yet a complete emotional expression system**.

The current `expressions.py` design is nevertheless correct in one important respect: Composer does not own runtime parameters. A preset is a semantic authoring choice over VariantSets; AutoRig compiles that into runtime behavior.

That responsibility boundary should remain.

---

# 9. Expression v2 Concept

## 9.1 Separate articulation from emotion

Expression v2 should explicitly distinguish two domains.

### A. ARTICULATION — continuously/runtime-driven

```text
Blink
  open
  closed

Viseme
  closed
  a
  i
  u
  e
  o
```

Runtime ownership: **AutoRig**

Composer role: provide/approve semantic source assets and alignment.

### B. EMOTION — authored state/preset

Suggested families:

```text
Eye Form
  neutral
  smile
  wide
  narrow
  optional custom...

Brows
  neutral
  happy
  sad
  angry
  worried
  optional custom...

Mouth Form
  neutral
  smile
  frown
  tense
  optional custom...

Overlay
  none
  blush
  tear
  sweat
  shadow
  optional custom...
```

These families are not required to all exist for every character.

## 9.2 Emotional presets combine families

Example:

```text
HAPPY
  eye_form    = smile
  brow_state  = happy
  mouth_form  = smile
  overlay     = none

SAD
  eye_form    = neutral
  brow_state  = sad
  mouth_form  = frown
  overlay     = optional_tear

ANGRY
  eye_form    = narrow
  brow_state  = angry
  mouth_form  = tense
  overlay     = none
```

This prevents the combinatorial explosion of whole-face images.

---

# 10. Critical Rule: Emotion Must Preserve Blink and Lip Sync

A naive design would make:

```text
happy = smile_eye.png + smile_mouth.png
```

and then simply replace the current eye and mouth sprites.

That can destroy:

- blinking
- mouth closure
- viseme switching
- speech animation

Therefore expression presets need an explicit preservation rule.

Recommended semantic rule:

```text
emotion preset modifies emotional channels
articulation channels remain active unless explicitly disabled
```

Default:

```yaml
preserve:
  blink: true
  viseme: true
```

This is a Composer authoring contract, not a deformation instruction.

AutoRig decides how to achieve it.

---

# 11. Two-Stage Expression Implementation Plan

Current AutoRig already reads Composer `variant_sets` and `expression_presets` and compiles them into runtime `sprite_swap`/preset bindings. That means v0.4 should not unnecessarily block on a brand-new runtime system.

## 11.1 Stage A — compatible with current AutoRig

Use existing VariantSets:

```text
eyes_state       open / closed
mouth_viseme     closed / a / i / u / e / o
brow_state       neutral / happy / sad / angry / ...
eye_form         neutral / smile / wide / narrow / ...
mouth_form       neutral / smile / frown / tense / ...
overlay_state     none / blush / tear / sweat / ...
```

Expression presets select emotional VariantSets atomically.

Example:

```json
{
  "happy": {
    "variants": {
      "brow_state": "brow_happy",
      "eye_form": "eye_smile",
      "mouth_form": "mouth_smile",
      "overlay_state": "overlay_none"
    },
    "metadata": {
      "preserve": ["blink", "viseme"]
    }
  }
}
```

Important compatibility rule:

**Do not put `mouth_viseme` selection inside an emotion preset by default.**  
**Do not put `eyes_state=closed` inside an emotion preset by default.**

Those belong to articulation.

For Stage A, if an emotional eye/mouth asset cannot coexist correctly with current AutoRig articulation, Composer should show a preflight warning rather than pretending preservation is guaranteed.

## 11.2 Stage B — explicit AutoRig-facing `expression_intent`

Recommended future Rig Bundle contract:

```yaml
expression_intent:
  profile: face_expression_core_v2

  articulation:
    blink:
      variant_set: eyes_state
      open: inst_eye_open
      closed: inst_eye_closed

    viseme:
      variant_set: mouth_viseme
      closed: inst_mouth_closed
      a: inst_mouth_a
      i: inst_mouth_i
      u: inst_mouth_u
      e: inst_mouth_e
      o: inst_mouth_o

  emotion_channels:
    eye_form:
      mode: authored_state
      variant_set: eye_form
    brow_state:
      mode: authored_state
      variant_set: brow_state
    mouth_form:
      mode: authored_state
      variant_set: mouth_form
    overlay_state:
      mode: overlay
      variant_set: overlay_state

  presets:
    happy:
      eye_form: smile
      brow_state: happy
      mouth_form: smile
      overlay_state: none
      preserve:
        blink: true
        viseme: true
```

Composer says **what state means what**.

AutoRig decides whether each state is implemented through:

- sprite swap
- crossfade
- parameter offset
- multiplicative eye openness
- additive deformation
- overlay visibility
- generated intermediate geometry

That is rig truth and remains downstream.

---

# 12. Fix Required in Current Rig Bundle Export

The current Composer `donor_slots` board is authoring state, but current Rig Bundle export primarily sends donor provenance plus `variant_sets`/`expressions`.

For `face_expression_core_v2`, AutoRig needs an unambiguous semantic mapping such as:

```text
eyes.open       → instance X
eyes.closed     → instance Y
mouth.a         → instance A
mouth.i         → instance I
...
```

Do not require AutoRig to infer these assignments from:

- filename
- semantic display label
- provenance operation
- layer order

Recommended export change:

```json
{
  "expression_intent": { ... },
  "donor_slots": {
    "profile": "face_expression_core_v2",
    "eyes": { ... },
    "mouth": { ... }
  }
}
```

or fold the donor mapping entirely into `expression_intent.articulation`.

Preferred final design: **one canonical `expression_intent` block**, with old `donor_slots` retained only as Composer authoring UI state/migration input.

---

# 13. Expression UI Proposal

## 13.1 Default EXPRESSIONS workspace

```text
┌──────────────────────────────────────────────────────────────────────┐
│  COMPOSE                 EXPRESSIONS                 PREPARE RIG     │
├─────────────────┬────────────────────────────────┬───────────────────┤
│ PRESETS         │                                │ EXPRESSION        │
│                 │                                │                   │
│ Neutral         │                                │ HAPPY             │
│ Happy           │           CHARACTER            │                   │
│ Sad             │            PREVIEW             │ Eyes     Smile   │
│ Angry           │                                │ Brows    Happy   │
│ Shock           │                                │ Mouth    Smile   │
│                 │                                │ Overlay  None    │
│ + Add Preset    │                                │                   │
│                 │                                │ ☑ Blink Test     │
│                 │                                │ ☑ Talk Test      │
└─────────────────┴────────────────────────────────┴───────────────────┘
```

The author should be able to select `Happy` and see the actual face immediately.

## 13.2 Ingredients board

A small secondary panel/button exposes assets:

```text
ARTICULATION

Eyes
  [ Open ✓ ] [ Closed ✓ ]

Mouth
  [ Closed ✓ ] [ A ✓ ] [ I ✓ ] [ U ✓ ] [ E ✓ ] [ O ✓ ]

EMOTION PARTS

Eye Form
  [ Neutral ✓ ] [ Smile + ] [ Wide + ] [ Narrow + ]

Brows
  [ Neutral ✓ ] [ Happy + ] [ Sad + ] [ Angry + ]

Mouth Form
  [ Neutral ✓ ] [ Smile + ] [ Frown + ]

Overlay
  [ None ✓ ] [ Blush + ] [ Tear + ] [ Sweat + ]
```

Each card supports:

- thumbnail
- status badge
- drop image
- Use Selected
- Replace
- Clear

Alignment opens only when necessary.

## 13.3 Donor Align becomes contextual

The existing Donor Align workbench is powerful but too administrative for the default surface.

Default flow:

```text
Drop image into Smile Eye slot
        ↓
Auto-align / existing transform candidate
        ↓
Preview ghost on character
        ↓
If acceptable: Accept
If not: drag ghost directly on canvas
```

Advanced donor diagnostics remain available behind `Details`.

Do not ask normal users to type coordinates.

---

# 14. Expression Preview Requirements

Expression authoring cannot be trusted from static thumbnails alone.

Minimum preview tests:

## Blink Test

While current emotion preset remains active:

```text
open → blink → open
```

Check that emotional eye state does not disappear or produce double eyes.

## Talk Test

Cycle:

```text
closed → a → i → u → e → o → closed
```

while emotion remains active.

Check that mouth emotion does not prevent closure or viseme switching.

## Preset Switch Test

```text
neutral → happy → sad → angry → neutral
```

Detect:

- double drawing
- missing layers
- incorrect draw plane
- alignment drift
- visibility conflicts

These tests can initially be simple deterministic preview loops. They do not require full physics simulation inside Composer.

---

# 15. PREPARE RIG Simplification

Default PREPARE RIG should answer only three questions:

```text
1. Is torso composition ready?
2. Are expression ingredients complete enough?
3. Can AutoRig consume this bundle?
```

Suggested screen:

```text
PREPARE RIG

Torso
  topwear + handwear      READY
  semantic merge          AUTO

Expressions
  Blink                   READY
  Visemes                 6/6
  Emotion presets         4
  Talk/Emotion conflict   NONE

AutoRig Preflight
  ✓ layers resolved
  ✓ no pending remap
  ✓ no unbaked required plan
  ✓ expression intent valid

[ Export Rig Bundle ]

▸ Advanced Bake
▸ Rig Intent
▸ Diagnostics
```

The current full Bake Workbench remains available, but normal production should not require understanding Bake Plans unless the automatic path fails.

---

# 16. What Should Disappear From the Default UI

The following should remain implemented but normally hidden:

- raw `draw_order` integer
- raw instance IDs except diagnostics/detail
- raw source IDs/revisions
- provenance text block
- all transform numbers simultaneously
- Plane unless relevant
- Slot unless relevant
- VisualOps internal IDs
- Bake Plan lifecycle vocabulary
- CAN_BAKE/WARN/BLOCK internals unless there is a warning/block
- drift metrics during ordinary successful import
- all contexts shown simultaneously

This is not removal of capability. It is **information hierarchy**.

---

# 17. Error / Warning Philosophy

Do not make successful production feel like debugging.

Default status language:

```text
READY
NEEDS REVIEW
BLOCKED
```

Detailed internal classifications appear only when expanded.

Example:

```text
Expressions: NEEDS REVIEW
  Mouth smile may replace active viseme layer.
  [Preview Talk Test] [Details]
```

instead of immediately displaying several low-level VariantSet/instance identifiers.

---

# 18. Proposed v0.4 Implementation Order

## Phase U1 — Canvas-first cleanup

- make direct canvas manipulation the documented/default transform workflow
- simplify right panel
- move raw transform fields under Advanced
- preserve current one-drag/one-undo semantics
- add drag-and-drop layer import if absent/incomplete
- make layer reorder/add/delete visually primary

**Exit:** A user can assemble a portrait without typing x/y/scale values.

## Phase U2 — Color Match

- two-point/patch source-target picker
- non-destructive Color VisualOp generation
- strength control
- optional mask restriction
- preview/undo regression

**Exit:** Common skin mismatch is fixable without leaving Composer.

## Phase U3 — External Edit round trip

- ORA export + sidecar IDs
- ORA reimport diff/review
- PSD export/reimport optional second adapter
- preserve Composer semantic contracts

**Exit:** difficult pixel edits can safely leave and return.

## Phase E1 — Expression workspace redesign

- convert donor table into card/slot board
- preset-first UI
- add brow/eye-form/mouth-form/overlay VariantSet families
- preserve v1 eye/mouth articulation slots
- Blink Test / Talk Test preview

**Exit:** user can author Happy/Sad/Angry without manually managing raw VariantSets.

## Phase E2 — Expression handoff contract

- define `expression_intent` schema
- export explicit articulation mapping
- export emotion channel mapping
- validation: emotion preset cannot silently consume blink/viseme channels
- AutoRig consumer update
- cross-repo fixture test

**Exit:** AutoRig receives explicit meaning, not filename inference.

## Phase U4 — PREPARE RIG consolidation

- present one concise readiness checklist
- keep advanced Bake/RigIntent surfaces available
- Export Rig Bundle becomes the obvious final action

**Exit:** ordinary character preparation follows one visible three-step workflow.

---

# 19. Non-Goals for v0.4

Explicitly exclude:

- general paint application
- full PSD fidelity engine
- arbitrary vector graphics
- AutoRig mesh editing inside Composer
- runtime physics tuning inside Composer
- timeline animation authoring
- full Live2D-style parameter editor
- replacing Krita/Photoshop
- replacing AutoRig preview/runtime QA

---

# 20. Acceptance Scenarios

## Scenario A — ordinary layer assembly

A user imports a sleeve/hand layer, drags it into position, scales it with handles, reorders it under topwear, and saves without opening Advanced controls.

PASS if no numeric transform field is required.

## Scenario B — skin color mismatch

A hand donor is too warm relative to the face. User selects the hand, samples hand skin and face skin, applies Color Match at 70%, and masks one non-skin region.

PASS if no external editor is required for this common correction.

## Scenario C — difficult cleanup

A generated hand has a painted artifact requiring clone/heal work. User exports external edit, fixes it in Krita/Photoshop, reimports, and Composer identifies the original layer by stable ID while preserving VariantSet/RigIntent/provenance relationships.

PASS if pixel replacement does not reconstruct/lose assembly semantics.

## Scenario D — Happy expression

User creates `Happy`, chooses smiling eye form + happy brow + smiling mouth form, enables preview, and runs Blink Test and Talk Test.

PASS if blink and viseme remain semantically independent and any incompatible runtime composition is surfaced before export.

## Scenario E — AutoRig handoff

Rig Bundle contains explicit articulation and emotion mappings. AutoRig consumes the mappings without guessing filenames or donor provenance labels.

PASS if a cross-repository fixture can rename source PNG files without changing compiled expression meaning.

---

# 21. Final Product Shape

The intended feeling of Composer v0.4 is:

```text
NOT:
"Here is a technical editor with every property exposed."

BUT:
"Put the pieces where they belong, fix obvious mismatches,
 build the facial states, check readiness, and send it to AutoRig."
```

The user should spend most of their time looking at the character, not at numbers or manifests.

That is the central UX criterion for every v0.4 decision.

---

# 22. Reference Sources

- Krita Transform Tool: https://docs.krita.org/en/reference_manual/tools/transform.html
- Ren'Py Layered Images: https://www.renpy.org/doc/html/layeredimage.html
- Live2D Expression Settings and Export: https://docs.live2d.com/en/cubism-editor-manual/setting-and-exporting-facial-expressions/
- Live2D SDK Expression Motion: https://docs.live2d.com/en/cubism-sdk-manual/expression/
- OpenRaster: https://www.openraster.org/
- OpenRaster Layer Stack: https://www.openraster.org/baseline/layer-stack-spec.html
- psd-tools usage: https://github.com/psd-tools/psd-tools/blob/main/docs/usage.rst

## Repository implementation references

Composer:

- `portrait_composer/ui/canvas/gizmos.py`
- `portrait_composer/ui/docks/inspector_dock.py`
- `portrait_composer/ui/workbenches/donor.py`
- `portrait_composer/donor_slots.py`
- `portrait_composer/expressions.py`
- `portrait_composer/rig_bundle.py`
- `portrait_composer/visual_ops.py`
- `portrait_composer/mask_ops.py`

Portrait AutoRig:

- current README contract: Composer `variant_sets` and `expression_presets` are compiled to runtime sprite-swap/preset behavior
- AutoRig remains responsible for runtime expression binding, deformation, blink/lip-sync execution, and other rig truth

---

## Decision Summary

**LOCK candidates for v0.4:**

- Canvas-first transform
- Three-step workflow: COMPOSE → EXPRESSIONS → PREPARE RIG
- Inspector becomes contextual/progressive, not a property dump
- Color Match + Mask Repair only; no general paint engine
- External Edit round trip, ORA-first / PSD-compatible
- Articulation and Emotion separated
- Blink and Viseme preserved by default across emotion presets
- Expression preset remains semantic authoring; runtime mechanics remain AutoRig-owned
- Rig Bundle must export explicit expression semantic mapping
