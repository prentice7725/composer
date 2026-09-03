# SEETHROUGH / COMPOSER / AUTORIG RESPONSIBILITY & VERSION-UP MASTER v0.2

> Status: Architecture Lock Candidate
> Date: 2026-09-03
> Projects: `seethrough-portrait` / `portrait-composer` / `portrait-autorig`

---

# 0. v0.2 핵심 변경

v0.1의 3단 책임 분리는 유지된다.

```text
SOURCE IMAGE
    ↓
seethrough-portrait
    ↓ Portrait Bundle
portrait-composer
    ↓ Assembly Bundle
portrait-autorig
    ↓ Rig Bundle
```

최상위 책임:

- **SeeThrough = WHAT EXISTS**
- **Composer = WHAT TO USE / WHERE TO PLACE / WHAT MAY MOVE**
- **AutoRig = HOW IT MOVES**

v0.2에서는 다음을 추가로 잠근다.

1. `AssetDefinition != LayerInstance`
2. `VariantSet`
3. `SourceBinding / SourceRevision`
4. `Hierarchy / Slot / TransformLink / VariantSet / RigIntent` 분리
5. `draw_order != motion_depth`
6. `Mesh Topology Freeze`
7. explicit evaluation phases
8. contour mesh island policy
9. N-way boundary constraints
10. deterministic physics contract
11. Capability Report
12. `upper_torso_soft`를 **`upper_torso_secondary` 일반 시스템**으로 승격
13. `soft / firm_bounce / springy` response profile 지원
14. Anime2.5DRig + image2live2d의 strand topology를 P1/P2에 흡수

---

# 1. Pipeline Lock

```text
                         SOURCE IMAGE
                              │
                              ▼
┌──────────────────────────────────────────────────────┐
│                 seethrough-portrait                   │
│ semantic source truth                                 │
│ decomposition / hidden completion / ownership         │
│ source fidelity / occlusion measurement                │
└─────────────────────────┬──────────────────────────────┘
                          │ Portrait Bundle
                          ▼
┌──────────────────────────────────────────────────────┐
│                  portrait-composer                    │
│ final visual truth                                    │
│ assets / instances / variants / draw order             │
│ bake / source remap / rig intent                       │
│ authorable secondary-motion regions                    │
└─────────────────────────┬──────────────────────────────┘
                          │ Assembly Bundle
                          ▼
┌──────────────────────────────────────────────────────┐
│                   portrait-autorig                    │
│ rig compilation                                        │
│ mesh / topology / deformers / parameters                │
│ constraints / drivers / deterministic physics           │
│ runtime / capability / QA                               │
└─────────────────────────┬──────────────────────────────┘
                          │ Rig Bundle
```

---

# 2. Source Truth / Assembly Truth / Rig Truth

## Source Truth

SeeThrough가 보장:

> 원본 이미지가 semantic source asset으로 얼마나 정확히 복원되었는가.

## Assembly Truth

Composer가 보장:

> 최종 캐릭터가 실제로 어떻게 보이는가.

필수:

```text
Assembly Bundle/reference.png
```

## Rig Truth

AutoRig가 보장:

> parameter=rest 상태에서 Assembly Reference를 보존하고, 정의된 parameter/driver에 따라 deterministic하게 움직이는가.

---

# 3. Composer Data Model Lock

v0.2부터 `layer` 필드의 모든 의미를 몰아넣지 않는다.

```text
SourceAsset
    ↓
SourceRevision
    ↓
SourceBinding
    ↓
AssetDefinition
    ↓
LayerInstance
```

---

## 3.1 AssetDefinition

재사용 가능한 시각 원자 정의.

```json
{
  "id": "clerk_uniform_f30_03",
  "semantic": "topwear",
  "source": {},
  "planes": [],
  "compatibility": {},
  "provenance": {}
}
```

AssetDefinition은 character placement state를 소유하지 않는다.

---

## 3.2 LayerInstance

특정 캐릭터에서 AssetDefinition을 실제로 사용하는 인스턴스.

```json
{
  "id": "npc031_uniform",
  "asset_ref": "clerk_uniform_f30_03",
  "visible": true,
  "opacity": 1.0,
  "transform": {},
  "slot": "torso",
  "draw_order": 42,
  "transform_link": "uniform_main"
}
```

같은 AssetDefinition을 여러 캐릭터가 공유할 수 있다.

---

# 4. Five Relations Must Stay Separate

다음은 서로 다른 관계들이다.

## Hierarchy

편집/조직 구조.

## Slot / Plane

렌더 위치.

## TransformLink

Composer 편집 중 함께 이동/정렬되는 관계.

## VariantSet

동시에 활성화 가능한 asset state 관계.

## RigIntent

downstream motion/attachment 허용 관계.

이 다섯 개를 하나의 parent/group 개념으로 합치지 않는다.

---

# 5. VariantSet

Expression을 임의 일반 개념으로 확장한다.

```json
{
  "variant_sets": {
    "mouth": {
      "mode": "exclusive",
      "default": "neutral",
      "members": ["mouth_neutral", "mouth_a", "mouth_i", "mouth_u"]
    },
    "hands": {
      "mode": "exclusive",
      "members": ["hands_rest", "hands_document", "hands_chin"]
    }
  }
}
```

허용:

- eye state
- mouth / viseme
- expression asset
- hand pose
- accessory
- outfit variant
- alternate hair
- future angle-specific art

AutoRig는 VariantSet을 visibility/crossfade parameter binding으로 컴파일한다.

---

# 6. Source Revision / Remap

Composer는 upstream source가 갱신될 수 있음을 전제로 한다.

```json
{
  "source_binding": {
    "source_id": "A001_portrait",
    "revision": "sha256:...",
    "source_layer_id": "front_hair",
    "fallback_semantic": "hair_front"
  }
}
```

재수입 상태:

```text
EXACT_MATCH
SEMANTIC_MATCH
AMBIGUOUS
ORPHANED
```

AMBIGUOUS / ORPHANED는 조용히 임의 교체하지 않는다.

manual remap이 가능해야 한다.

---

# 7. Draw Order vs Motion Depth

v0.2 hard invariant:

> **draw_order != motion_depth**

Composer:

```text
draw_order
```

AutoRig:

```text
motion_depth
```

`draw_order`는 무엇이 위에 보이는가.

`motion_depth`는 2.5D turn/parallax에서 얼마나 움직이는가.

서로 다른 값이고 서로를 전제로 하는 정본이 아니다.

---

# 8. Rig Intent v0.2

Composer가 authoring한다.

초기 구조:

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

## 8.1 deformation_scope

```text
baked
rigid
local
independent
secondary
```

---

## 8.2 attachment

```json
{
  "target": "torso",
  "mode": "weld"
}
```

초기 attachment mode:

```text
weld
hinge
free
follow
```

---

# 9. Upper Torso Secondary System

v0.1의 `upper_torso_soft` 특수기능을 일반화한다.

신규 canonical name:

```text
upper_torso_secondary
```

목적:

> torso garment/body surface의 지정된 영역에 secondary lag / bounce / breathing response를 허용한다.

성별/신체형에 대한 추론을 하지 않는다.

---

## 9.1 Composer Responsibility

Composer는 다음만 결정한다.

```text
WHERE
WHAT MAY MOVE
WHAT RESPONSE PROFILE IS INTENDED
```

예:

```json
{
  "id": "upper_torso_secondary",
  "target": "topwear_with_arms",
  "geometry": {
    "kind": "two_lobe"
  },
  "response_profile": "firm_bounce",
  "author_strength": 0.85,
  "locks": {
    "center": 0.12,
    "neckline": 0.18,
    "shoulder": 0.10
  }
}
```

---

## 9.2 Response Profiles

초기 profile:

### `soft`

- 낮은 복원력
- 긴 settle
- 상대적으로 큰 lag
- smooth low-frequency motion

### `firm_bounce`

사용자 표현의 "단단한데 출렁 이는 출렁"에 해당.

- 더 높은 복원력
- 짧은 lag
- 명확한 overshoot
- 빠른 반동
- 작은 진자운동/지속 진동
- displacement clamp는 soft보다 보수적일 수 있음

### `springy`

- 중간 복원력
- 반복 반동이 조금 더 잘 보임
- stylized motion에 적합

이 profile은 Composer의 author intent이며 실제 numeric physics는 AutoRig config가 소유한다.

---

## 9.3 AutoRig Responsibility

AutoRig:

```text
profile
+ region
+ driver inputs
    ↓
UpperTorsoSecondaryDriver
    ↓
output parameter
    ↓
local_soft_field
```

예:

```text
ParamBreath
ParamAngleY
ParamBodyAngleY
ParamBodyAngleX
      ↓
UpperTorsoSecondaryDriver
      ↓
ParamUpperTorsoSecondary
      ↓
local_soft_field
```

---

# 10. Physics Driver Contract

input parameter를 단순 합산하지 않는다.

```json
{
  "inputs": [
    {
      "parameter": "ParamBreath",
      "mode": "translation",
      "weight": 1.0
    },
    {
      "parameter": "ParamAngleY",
      "mode": "angle",
      "weight": -0.25
    },
    {
      "parameter": "ParamBodyAngleX",
      "mode": "acceleration",
      "weight": 0.35
    }
  ]
}
```

초기 input interpretation:

```text
translation
angle
velocity
acceleration
impulse
```

P2 구현 시점까지 schema reservation만 가능.

---

# 11. Mesh Topology Freeze

AutoRig compilation order:

```text
Assembly
  ↓
rig part derivation
  ↓
mesh generation
  ↓
TOPOLOGY FREEZE
  ↓
anchors / weights
  ↓
deformers
  ↓
constraints
  ↓
keyforms
  ↓
physics
```

mesh manifest:

```json
{
  "topology_hash": "sha256:..."
}
```

topology가 바뀌면 다음을 invalidate:

```text
vertex weights
keyforms
boundary constraints
physics region bindings
```

silent remap 금지.

---

# 12. Contour Mesh Island Policy

P1 contour mesh는 disconnected alpha island를 인식해야 한다.

```json
{
  "island_policy": "separate"
}
```

초기 정책:

```text
separate
connect_nearest
largest_only
reject
```

기본:

```text
separate
```

---

# 13. Strand Topology

P1은 다음 계층을 추가한다.

```text
hair_secondary part
      ↓
connected mesh components
      ↓
bottom-contour tip detection
      ↓
wide curtain column split
      ↓
overlapping per-vertex weights
      ↓
StrandSpec[]
```

핵심:

- disconnected lobe는 별도 strand
- connected sheet라도 prominent tip이 여러 개면 lock으로 분할
- 넓은 back/side hair curtain은 overlapping vertical columns
- column weights는 partition-of-unity
- hard seam이 생기지 않게 blend

---

# 14. Strand Physics

P2:

```text
StrandSpec
   ↓
per-strand output parameter
   ↓
StrandSpringDriver
```

material/tuning은 geometry-aware하게 조절 가능.

longer strand:

```text
more lag
more mass
slower settle
```

각 strand의 위상 desync 허용.

---

# 15. Explicit Evaluation Phases

Rig runtime의 호출 순서가 암묵적 규칙이 되면 안 된다.

v0.2:

```text
PHASE 0 base
PHASE 1 primary
PHASE 2 corrective
PHASE 3 secondary
PHASE 4 constraints
PHASE 5 visibility
PHASE 6 render
```

각 deformer/driver/constraint는 phase를 가진다.

---

# 16. Boundary Constraint

P1 canonical:

```text
boundary_stitch
```

한 vertex/sample이 여러 constraint에 참여 가능해야 한다.

금지:

```text
one vertex -> one seam only
```

예:

```json
{
  "id": "neck_collar",
  "kind": "boundary_stitch",
  "a": "neck",
  "b": "topwear",
  "strength": 0.75,
  "samples": []
}
```

---

# 17. Deterministic Physics Contract

P2 physics에는 최소 다음을 명시한다.

```json
{
  "physics": {
    "update_hz": 60,
    "reference_scale": 768,
    "reset_policy": "rest",
    "warmup_seconds": 0.25
  }
}
```

테스트:

```text
RESET
→ fixed ticks
→ capture
```

runtime frame rate 변화가 golden test 결과를 흔들지 않게 한다.

---

# 18. Physics Failure Policy

non-finite 발생 시:

```text
rollback last good state
→ diagnostic
→ offending driver disable/degrade
```

NaN/INF를 renderer로 전파하지 않는다.

---

# 19. Capability Report

QA와 capability를 분리한다.

## QA

> 잘못된 rig인가?

## Capability

> 이 rig는 실제 무엇을 할 수 있는가?

예:

```json
{
  "capabilities": {
    "head_turn": "ready",
    "blink_l": "ready",
    "blink_r": "ready",
    "mouth_open": "degraded",
    "hair_secondary": "ready",
    "upper_torso_secondary": "ready"
  }
}
```

상태:

```text
ready
degraded
disabled
unsupported
```

DEGRADED는 compile failure가 아니다.

---

# 20. Reference Evaluator

장기적으로:

```text
Reference Evaluator
    │
    │ compare
    ▼
Runtime Evaluator
```

를 둔다.

reference evaluator:

- 느려도 됨
- simple CPU implementation
- correctness oracle

runtime evaluator:

- JS/WebGL
- production optimized

P0 `runtime.mjs` 원본부터 이 방향을 유지.

---

# 21. Rejected Heuristic Ledger

전문서 권장:

```text
docs/HEURISTIC_REGISTRY.md
```

기록:

```text
ID
status
purpose
corpus
false positive
false negative
why accepted/rejected
replacement
```

예:

```text
H-014
chest-by-face-ratio
REJECTED
reason: folded-arm / garment / body-proportion false positive
```

실패한 헐리스틱을 반복 구현하지 않는다.

---

# 22. Implementation Order v0.2

```text
STEP 0
SeeThrough P0 Closeout

STEP 1
Composer C0
Asset/Instance
AssemblyDocument
SourceBinding
Identity Assembly

STEP 2
AutoRig Assembly input seam

STEP 3
Composer C1/C2
Multi-source
VariantSet
Hierarchy/Slot/Link
Bake/Profile

STEP 4
AutoRig P0
Manifest/runtime/parameter
draw_order vs motion_depth
topology hash reservation
evaluation phases
Capability Report

STEP 5
Composer C3/C4
Donor/Expression
RigIntent
UpperTorsoSecondary authoring

STEP 6
AutoRig P1
Contour/islands
strand topology
clip
boundary stitch
mesh QA

STEP 7
AutoRig P2
deterministic physics
strand driver
upper torso secondary driver
lip-sync
export
```

---

# 23. Architecture Invariants v0.2

1. SeeThrough는 final design을 결정하지 않는다.
2. Composer는 mesh/deformer 상태를 구현하지 않는다.
3. AutoRig는 donor/source asset을 선택하지 않는다.
4. AutoRig는 final draw order를 발명하지 않는다.
5. `draw_order != motion_depth`.
6. `AssetDefinition != LayerInstance`.
7. `Hierarchy != Slot != TransformLink != VariantSet != RigIntent`.
8. Composer는 Assembly Reference를 반드시 출력한다.
9. AutoRig rest pose는 Assembly Reference를 보존한다.
10. mesh topology 변경 후 dependent rig data를 silent reuse하지 않는다.
11. secondary region은 Composer가 정의한다.
12. secondary response physics는 AutoRig가 계산한다.
13. capability degradation은 가능한 경우 hard failure보다 우선한다.
14. runtime physics는 reset/fixed-step reproducibility를 가져야 한다.
15. cross-repo private imports보다 versioned bundle contract를 우선한다.

---

# 24. Final Lock

> **SeeThrough compiles source truth. Composer authors assembly truth and motion intent. AutoRig compiles deterministic motion without redefining the character.**

Secondary motion:

> **Composer defines WHERE, WHAT, and intended RESPONSE CLASS. AutoRig defines HOW that response is physically evaluated.**

따라서 `soft chest`와 `firm-bounce chest`는 별도 하드코딩 기능이 아니라:

```text
upper_torso_secondary
    + response_profile
```

의 서로 다른 authoring preset으로 취급한다.
