# PORTRAIT COMPOSER IMPLEMENTATION DIRECTIVE v0.3

## Status

```text
Document:
PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.3.md

Target:
Portrait Composer v0.3

Milestone:
C6-A ~ C6-J

Status:
RESEARCH-PATCHED DESIGN LOCK
READY FOR IMPLEMENTATION
```

---

# 0. 문서 목적

본 문서는 Portrait Composer v0.3 구현 방향을 잠그는 정본(implementation directive)이다.

v0.3의 핵심 목표는 Composer를 단순한 레이어 선택/조합 도구에서 다음 두 축을 가진 중앙 authoring tool로 승격하는 것이다.

1. **VISUAL COMPOSE**
   - SeeThrough Portrait Bundle 입력
   - Harvest
   - 레이어 선택/교체/추가/정렬
   - 비파괴 이미지 보정
   - Variant
   - Bake Plan

2. **RIG PREPARATION**
   - Donor
   - Rig Intent
   - Secondary Region
   - Attachment
   - Bake Validation
   - AutoRig Bundle Export

기존 C0~C5 구현은 가능한 한 유지한다.

v0.3에서는 그 위에 다음을 증설한다.

- ordered VisualOps stack
- source replace / re-import / remap UX
- gesture-based transient preview / history compression
- proxy preview / canonical full-resolution render
- Qt-native i18n
- Bake Plan
- COMPOSE / RIG PREP workspace 재편
- AutoRig Rig Bundle export

---

# 1. 선행 조사에서 채택한 원칙

v0.3은 범용 이미지 편집기나 범용 rig editor를 새로 발명하지 않는다.

다음 검증된 패턴을 Portrait Composer 목적에 맞게 최소한으로 채택한다.

```text
Photoshop 계열:
source replacement + edit state preservation

Krita:
non-destructive transparency/transform/filter mask 철학

Blender:
ordered modifier stack + explicit Apply

Live2D Cubism:
source image / imported model 분리
re-import / remap을 정식 workflow로 취급
대형 소스 proxy preview

Spine:
slot / attachment / appearance placeholder 분리
linked deformation reuse 개념

Qt:
native i18n
transient UI state
gesture 단위 command/undo 개념

Pillow:
canonical raster render
color enhancement
affine/perspective/quad/mesh transform
mask/composite
```

원칙:

> **검증된 일반 편집기 기능은 가능한 한 기존 라이브러리/프레임워크를 사용하고, Composer는 portrait-specific workflow와 semantic glue만 구현한다.**

---

# 2. v0.3 핵심 책임 분리

## 2.1 전체 파이프라인

```text
SeeThrough Portrait Bundle(s)
              │
              ▼
╔══════════════════════════════════╗
║  A. VISUAL COMPOSE              ║
║                                  ║
║  Source / Re-import / Remap      ║
║  Harvest                         ║
║  Layer replace / add / remove    ║
║  Transform                       ║
║  VisualOps Stack                 ║
║  Draw order                      ║
║  Variants                        ║
║  Bake Plan                       ║
║                                  ║
║  → "보이는 모습" 완성            ║
╚══════════════════════════════════╝
              │
              ▼
╔══════════════════════════════════╗
║  B. RIG PREPARATION             ║
║                                  ║
║  Donor                           ║
║  Rig Intent                      ║
║  Attachment                      ║
║  Secondary Region                ║
║  Bake Validation                 ║
║                                  ║
║  → "어떻게 움직일지" 완성       ║
╚══════════════════════════════════╝
              │
              ▼
        FINAL BAKE
              │
              ▼
      AutoRig Bundle Export
              │
              ▼
           AutoRig
```

---

## 2.2 Harvest

Harvest는 **완성된 레이어 구성을 만든다.**

담당:

- SeeThrough Portrait Bundle 수집
- semantic별 후보 비교
- source replace
- 레이어 선택
- 레이어 교체
- 레이어 추가/삭제
- 위치/크기/회전
- 비파괴 VisualOps
- draw order 조정
- VariantSet 연계

Harvest는 원본 픽셀을 destructive하게 수정하지 않는다.

---

## 2.3 Bake

Bake는 **선택된 여러 레이어를 실제 하나의 derived raster layer로 굽는 기능**이다.

Bake는 `flatten`과 `semantic_merge` 두 모드를 가진다. 일반 합성은
`flatten`을 사용하고, `topwear_with_arms`처럼 새 semantic surface를 만드는
경우 `semantic_merge`를 사용한다. Semantic merge는
`contact zone → shared join edge → ownership → RGB+alpha edge bleed →
internal line replacement → narrow-band tone/alpha blend` 순서의
boundary-aware merge-repair를 수행한다. Source PNG와 mask는 수정하지
않는다. `seam_policy`는 `cleanup`, `expand_under`, `remove_internal_lines`,
`contact_band_px`, `tone_blend_width`, `alpha_blend_width`,
`ownership_rule`을 저장하며 preview와 final bake가 같은 정책을 사용한다.

담당:

- alpha composite
- derived AssetDefinition 생성
- derived LayerInstance 생성
- provenance 기록
- source instance 비파괴 숨김
- undo/redo 복구
- RigIntent / Variant / Attachment 충돌 검사

Bake는 Export가 아니다.

---

## 2.4 Rig Preparation

Rig Prep은 **완성된 시각 구조에 motion 의미를 부여한다.**

담당:

- donor 지정
- rig intent
- deformation scope
- attachment
- secondary region
- rig 관련 validation
- Bake Plan 검증

---

## 2.5 AutoRig

AutoRig는 Composer가 넘긴 Rig Bundle을 소비해 실제 rig를 생성한다.

Composer는 다음을 하지 않는다.

- mesh/deformer math
- constraint solver
- runtime motion parameter binding
- physics constant solve
- final runtime rig generation

---

# 3. Hard Invariants

v0.3에서 다음은 변경 금지 원칙으로 잠근다.

```text
Harvest ≠ Bake
Bake ≠ Export
RigIntent ≠ AutoRig

Source PNG is immutable.
Visual editing is non-destructive.

Assembly Bundle = Composer 작업 저장물
Rig Bundle      = AutoRig 전달물

i18n = Presentation only
Schema/Core identifiers = canonical English IDs

draw_order != motion_depth
slot != semantic

Preview state != Document state
One gesture = One undo step
Canonical render != Proxy preview
```

추가:

> **UI drag/slider/brush 중간값은 document transaction을 생성하지 않는다.**

---

# 4. SeeThrough Direct Input

Composer는 SeeThrough가 생성한 **Portrait Bundle v1**을 upstream input으로 직접 받는다.

지원 입력:

```text
*.portrait directory
*.zip
```

입력 계약:

```text
format = portrait-bundle
version = 1.x
canonical_stage = production_repaired
canvas.coordinate_system = top-left-y-down
canvas.color_space = srgb
canvas.alpha = straight
```

Harvest는 canonical `layers/`만 사용한다.

```text
raw_layers/
```

는 forensic/debug 전용이며 Harvest 후보로 사용하지 않는다.

---

# 5. Source Replace / Re-import / Remap

v0.3에서는 source 교체를 Harvest의 핵심 workflow로 승격한다.

기존 Source 모델:

```text
SourceAsset
SourceRevision
SourceBinding
```

및 remap 상태:

```text
EXACT_MATCH
SEMANTIC_MATCH
AMBIGUOUS
ORPHANED
```

를 유지하고 GUI까지 정식 노출한다.

---

## 5.1 Replace Source 원칙

source를 교체해도 기본적으로 다음 authoring state는 보존한다.

```text
Transform
Opacity
VisualOps
Slot
DrawOrder
Hierarchy membership
TransformLink
VariantSet membership
Rig-independent authoring metadata
```

예:

```text
topwear from Run A
        ↓
transform / mask / color / warp 작성
        ↓
Replace Source → Run C
        ↓
기존 authoring state 유지
```

새 source의 크기나 shape가 크게 달라 기존 조정이 위험할 경우 자동 삭제하지 않고 review 상태를 표시한다.

예:

```text
SOURCE_CHANGED
FIT_REVIEW_REQUIRED
MASK_REVIEW_REQUIRED
WARP_REVIEW_REQUIRED
```

---

## 5.2 Re-import UX

GUI 예:

```text
SOURCE REMAP

head         ✓ EXACT
hair_front   ✓ EXACT
arm_left     ⚠ SEMANTIC_MATCH
badge        ? AMBIGUOUS
glasses      ✕ ORPHANED
```

지원 액션:

```text
Accept
Remap...
Keep Old Revision
Replace Source
Compare Revisions
```

AMBIGUOUS / ORPHANED는 silent auto replacement 금지.

---

# 6. LayerInstance Transform

기존 LayerInstance Transform은 유지한다.

```json
{
  "x": 0.0,
  "y": 0.0,
  "scale_x": 1.0,
  "scale_y": 1.0,
  "rotation": 0.0
}
```

기존:

- move
- scale X/Y
- rotate
- opacity
- draw order

를 그대로 활용한다.

---

## 6.1 Transform UX 확장

v0.3 추가:

- uniform scale lock
- flip X
- flip Y
- reset transform
- numeric input
- keyboard nudge
- bounding box
- center align
- optional snap

Flip은 구현 모델상 별도 bool 또는 signed scale 중 하나를 정본화한 뒤 일관되게 사용한다.

---

# 7. VisualOps는 Ordered Stack이다

기존 v0.3 초안의 고정 객체:

```text
color
mask
warp
```

구조는 폐기한다.

VisualOps는 **순서가 의미를 가지는 non-destructive ordered stack**으로 정의한다.

예:

```json
{
  "visual_ops": [
    {
      "id": "op_color_001",
      "type": "color",
      "enabled": true,
      "params": {
        "saturation": 0.92,
        "brightness": 1.03,
        "contrast": 1.05
      }
    },
    {
      "id": "op_warp_001",
      "type": "quad_warp",
      "enabled": true,
      "params": {}
    },
    {
      "id": "op_mask_001",
      "type": "mask",
      "enabled": true,
      "params": {
        "path": "masks/topwear__instance__op_mask_001.png"
      }
    }
  ]
}
```

연산은 위에서 아래로 평가한다.

```text
Source
  ↓
VisualOp[0]
  ↓
VisualOp[1]
  ↓
VisualOp[2]
  ↓
Layer Transform
  ↓
Composition
```

정확한 `VisualOps ↔ Layer Transform` 평가 순서는 canonical renderer에서 한 번 잠그고 preview renderer가 그대로 따른다.

---

## 7.1 VisualOp 공통 동작

모든 op는 가능하면 다음을 지원한다.

```text
enable / disable
reorder
reset
duplicate
remove
```

op 순서 변경은 결과를 변경할 수 있으므로 serialization 대상이다.

---

# 8. Color Adjustment

v0.3 최소 지원:

- Saturation / Color
- Brightness
- Contrast

Hue는 Pillow 기본 ImageEnhance의 직접 primitive가 아니므로 다음 중 하나로 구현한다.

```text
A. 명시적인 HSV/HSL 변환 op
B. v0.3.1로 defer
```

v0.3 구현 시 half-working Hue slider를 만들지 않는다.

후속 후보:

- Hue
- Tint
- Temperature
- Levels

Color Adjustment는 source image를 수정하지 않는다.

---

# 9. Non-destructive Mask

v0.3 마스크 기능:

- erase
- restore
- feather
- invert
- reset

파일 구조 예:

```text
layers/
  topwear.png

masks/
  topwear__instance__op_mask_001.png
```

마스크는 원본 PNG와 분리해 저장한다.

Mask op의 brush stroke는 한 번의 gesture로 취급한다.

```text
mouse press
   ↓
stroke preview / mask scratch buffer
   ↓
mouse release
   ↓
one commit
one undo
```

---

# 10. Fit / Warp

## 10.1 v0.3 필수

- Fit Width
- Fit Height
- Fit Bounding Box
- Align Center
- target anchor based fit
- 4-corner / quad warp

## 10.2 v0.3.1 후보

- simple mesh warp
- 3x3 / 4x4 mesh control

다음은 구현하지 않는다.

- liquify
- cage editor
- full raster painting suite
- Photoshop-grade transform stack

Composer는 portrait layer fitting tool이지 범용 이미지 편집기가 아니다.

---

# 11. Canonical Renderer / Preview Renderer

v0.3에서는 renderer 역할을 분리한다.

## 11.1 Canonical Renderer

저장, deterministic reference, Bake, export의 정본.

우선 Pillow 기반으로 유지한다.

Pillow 기본 기능을 우선 사용한다.

```text
ImageEnhance
Image.transform:
  AFFINE
  PERSPECTIVE
  QUAD
  MESH
mask / alpha composite
```

OpenCV는 기본 dependency로 추가하지 않는다.

---

## 11.2 Preview Renderer

GUI interactive preview용.

PySide6/Qt의 Graphics/View/Transform/Painter 계층을 우선 활용한다.

원칙:

> Preview와 canonical render는 같은 serialized parameters를 소비한다.

Preview renderer 자체의 내부 representation은 document schema가 아니다.

---

## 11.3 Preview Conformance

동일한 fixture에 대해:

```text
Qt Preview
≈
Pillow Canonical Render
```

를 검증한다.

pixel-perfect가 현실적으로 불필요한 경우 tolerance 기반 비교를 허용한다.

최종 `reference.png`, Bake, Rig Bundle은 반드시 canonical renderer 결과를 사용한다.

---

# 12. Proxy Preview / Deferred Quality

고비용 transform은 drag 중 매번 full-resolution render하지 않는다.

예:

```text
Interactive drag:
0.25x ~ 0.5x proxy

short idle / mouse release:
full-resolution preview

Save / Bake / Export:
canonical full-resolution render
```

proxy factor와 idle delay는 성능 측정 후 상수/config로 관리한다.

하드코딩 UI magic number로 흩어놓지 않는다.

---

# 13. Gesture / Preview / History Infrastructure

Visual editor를 붙이기 전에 history semantics를 잠근다.

현재 snapshot-based HistoryManager는 유지 가능하지만 commit 빈도를 통제한다.

## 13.1 One Gesture = One Undo

예:

```text
Transform drag
mousePress
→ begin transient gesture

mouseMove
→ preview only

mouseRelease
→ one document transaction
→ one history snapshot
```

Color slider:

```text
sliderPressed
→ begin preview

valueChanged
→ preview only

sliderReleased
→ one commit
```

Mask brush:

```text
one continuous stroke
→ one commit
```

Warp handle drag:

```text
one drag
→ one commit
```

---

## 13.2 Document mutation path

기존 원칙 유지:

```text
Qt Widgets
   ↓
GUI Command Layer
   ↓
Public Core API
   ↓
AssemblyDocument transaction
```

widget가 document field를 직접 수정하지 않는다.

transient preview는 별도 UI/session state 또는 scratch representation에 둔다.

---

# 14. VariantSet = Appearance Placeholder

새로운 Skin 시스템을 별도로 만들지 않는다.

기존 VariantSet을 appearance placeholder 개념으로 강화한다.

예:

```text
VariantSet: topwear

members:
  uniform_blue
  uniform_red
  uniform_black
```

downstream motion authoring은 가능한 한 concrete member가 아니라 logical target을 참조한다.

```text
preferred:
topwear

avoid when unnecessary:
uniform_blue
```

이 원칙은 outfit/hand/mouth/expression 재활용성을 높인다.

---

# 15. Future Rig Reuse Hook

Spine linked-mesh 계열에서 검증된 “같은 deformation structure + 다른 image” 재사용 가능성을 고려한다.

v0.3에서 linked mesh 시스템 자체는 구현하지 않는다.

그러나 Rig Bundle/schema가 미래의 다음 개념을 막지 않도록 한다.

```text
rig_template_ref
shared_deformation_source
deformation_inherit
```

이 필드 이름은 v0.3에서 확정하지 않아도 된다.

핵심은 **schema를 특정 asset 1개 = rig topology 1개로 강제하지 않는 것**이다.

---

# 16. Bake Plan

v0.3의 핵심 신규 개념.

Bake Plan은 실제 raster bake 이전에 **논리적인 merge 구조를 선언**한다.

예:

```json
{
  "plan_id": "torso_main",
  "sources": [
    "topwear__instance",
    "arm_l__instance",
    "arm_r__instance"
  ],
  "result_semantic": "topwear_with_arms",
  "result_slot": "torso",
  "status": "PLANNED"
}
```

상태:

```text
PLANNED
   ↓
RIG_CHECKED
   ↓
CAN_BAKE / WARN / BLOCK
   ↓
BAKED
```

Bake Plan 생성 시 실제 PNG는 만들지 않는다.

---

## 16.1 Bake UI 단계

Bake는 하나의 즉시 실행 버튼으로 뭉개지 않는다.

```text
PLAN
  ↓
PREVIEW
  ↓
VALIDATE
  ↓
APPLY
```

---

## 16.2 Bake Plan API

신규 후보:

```text
create_bake_plan()
update_bake_plan()
remove_bake_plan()

analyze_bake_plan()
apply_bake_plan()
```

기존 bake 안전 로직은 재사용한다.

---

# 17. Bake Safety

다음 조건은 계속 BLOCK 대상이다.

- source instance 2개 미만
- canvas 불일치
- source binding unresolved
- VariantSet 독립 switching 손실
- deformation_scope = independent
- attachment reference 충돌

다음은 WARN 가능:

- transform link dissolve
- multiple source bundle/seed
- RigIntent 미작성
- source replacement 후 review unresolved
- mask/warp review unresolved

absence is not safe 원칙을 유지한다.

---

# 18. topwear_with_arms

Portrait Rig용 logical torso surface는 정식 Bake Plan use case다.

예:

```text
topwear
arm_l
arm_r
handwear_l
handwear_r
        ↓
Bake Plan
        ↓
topwear_with_arms
```

Rig Prep:

```text
topwear_with_arms
deformation_scope = secondary
```

검증 후 Final Bake:

```text
topwear_with_arms.png
```

---

# 19. GUI Workspace Reorganization

기존 GUI Context:

```text
ASSEMBLE
HARVEST
VARIANTS
DONOR
RIG INTENT
BAKE
```

를 사용자 mental model 기준으로 크게 두 workspace로 재편한다.

---

## 19.1 COMPOSE

포함:

- Sources / Revision
- Re-import / Remap
- Harvest
- Layers
- Adjust / VisualOps
- Variants
- Bake Plan

개념:

```text
어떤 그림을 쓸 것인가?
어떻게 보이게 만들 것인가?
어떤 레이어를 하나로 묶을 것인가?
```

---

## 19.2 RIG PREP

포함:

- Donor
- Rig Intent
- Secondary Region
- Attachment
- Bake Validation
- Export

개념:

```text
이 결과물이 어떻게 움직여야 하는가?
AutoRig에 어떤 정보를 넘길 것인가?
```

---

# 20. Harvest UI v0.3

기존 candidate strip 구조는 유지하되 확장한다.

예:

```text
┌ SOURCES ──────────────────────┐
│ Run A   Run B   Run C         │
│                               │
│ head                          │
│ [A] [B] [C]                   │
│                               │
│ topwear                       │
│ [A] [B] [C]                   │
└───────────────────────────────┘

               CANVAS

┌ LAYERS ──────┐       ┌ INSPECTOR ─────┐
│ hair_front   │       │ Transform       │
│ head         │       │ VisualOps       │
│ topwear      │       │  ├ Color        │
│ arms         │       │  ├ Warp         │
└──────────────┘       │  └ Mask         │
                       └─────────────────┘
```

후보 hover는 transient preview.

Apply만 document transaction.

---

# 21. Qt-native i18n

기존 초안의 자체 JSON locale manager 설계는 폐기한다.

PySide6/Qt가 제공하는 translation toolchain을 사용한다.

## 21.1 구조

예:

```text
translations/
  portrait_composer_ko_KR.ts
  portrait_composer_en_US.ts
```

빌드:

```text
pyside6-lupdate
      ↓
.ts

Qt Linguist / translation edit
      ↓
pyside6-lrelease
      ↓
.qm
```

runtime:

```text
QTranslator
QCoreApplication / QApplication.installTranslator()
```

---

## 21.2 언어

v0.3 최소:

- ko-KR
- en-US

후속:

- ja-JP

사용자 설정:

```text
설정
 └ 언어
    ├ 시스템 언어
    ├ 한국어
    ├ English
    └ 日本語 (후속)
```

선택값은 기존 QSettings에 저장한다.

---

## 21.3 Runtime Retranslation

가능하면 재시작 없이 반영한다.

위젯/워크벤치는 Qt translation change에 대응 가능한 형태로 작성한다.

필요하면 각 top-level widget/workbench에 명시적 `retranslateUi()` 또는 동등한 메서드를 둔다.

---

## 21.4 i18n Invariant

사용자에게 보이는 문자열은 번역 가능한 경로를 통한다.

저장 데이터는 번역하지 않는다.

예:

```text
storage:
secondary
torso
topwear
CAN_BAKE

display ko-KR:
보조 변형
몸통
상의
합성 가능
```

---

# 22. Dependency Policy

v0.3 기본 dependency 철학:

```text
Pillow
PySide6
```

를 최대한 활용한다.

OpenCV를 다음 이유만으로 추가하지 않는다.

```text
"warp가 필요해서"
"이미지 처리니까"
"나중에 쓸 수도 있어서"
```

OpenCV 추가 조건:

- Pillow/Qt로 구현이 명백히 불충분
- 필요한 기능이 구체적으로 정의됨
- 성능/품질 benchmark로 이득 확인
- dependency 비용을 정당화

후보 예:

- dense remap
- advanced mesh warp
- 특정 accelerated image processing

---

# 23. Assembly Bundle vs Rig Bundle

두 번들은 목적이 다르다.

## Assembly Bundle

Composer 작업 저장물.

```text
Save
→ Assembly Bundle
```

포함:

- authoring state
- SourceBinding / SourceRevision
- Transform
- VisualOps stack
- VariantSet
- RigIntent
- Bake Plan
- provenance
- UI와 무관한 작업 데이터

---

## Rig Bundle

AutoRig 전달물.

```text
Export for AutoRig
→ Rig Bundle
```

예:

```text
A001.rigbundle/
│
├ manifest.json
├ reference.png
│
├ layers/
│   ├ head.png
│   ├ hair_front.png
│   └ topwear_with_arms.png
│
├ masks/
│
├ rig_intent.json
├ donors.json
├ secondary_regions.json
├ attachments.json
│
└ provenance/
```

authoring-only transient preview state는 Rig Bundle에 들어가지 않는다.

---

# 24. AutoRig Export

v0.3에서는 AutoRig 전달용 export를 정식으로 닫는다.

Export 전 검증:

- unresolved source 없음
- remap AMBIGUOUS / ORPHANED unresolved 없음
- source replacement review 완료
- Bake Plan 상태 확인
- required donor 존재
- required RigIntent 존재
- attachment consistency
- secondary region consistency
- deterministic canonical reference
- canonical layer output 존재

---

# 25. C6 Implementation Phases — Research Patched

## C6-A — Responsibility + Data Model Lock

구현 전 잠금:

- 책임 경계
- VisualOps ordered stack
- Preview != Document
- canonical renderer contract
- source replace preservation rule
- Bake Plan data model
- migration policy

Exit:

- schema proposal 완료
- 기존 C0~C5 호환성 계획 완료

---

## C6-B — Qt-native i18n Foundation

구현:

- QTranslator
- TS/QM
- ko-KR / en-US
- runtime language switch
- QSettings persistence
- 기존 GUI 문자열 migration

Exit:

- main menu / dialog / workbench 번역
- core/schema IDs 불변
- JSON locale manager 없음

---

## C6-C — Gesture / Preview / History Infrastructure

Visual editor보다 먼저 구현한다.

구현:

- begin/update/commit/cancel gesture model
- transient preview
- one gesture = one transaction
- color slider commit compression
- transform drag commit compression
- mask stroke commit compression
- warp handle commit compression
- proxy preview infrastructure

Exit:

- drag 100 update → undo entry 1개
- slider 100 update → undo entry 1개
- cancel gesture → document 변화 0

---

## C6-D — Re-import / Remap UX

구현:

- SourceRevision UI
- EXACT / SEMANTIC / AMBIGUOUS / ORPHANED 표시
- Replace Source
- Preserve Transform / VisualOps
- review-required 상태
- manual remap

Exit:

- source 교체 후 authoring state 보존
- ambiguous silent replace 없음
- old revision 유지 가능

---

## C6-E — Transform + Color Stack

구현:

- uniform scale
- flip
- reset
- numeric edit
- nudge
- align
- Color VisualOp
- stack enable/disable/reorder

Exit:

- non-destructive
- serialized
- undo/redo
- save/reload
- preview/canonical conformance

---

## C6-F — Mask Stack

구현:

- Mask VisualOp
- erase / restore
- feather
- invert / reset
- mask PNG persistence

Exit:

- source PNG hash 불변
- one stroke = one undo
- save/reload identical

---

## C6-G — Fit + Quad Warp

구현:

- Fit Width
- Fit Height
- Fit Bounding Box
- anchor alignment
- Quad Warp VisualOp
- proxy drag preview
- canonical Pillow render

고급 mesh warp는 v0.3.1로 defer 가능.

Exit:

- preview/canonical tolerance test
- one handle drag = one undo

---

## C6-H — Bake Plan + Workspace Reorganization

구현:

- Bake Plan
- PLAN / PREVIEW / VALIDATE / APPLY
- COMPOSE / RIG PREP 2축 workspace
- Variant logical target rule
- existing Donor/RigIntent/Bake workbench 재사용
- `flatten` / `semantic_merge` bake mode
- seam policy serialization and deterministic contact-zone repair
- named semantic merge profile (`topwear_with_arms`)

Exit:

- feature loss 없음
- mental model 2축
- Bake planning 시 raster 생성 없음
- semantic merge의 seam policy save/reload 및 undo/redo 보존

---

## C6-I — Final Bake + AutoRig Export

구현:

- validated Bake
- derived assets
- provenance
- Rig Bundle export
- export validation

Exit:

```text
SeeThrough
→ Source/Harvest
→ Adjust
→ Bake Plan
→ Rig Prep
→ Final Bake
→ Rig Bundle
→ AutoRig
```

end-to-end 1회 완주.

---

## C6-J — Migration / Regression / Performance

검증:

- v0.2 Assembly load
- C0~C5 regression
- save/reload
- undo/redo
- source PNG immutable
- VisualOps order persistence
- source replace preservation
- re-import/remap
- proxy/full render
- i18n switch
- Bake Plan persistence
- Rig Bundle export consistency

성능:

- interactive transform responsiveness
- VisualOps preview latency
- full-resolution canonical render timing
- mask brush latency
- memory usage under long editing sessions

---

# 26. Migration Policy

v0.2 document에 새 필드가 없으면 identity/default로 취급한다.

예:

```text
visual_ops absent
→ []

bake_plans absent
→ {}

source review state absent
→ resolved unless remap detects otherwise

locale
→ UI setting only
→ document에 저장하지 않음
```

v0.2 파일을 열었을 때 destructive migration을 하지 않는다.

필요하면 save 시 v0.3 schema로 승격한다.

---

# 27. Regression Policy

기존 C0~C5는 v0.3에서 삭제하지 않는다.

특히 다음은 유지 필수:

- Portrait Bundle v1 direct input
- raw_layers harvest 금지
- source revision/remap
- hierarchy
- slot
- TransformLink
- VariantSet
- donor
- RigIntent
- secondary region
- Bake CAN_BAKE/WARN/BLOCK
- provenance
- deterministic reference render
- undo/redo
- workspace persistence

---

# 28. v0.3 End-to-End Acceptance Test

최소 통합 테스트:

```text
1. SeeThrough Portrait Bundle A/B/C import
2. head = A
3. topwear = C
4. arms = B
5. topwear transform 조정
6. Color VisualOp 추가
7. Mask VisualOp 추가 및 한 stroke 편집
8. Quad Warp VisualOp 추가
9. VisualOps reorder 후 결과 변화 확인
10. topwear source를 다른 run으로 Replace
11. Transform / VisualOps 보존 확인
12. remap ambiguous fixture 수동 해결
13. Bake Plan 생성
14. topwear + arms → topwear_with_arms
15. RigIntent = secondary
16. donor 지정
17. Bake validation = CAN_BAKE
18. Final Bake
19. Rig Bundle export
20. save Assembly Bundle
21. reload
22. deterministic canonical reference 비교
23. undo/redo 확인
24. 한 drag = undo 1개 확인
25. 한 slider gesture = undo 1개 확인
26. 한 mask stroke = undo 1개 확인
27. ko-KR ↔ en-US runtime switch
28. source PNG hash 불변 확인
29. proxy preview → full canonical render 전환 확인
30. C0~C5 regression PASS
```

모든 항목 통과 시 v0.3 핵심 목표 완료.

---

# 29. 바퀴 재발명 금지 목록

v0.3에서 다음을 새로 만들지 않는다.

```text
자체 번역 파일 포맷 / 번역 GUI
→ Qt Linguist / QTranslator 사용

자체 범용 image warp engine
→ Pillow / Qt 우선

자체 범용 painting engine
→ 필요한 mask brush만 구현

자체 skin system
→ VariantSet 확장

자체 rig deformation engine
→ AutoRig 책임

자체 runtime physics system
→ AutoRig/runtime 책임

매 frame/document snapshot식 slider history
→ transient gesture + one commit

source PNG 직접 수정
→ 금지
```

---

# 30. 외부 선행 사례에서 얻은 설계 체크리스트

## Qt / PySide6

채택:

- QTranslator
- `.ts → .qm`
- pyside6-lupdate
- pyside6-lrelease
- translation tooling 재사용

## Blender

채택:

- ordered non-destructive operation stack
- operation enable/disable
- explicit Apply 개념
- order affects result

## Krita

채택:

- source pixel 보존
- transparency mask
- transform/filter 계층을 비파괴로 취급

## Live2D Cubism

채택:

- source와 imported/model state 분리
- re-import를 정식 workflow로 취급
- wrong mapping에 manual remap 제공
- large source preview quality를 낮출 수 있는 구조

## Spine

채택:

- slot / attachment / appearance 분리
- VariantSet을 appearance placeholder로 활용
- future deformation reuse hook을 막지 않음

## Pillow

채택:

- canonical raster engine 우선 후보
- ImageEnhance
- AFFINE / PERSPECTIVE / QUAD / MESH
- mask/composite

---

# 31. References — Official Documentation

조사 기반 설계 참고자료.

- Qt for Python — Translating Applications  
  https://doc.qt.io/qtforpython-6/tutorials/basictutorial/translations.html

- Qt for Python — QTranslator  
  https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTranslator.html

- Qt for Python — Tools / Linguist / lupdate / lrelease  
  https://doc.qt.io/qtforpython-6/tools/index.html

- Blender Manual — Modifiers Introduction / Modifier Stack  
  https://docs.blender.org/manual/en/latest/modeling/modifiers/introduction.html

- Krita Manual — Transparency Masks  
  https://docs.krita.org/en/reference_manual/layers_and_masks/transparency_masks.html

- Krita Manual — Layers and Masks  
  https://docs.krita.org/en/reference_manual/layers_and_masks.html

- Live2D Cubism — Import PSDs  
  https://docs.live2d.com/en/cubism-editor-manual/psd-import/

- Live2D Cubism — Re-import PSDs  
  https://docs.live2d.com/en/cubism-editor-manual/psd-re-import/

- Live2D Cubism — Source Image and Model Guide Image  
  https://docs.live2d.com/en/cubism-editor-manual/original-picture/

- Spine User Guide — Skins  
  https://us.esotericsoftware.com/spine-skins

- Spine User Guide — Attachments  
  https://us.esotericsoftware.com/spine-attachments

- Spine User Guide — Mesh / Linked Meshes  
  https://us.esotericsoftware.com/spine-meshes

- Pillow — Image module / Image.transform  
  https://pillow.readthedocs.io/en/latest/reference/Image.html

- Pillow — ImageEnhance  
  https://pillow.readthedocs.io/en/latest/reference/ImageEnhance.html

---

# 32. 최종 정의

Portrait Composer v0.3는 다음 역할을 가진다.

> **SeeThrough가 만든 canonical portrait assets를 revision-aware하게 수확하고,  
> 레이어를 교체·보정·조립해 시각적 완성 상태를 비파괴 authoring stack으로 만들고,  
> 필요한 레이어는 Bake Plan과 validation을 거쳐 합성하며,  
> donor와 Rig Intent를 부여해 AutoRig가 실행 가능한 Rig Bundle로 내보내는 중앙 authoring tool.**

핵심 문장:

> **Harvest는 완성된 레이어 구성을 만든다.  
> VisualOps는 원본을 손상시키지 않고 그 구성을 보정한다.  
> Bake는 필요한 레이어만 실제 하나의 이미지로 굽는다.  
> Rig Prep은 그 결과물이 어떻게 움직여야 하는지 기술한다.  
> AutoRig는 그 지시를 실제 리깅으로 실행한다.**

그리고 구현 원칙:

> **바퀴는 만들지 않는다.  
> 검증된 편집기 패턴과 Qt/Pillow 기능을 재사용하고,  
> Composer는 SeeThrough와 AutoRig 사이의 portrait-specific authoring 문제에만 집중한다.**
