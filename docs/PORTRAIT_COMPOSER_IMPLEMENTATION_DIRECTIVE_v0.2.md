# PORTRAIT-COMPOSER IMPLEMENTATION DIRECTIVE v0.2

> Project: `portrait-composer`
> Status: Implementation Directive
> Date: 2026-09-03
> Supersedes: v0.1

---

# 0. Mission

`portrait-composer`는:

> **Semantic Portrait Assembly & Authoring Tool**

이다.

입력:

```text
Portrait Bundle(s)
donor image(s)
modular assets
recipes
```

출력:

```text
Assembly Bundle
```

핵심 책임:

> **WHAT TO USE / WHERE TO PLACE / WHAT MAY MOVE**

Composer는 mesh/deformation/physics solver를 구현하지 않는다.

---

# 1. v0.2 New Locks

v0.1에 추가:

- AssetDefinition / LayerInstance 분리
- stable IDs
- SourceRevision / SourceBinding
- manual remap
- VariantSet
- Multi-Source Harvesting
- Hierarchy / Slot / TransformLink / VariantSet / RigIntent 분리
- transactional AssemblyDocument
- response-profile authoring
- `upper_torso_secondary`
- attachment intent

---

# 2. Repository Layout

```text
portrait-composer/
├─ portrait_composer/
│  ├─ document.py
│  ├─ assets.py
│  ├─ instances.py
│  ├─ sources.py
│  ├─ remap.py
│  ├─ bundle.py
│  ├─ assembly.py
│  ├─ render.py
│  ├─ hierarchy.py
│  ├─ slots.py
│  ├─ links.py
│  ├─ variants.py
│  ├─ bake.py
│  ├─ profiles.py
│  ├─ provenance.py
│  ├─ compatibility.py
│  ├─ donors.py
│  ├─ expressions.py
│  ├─ rig_intent.py
│  ├─ secondary_regions.py
│  ├─ validation.py
│  ├─ history.py
│  ├─ workflow.py
│  ├─ cli.py
│  ├─ gui.py
├─ schemas/
│  ├─ portrait-assembly-v0.2.schema.json
├─ tests/
```

---

# 3. C0 — Document Core First

GUI보다 먼저 `AssemblyDocument`를 구현.

```text
AssemblyDocument
├─ sources
├─ assets
├─ instances
├─ hierarchy
├─ variant_sets
├─ links
├─ rig_intent
├─ composition
├─ provenance
```

---

# 4. Transaction Model

모든 편집 operation:

```text
snapshot
  ↓
apply
  ↓
validate
 ├─┴─┐
OK FAIL
│   │
commit rollback
```

필요:

- undo
- redo
- dirty state
- saved revision token

작업 중 validation fail로 document를 반쯤 변한 상태에 두지 않는다.

---

# 5. AssetDefinition

```json
{
  "id": "uniform_clerk_03",
  "semantic": "topwear",
  "source_binding": "src_uniform03",
  "planes": [
    "sleeve_back",
    "torso",
    "sleeve_front"
  ],
  "compatibility": {}
}
```

재사용 가능.

---

# 6. LayerInstance

```json
{
  "id": "npc031_uniform",
  "asset_ref": "uniform_clerk_03",
  "slot": "torso",
  "draw_order": 40,
  "visible": true,
  "opacity": 1.0,
  "transform": {
    "x": 0,
    "y": 0,
    "scale_x": 1,
    "scale_y": 1,
    "rotation": 0
  },
  "transform_link": "uniform_main"
}
```

Asset를 복사하지 않고 instance로 배치.

---

# 7. Source Model

```text
SourceAsset
    ↓
SourceRevision
    ↓
SourceBinding
```

## SourceRevision

content hash 형식 권장.

```json
{
  "source_id": "A001",
  "revision": "sha256:..."
}
```

---

# 8. Reimport / Remap

재수입 시 layer binding을 다시금으로 확정.

```text
EXACT_MATCH
SEMANTIC_MATCH
AMBIGUOUS
ORPHANED
```

AMBIGUOUS는 user mapping 요구.

CLI/headless에서는:

```text
fail
or
emit unresolved mapping report
```

중 하나.

silent guess 금지.

---

# 9. C0 Identity Composer

Portrait Bundle 하나를 아무 변경 없이 Assembly로 변환.

```text
Portrait Bundle
→ AssetDefinitions
→ LayerInstances
→ source draw order
→ reference render
→ Assembly Bundle
```

Acceptance:

```text
Composer reference
== SeeThrough canonical composite
```

---

# 10. C1 — Multi-Source Harvesting

여러 Portrait Bundle에서 최종 layer를 조합.

예:

```text
run1 → face
run2 → hair_front
run3 → topwear
```

각 선택은 provenance에 기록.

UI는 source badge 표시.

---

# 11. Five Relation Types

## Hierarchy

편집 tree.

## Slot

렌더 plane.

## TransformLink

편집 시 함께 이동.

## VariantSet

배타/선택 state.

## RigIntent

downstream motion 허가.

서로 암묵 동기화하지 않는다.

---

# 12. VariantSet

```json
{
  "id": "mouth",
  "mode": "exclusive",
  "default": "mouth_neutral",
  "members": [
    "mouth_neutral",
    "mouth_a",
    "mouth_i",
    "mouth_u"
  ]
}
```

C1부터 data model이 존재.

C3 donor expression이 member를 추가할 수 있다.

---

# 13. Slots

초기 vocabulary:

```text
body_back
hair_back
torso_back
torso
torso_front
neck
head
face
eye
mouth
accessory_front
hair_front
headwear
```

slot은 semantic이 아니다.

---

# 14. Multi-Plane Asset

하나의 asset:

```text
uniform
├ sleeve_back  → torso_back
├ torso        → torso
├ sleeve_front → torso_front
└ hand_overlay → torso_front
```

한 asset의 plane들이 서로 다른 slot에 존재 가능.

---

# 15. Final Draw Order

Composer 정본.

```json
{
  "composition": {
    "draw_order": [
      "hair_back",
      "body",
      "topwear_with_arms",
      "head",
      "hair_front"
    ]
  }
}
```

AutoRig는 이것을 재해석하지 않는다.

---

# 16. C2 — Bake / Merge

Bake는 source destructive edit가 아니다.

```text
instances
→ derived AssetDefinition
→ derived LayerInstance
```

provenance:

```json
{
  "operation": "alpha_composite",
  "sources": ["topwear", "sleeve", "arm", "handwear"]
}
```

---

# 17. Dry-Run Bake Analysis

실제 merge 이전:

```text
CAN_BAKE
WARN
BLOCK
```

필수.

검사:

- canvas
- incompatible blend
- conflicting VariantSet
- independent RigIntent
- source mismatch
- unresolved attachment

---

# 18. Export Profiles

## PORTRAIT_STATIC

전극 bake.

## PORTRAIT_RIG

기본 NPC.

- head/face/hair expression
- torso low motion
- independent hand motion 없으면 bake 권장
- upper torso secondary 허용

## FULL_MOTION

arm/hand/sleeve 독립 유지.

---

# 19. C3 — Donor / Expression

Composer가 donor를 처리.

```text
donor
→ matte
→ align
→ semantic ROI
→ drift check
→ AssetDefinition
→ VariantSet member
```

AutoRig는 donor original을 모른다.

---

# 20. Expression as VariantSet

특별 asset이 특별 변동 시스템이 아니라 VariantSet을 사용할 수 있다.

예:

```text
eye_state
mouth_viseme
brow_state
```

단 composite expression preset은 여러 VariantSet + parameter hint를 묶을 수 있다.

---

# 21. C4 — RigIntent

```json
{
  "rig_intent": {
    "regions": {},
    "attachments": {},
    "deformation_scopes": {}
  }
}
```

---

# 22. Deformation Scope

초기:

```text
baked
rigid
local
independent
secondary
```

---

# 23. Attachment Intent

```json
{
  "id": "front_hair_attach",
  "child": "hair_front",
  "target": "head",
  "mode": "follow"
}
```

modes:

```text
weld
hinge
free
follow
```

Composer는 attachment intent만 이다.

실제 constraint math는 AutoRig.

---

# 24. Upper Torso Secondary

v0.2 canonical:

```text
upper_torso_secondary
```

이름은 anatomy/gender assumption을 넣지 않는다.

---

# 25. Region Authoring

Composer가 저작:

- target
- geometry
- left/right region
- center lock
- neckline lock
- shoulder lock
- lower falloff
- exclusion
- enabled
- author strength
- response profile

---

# 26. Response Profile

초기:

```text
soft
firm_bounce
springy
```

## soft

느리고 부드러운 secondary lag.

## firm_bounce

높은 복원력 + 짧은 overshoot + 빠른 반동.

“단단한데 출렁 이는” 방향.

## springy

조금 더 stylized하고 반복적인 반동.

Composer는 qualitative intent만 저장.

numeric constants는 AutoRig config.

---

# 27. Upper Torso Region Example

```json
{
  "id": "upper_torso_secondary",
  "target": "topwear_with_arms",
  "geometry": {
    "kind": "two_lobe",
    "left": {
      "center": [0.39, 0.36],
      "radius": [0.24, 0.20]
    },
    "right": {
      "center": [0.61, 0.36],
      "radius": [0.24, 0.20]
    }
  },
  "locks": {
    "center": 0.10,
    "neckline": 0.16,
    "shoulder": 0.08
  },
  "response_profile": "firm_bounce",
  "author_strength": 0.9
}
```

향후 `weight_mask` 지원.

---

# 28. Visual Preflight

Composer가 검사:

- target exists
- geometry inside target
- neckline intrusion
- overlay/hand occlusion
- sparse garment
- bake conflict
- profile visual suitability
- attachment conflict

결과:

```text
READY
DEGRADED
DISABLED
```

AutoRig deformation safety와 구분.

---

# 29. Assembly Bundle v0.2

```text
A001.assembly/
├─ manifest.json
├─ reference.png
├─ layers/
├─ expressions/
├─ masks/
├─ diagnostics/
```

manifest 추가:

```json
{
  "format": "portrait-assembly",
  "version": "0.2",
  "sources": {},
  "assets": {},
  "instances": {},
  "variant_sets": {},
  "composition": {},
  "rig_intent": {},
  "provenance": {}
}
```

---

# 30. Validation

Hard errors:

- missing source
- missing asset
- missing instance ref
- duplicate stable ID
- invalid draw order ref
- invalid VariantSet member
- invalid rig target
- broken attachment target
- unresolved source binding in production export
- missing reference.png

Warnings:

- ambiguous remap candidate
- occlusion risk
- bake recommendation
- secondary region heavily occluded

---

# 31. CLI

```text
portrait-composer identity IN -o OUT
portrait-composer validate OUT
portrait-composer render OUT
portrait-composer apply IN recipe.json -o OUT
portrait-composer remap OLD NEW
```

---

# 32. C0 Exit

- [ ] AssemblyDocument
- [ ] transaction/history
- [ ] AssetDefinition
- [ ] LayerInstance
- [ ] SourceBinding
- [ ] v0.2 schema
- [ ] identity render
- [ ] reference.png
- [ ] provenance
- [ ] CLI
- [ ] regression

---

# 33. C1/C2 Exit

- [ ] multi-source harvest
- [ ] hierarchy
- [ ] slot
- [ ] transform link
- [ ] VariantSet
- [ ] reorder
- [ ] bake dry-run
- [ ] bake provenance
- [ ] profiles
- [ ] source remap

---

# 34. C3/C4 Exit

- [ ] donor
- [ ] expression assets
- [ ] rig intent
- [ ] attachment
- [ ] upper_torso_secondary
- [ ] soft/firm_bounce/springy
- [ ] manual region edit
- [ ] visual preflight

---

# 35. Final Rule

> Composer는 **최종 캐릭터가 무엇으로 구성되고, 무엇이 어디에 있고, 무엇이 움직일 수 있는지** 결정한다.

Secondary motion에서는:

> Composer는 **영역 + 의도된 response class**까지만 결정한다.

실제 출력 상의 실행은 AutoRig가 담당한다.
