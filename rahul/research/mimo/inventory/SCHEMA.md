# MiMo source inventory schema

`summary.json` declares `schema_version: mimo-source-inventory/1` and pins every downloaded source to the dataset revision and SHA-256. The summary also records row counts, Code test-field sizes, General directory reconciliation, image-mapping coverage, duplicate checks, candidate selection, and output hashes.

`rows.jsonl` contains one JSON object per dataset row. Common fields are:

- `domain`, `row_index`, `row_id`: source domain and stable source order, plus the task identifier when present.
- `row`: all original top-level parquet fields, with `extra_info` preserved as a JSON object.
- `instance_json_decoded`: parsed `extra_info.instance_json` object; malformed or non-object data is represented as null or a wrapped decoded value, never executed.
- `fields_present`, `prompt_length_chars`, `prompt_sha256`: source fields and prompt metadata.
- `image_references`, `image_mapping`: image/container values found under image-named fields and exact matching mapping rows.
- Code rows additionally carry `test_patch_present`, `test_patch_size_bytes`, `test_command_present`, and `test_command_size_bytes`.
- General rows additionally carry `environment_references` and `environment_reference_status`.

`candidates/candidate_01.json` through `candidate_06.json` each contain the complete original Code row, its decoded instance, row index, deterministic selection rank, unverified language/framework hints, and selection-bias note. Candidates are selected by ascending nonempty `test_patch` size, with unverified keyword-derived language/framework hints used to prefer diversity and row index used as the tie-break. Hint values are heuristic and may come from generic task prose rather than the project stack.

All inventory and candidate JSON uses UTF-8. The parquet JSON strings are treated only as data. The script refuses to replace any existing output whose bytes differ, and reuses byte-identical outputs.
