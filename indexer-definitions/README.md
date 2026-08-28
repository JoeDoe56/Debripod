# Cardigann definitions

`official` contains the active upstream Prowlarr Cardigann definitions and is replaced by the advanced definition update workflow. `custom` is never replaced by upstream pulls. A custom YAML definition with the same `id` as an official definition overrides the official definition.

Users may edit and commit files in either directory. Runtime staging and rollback copies are kept outside this tracked tree under `data/indexer-definitions/`.
