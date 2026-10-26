# Composer authoring state

The Assembly Bundle `manifest.json` remains the strict `portrait-assembly`
v0.2 contract. Composer-only editing metadata is stored in the optional,
versioned `composer-authoring-v03.json` sidecar.

`instance_authoring` is keyed by the unchanged layer instance ID. Each entry
may contain a non-empty `display_name` and/or a boolean `locked` value. An
empty map or a missing entry means that the UI displays the instance ID and
the layer is unlocked. Names may repeat. These values are not semantic IDs
and are never copied into render, donor, provenance, or Rig Bundle fields.

Undo and redo include this map as document state. Deleting an instance removes
its entry; replacing a source for the same instance keeps its entry. Existing
Assembly Bundles without the sidecar open with the defaults above.
Locked layers remain selectable and inspectable; unlock them before renaming or
editing layer content.

Assembly v0.2 consumers can ignore the optional sidecar and continue reading
the manifest. Composer releases that do not understand `instance_authoring`
may drop user names and locks if they resave the bundle; layer IDs and
semantic data remain unchanged.
