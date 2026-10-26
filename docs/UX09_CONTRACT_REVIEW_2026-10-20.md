# UX09 Delivery Contract Review — 2026-10-20

## Pinned inputs

This review covers the producer/consumer files and their versioned bundle schemas; it is not an audit of either repository as a whole.

| Component | Pinned revision |
| --- | --- |
| SeeThrough producer | `a124eef2b5a166fd26d56f2026181bd83e134973` |
| Composer Rig Bundle v0.4 schema | `portrait-composer@d9393d9153522d086c61eb52dbadff02f0aa17e0:portrait-rig-bundle-v0.4`, SHA-256 `9359098a2db74aab5871ef280fc19d0f243a8167165af6277c2d0f97ebc68bd7` |
| Composer Assembly v0.2 schema accepted by AutoRig | `portrait-composer@53e98b43d3856dcfaac30cb787e5755ef9e3c3c1:portrait-assembly-v0.2`, SHA-256 `206d6c6c8cf391b760faf167a46017e791a024e719e5eed06ad13a62c1202449` |
| AutoRig before UX09 | `88fdf699f1af683fe6ee2b4940c0dd2f78745471` |
| AutoRig Rig Bundle v0.4 consumer | `967a3473a5c868ce938bd59e6c488d12b2ed1571` |

## Contract findings and changes

- Composer now emits Rig Bundle v0.4 with visible canonical layers, hidden VariantSet member images, explicit expression intent, source validation/warnings, and an authoritative `instance_draw_order` that includes hidden members. The consumer no longer has to infer order from stale per-instance metadata.
- AutoRig accepts `portrait-rig-bundle` v0.4 through its existing Assembly compiler path. It validates the pinned schema, image paths, variant membership, expression references, canvas/reference dimensions, and source metadata before compiling. Assembly v0.2 remains a separately supported input with its own schema pin.
- `build_expression_intent` provides the consumer with blink/viseme state-to-VariantSet bindings, emotion channels, presets, and blink/viseme preservation flags. Composer keeps raw `donor_slots` in its authoring sidecar; it does not add them to the Rig Bundle or generated AutoRig manifest. Consumer tests confirm the states, hidden images, and preset variants reach AutoRig.
- Image-space left/right candidates remain optional producer metadata. When adopted, each side is emitted as its own canonical layer and becomes a separate AutoRig mesh/tag. “Left” and “right” mean image geometry; they do not establish anatomical identity or a limb chain. AutoRig does not generate full-body joints, IK, or walking/gait from these layers.
- Composer stages a complete export beside the target, validates it, then swaps it into place. A forced staging-validation failure leaves a previously valid output manifest byte-for-byte unchanged.
- The export review status includes producer warnings and the current capability limit. AutoRig preflight/Rest Fidelity report rig compatibility and reference reproduction; they do not certify upstream reconstruction quality.

## Evidence

### Real SeeThrough portrait handoff

Fixture: `20260904_232933_3ad3d237.portrait` from the pinned SeeThrough output set.

- Producer validation: `static_reconstruction=review`, `seams=review`, `local_fidelity=pass`; three warnings were retained in the Rig output source metadata.
- Composer Assembly v0.2 roundtrip → AutoRig: `rig_preflight=READY`, `rest_fidelity=pass`.
- Composer Rig Bundle v0.4 → AutoRig public workflow: `input_kind=rig_bundle`, `rig_preflight=READY`, `rest_fidelity=pass`.
- The fixture has no computed left/right derivatives. It is evidence for portrait transport and render fidelity, not a clean producer-quality pass.

The available alternate producer fixture `20260929_000141_2a352a5a.portrait` reports `static_reconstruction=fail`, `seams=review`, and `local_fidelity=review`. It also compiles to `READY`/Rest Fidelity `pass`, while those producer warnings remain present. This confirms the two status families stay separate.

### Structural expression and full-body limitation fixture

AutoRig's synthetic contract fixture includes open/closed eye variants, mouth expression variants, separate left/right arms, hands, legs, bottomwear, and the explicit `face_expression_core_v2` intent. It verifies that variant images and expression presets compile, source warnings survive, and limb-side layers remain independent mesh tags. The generated manifest has no joints, IK, or gait data. This fixture is structural only and is not used to judge segmentation or generated-image quality.

## Verification run

- Composer: `pytest tests/test_v03_export.py tests/test_v03_acceptance.py tests/test_v04_expression_external.py tests/test_gui_rig_export.py -q` — 13 passed.
- AutoRig: `pytest tests/test_rig_bundle.py tests/test_assembly.py tests/test_variant.py tests/test_workflow.py -q` — 49 passed.
- Real producer → Composer Assembly → AutoRig and producer → Composer Rig Bundle → AutoRig handoffs both completed with the statuses recorded above.
- Qt verification used offscreen tests; no native interactive GUI session was performed.
