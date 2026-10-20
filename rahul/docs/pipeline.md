# Pipeline contract

A pipeline run preserves the relationship between the source inputs, normalized tasks, static observations, optional probe results, and the report. Its stages are:

```text
config + source files
        │
        ▼
content-hash-locked snapshot
        │
        ▼
explicit adapter → normalized task records
        │
        ├── static checks → findings / gaps / skips
        │
        └── optional bounded paired probes → observations
                                │
                                ▼
                    evidence-linked run report
```

## Configuration

A config is JSON with `schema_version` equal to `rlaudit.pipeline/v1`. Its top-level fields are `name`, `sources`, `adapter`, `checks`, `probes`, `execution`, and optional declared `provenance`.

Each source declares an `id` and a `path` relative to the config directory. `sha256` is optional; if present, it must match the source content. A single-file source digest is SHA-256 of its raw bytes. A directory source digest covers the canonical tree, including relative paths, entry kinds, file sizes and hashes, executable bits, and empty directories; the exact source entries are recorded in `inputs.lock.json`. The runner records the actual digest either way and uses the locked snapshot for replay. A changed source cannot silently replace the bytes in an existing run. Snapshot limits apply before parsing: by default, all sources together are capped at 256 MiB and 10,000 file/directory entries.

An adapter names a source and declares one supported `kind`:

- `local_jsonl` reads fixture/task records. The canonical shape is `{ "task_id": string, "domain": string, "prompt": string, "metadata": object, "files": object }`. Fields in `metadata` remain source evidence; the adapter does not infer missing grader behavior. Optional `files` is a role-to-reference mapping whose values contain `source` (a declared source ID), `path` (relative to that source), and optional `sha256`. For a source that is a single file, the path may be empty, `.`, or the source filename.
- `mimo_code`, `mimo_cyber`, `mimo_webdev`, and `mimo_music` normalize pinned MiMo parquet files. `mimo_general` reads a task-bundle directory tree. Optional `ids` and `limit` bound selection. The Cyber/Webdev/Music adapters use `mimo-{domain}-{row_index:06d}` IDs within the pinned file and retain upstream identifiers in `metadata.source_id`. They preserve the original row, messages, metadata, and source hash. Adapters surface unsupported or missing fields as gaps; malformed required source fields are data errors.

Static check names are explicit (`schema`, `code_static`, `general_contract`, `mimo_contract`). `mimo_contract` checks the published Cyber/Webdev/Music task metadata against narrow source-backed contracts. It does not launch binaries, render music/websites, or call visual judges. Checks may report an observed rule, a missing item, or an unsupported case. A missing criterion, narrow test, or static suspicion is not by itself proof of reward failure.

## Probe contract

A probe is optional and contains an `id`, `task_ids`, an argv `command`, JSON `cases`, a `relation`, an `executor`, and a `scope` (`component` or `environment`). The command is an argument vector, never a shell string. Supported placeholders are `{python}`, `{source:ID}`, and `{workspace}`. Each case has an `id` and JSON `input`.

The driver receives one JSON object on stdin:

```json
{"task": {}, "case": {}, "workspace": "...", "sources": {}}
```

The driver writes one JSON object on stdout with a finite numeric `reward` and optional `details`. Probe relations are declared as:

- `invariant`: rewards are expected to remain equal across paired cases.
- `nondecreasing`: rewards should not decrease as the stated input measure increases.
- `expected`: explicit expected values are listed in `values`.

Every relation includes a human-readable `justification`; `tolerance` is explicit where numeric comparison needs it. These relations encode the narrow hypothesis being tested, not universal correctness. Reports preserve each input, output, relation, and justification so readers can inspect whether the pair was a meaningful test.

The `execution` object declares `partition`, `allow_trusted_process`, `max_source_bytes`, `max_source_files`, `max_tasks`, `max_probe_cases`, `timeout_seconds`, `max_probe_seconds`, `max_output_bytes`, `cpus`, `memory`, Slurm `time_limit`, and exact optional dependency versions. Defaults cap aggregate source input at 256 MiB and 10,000 file/directory entries, normalized tasks at 10,000, and probes at 20 cases, 30 seconds per case, 120 seconds total, and 1 MiB of output. The example requests one CPU, 2 GiB of memory, and a five-minute job. Use tighter limits for smaller audits when possible.

`run` submits one Slurm worker on `amd-tw-verification`; the worker does the full snapshot, normalization, static checks, probes, and report generation. The CLI returns a Slurm job ID immediately. Wait until that job is complete (for example, check with `squeue -j JOB_ID` and `sacct -j JOB_ID`) before calling `verify` or `report`. The `current` backend is rejected outside the required partition, and probes must not be run on a login node. Replay requires the same audit engine and configured dependency versions. `compare` checks the input fingerprint and semantic result digest, so timestamps or other nonsemantic byte differences do not determine whether a run reproduced.

The `trusted_process` executor is denied unless `allow_trusted_process` is explicitly true. It runs with a minimal environment and the recorded engine as its only `PYTHONPATH`, allowing shared module drivers such as `rlaudit.verifiers_adapter`. Inherited host module paths are excluded. It has no network isolation; opt in only for code you have explicitly reviewed, including its imports and any data it parses. The `docker` executor requires an image reference pinned by digest and runs the probe with network access disabled (`--network none`). Neither the config nor the runner proves that arbitrary trusted code makes no external calls. There is no built-in paid model provider or training stage, but custom drivers may contact external services and incur costs; review their code and dependencies accordingly.

## Evidence and interpretation

A report should preserve source hashes, adapter and check versions, candidate IDs, probe cases and outputs, execution limits, and skip/error details. Label source observations, heuristic candidates, and completed probe observations separately. Unsupported check/task combinations are reported as skips with their reason; a skip is not a pass and does not establish a defect. For a new environment, export tasks as JSONL records with `task_id`, `domain`, `prompt`, `metadata`, and `files`, then use `local_jsonl`. A probe driver receives JSON on stdin with `task`, `case`, `workspace`, and `sources`, and writes JSON on stdout with a finite numeric `reward` and optional `details`. Begin with `plan` to validate the config, then submit the bounded run on Slurm. A confirmed mismatch needs an explicit prompt requirement, grader evidence, an observed result, and an alternative-explanation review. Static analysis and synthetic toy examples only validate the pipeline's own plumbing; they do not establish a defect in an upstream task or prevalence across a dataset.

A replay uses the stored content-hash-locked snapshot rather than silently reading updated input files; it rejects a changed audit engine, and configured dependencies must match their pinned versions. Verification checks that run artifacts still match their recorded hashes. Comparison checks input fingerprints and semantic results, ignoring timestamps and other nonsemantic byte differences; it does not decide which run is correct.

The checked-in local example has two normalized task records and two paired probes. The format-reward probe asks whether equivalent numeric strings get equivalent reward. The toy-state probe checks only the driver's explicit expected rewards (0.1 and 0.2) for two actions at position zero; it does not validate broader state dynamics or environment behavior.


## Driver responsibilities and failures

The runner provides a new process and workspace for every case. The driver must reset the actual environment, select and report seeds, and recreate any external state needed by its declared hypothesis. A new workspace alone cannot reset a remote service or simulation. JSON case inputs can carry seeds, initial states, action sequences, or trajectories. Preserve observations and termination information in `details` or case artifacts.

Emit one JSON object on stdout. Return a nonzero exit status for infrastructure or grader failures; do not encode those failures as reward zero. Timeouts, malformed/nonfinite output, output limits, and incomplete relations remain inconclusive. Relations are evaluated separately for each task. Schema checking is mandatory, even if omitted from `checks`. Invalid task/contract records block their probe targets, with skipped targets recorded; independent valid targets continue. Source-wide data errors block all targets. Any data error leaves the report incomplete even when other targets succeed. A manifest with neither checks nor probes is rejected.

Docker images must already be available on the compute node (`--pull never`). The runner never mounts the host Docker socket or home into the container, overrides the entrypoint, disables network access, and applies CPU/memory/PID limits. Artifact byte/count limits bound collection, not all possible filesystem writes; drivers and execution infrastructure still need review. Trusted-process mode is an explicit reviewed-code path, not a sandbox.

## Run bundle and exit status

A completed bundle includes `pipeline.lock.json`, `inputs.lock.json`, copied `inputs/`, the recorded `engine/`, `tasks.jsonl`, adapter/check/probe records, per-case inputs/logs/artifacts, `findings.jsonl`, `report.json`, `state.json`, `artifacts.json`, and `replay.sh`. File hashes detect accidental changes; this is not a signed attestation. Keep all of the bundle for replay. Cases record worker paths; the artifact index uses paths relative to the bundle.

`replay.sh --output NEW_RUN --backend slurm` uses the recorded engine with bytecode writes disabled. The worker creates pinned optional dependencies through `uv`; its actual installed transitive requirements are locked. Source paths and run locations may change, while input/config/code/version fingerprints and semantic results must agree for `compare` to report reproduction. Timestamps and generated binary-container metadata are excluded from semantic comparison.

| Exit code | Meaning |
| --- | --- |
| 0 | Completed operation; an audit may still contain candidate findings. |
| 1 | `compare` found different fingerprints or semantic results. |
| 2 | Invalid configuration, failed integrity check, or execution/setup error. |
| 3 | Audit completed with data errors or inconclusive probes. |

For any MiMo parquet adapter, declare an exact `pyarrow` version in `execution.dependencies`. Declare driver dependencies too; the framework cannot infer arbitrary imports. Docker runtimes are pinned through their image digest. No-op, unsupported, failed, and partially observed checks must never be interpreted as a certificate of correctness.

GPU reservations use `execution.gpus` on Slurm. Reviewed host drivers inherit the scheduler's CUDA/HIP/ROCR device-visibility restrictions; general credentials and environment variables are excluded. GPU hardware execution has not been validated by the CPU examples. Docker GPU passthrough is intentionally unsupported and rejected when GPUs are requested; it needs a site-specific executor before use.
