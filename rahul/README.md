# rlaudit

Stable independent toolkit snapshot; see [SNAPSHOT.md](SNAPSHOT.md) for provenance, included inputs, and parent-repository scope. Run commands below from this `rahul/` directory.

`rlaudit` is a bounded, evidence-focused pipeline for auditing task and reward contracts. It snapshots declared inputs by content hash, normalizes tasks through explicit adapters, runs static checks, and can run optional paired probes on a Slurm compute node. Reports separate observations and candidate concerns from confirmed mismatches; a structural gap or narrow test alone is not a defect claim.

The initial examples use two local synthetic task records. One paired probe checks formatting invariance; another checks two explicit reward values for a toy state/action transition. The latter does not validate broader state dynamics or environment behavior. The examples do not download task bundles or images, contact external judges, or claim that a reward rule is universally correct. There is no built-in paid model provider or training stage. Custom trusted drivers may make network calls, so the framework cannot guarantee that no API calls occur.

## Run the local example

From the repository root:

```sh
PYTHONPATH=src python -m rlaudit plan examples/local/pipeline.json
PYTHONPATH=src python -m rlaudit run examples/local/pipeline.json --output runs/toy --backend slurm
# run prints a Slurm job ID; wait for that job to finish before continuing
squeue -j JOB_ID
PYTHONPATH=src python -m rlaudit verify runs/toy
PYTHONPATH=src python -m rlaudit report runs/toy
```

`plan` validates the config and describes its declared sources, checks, and bounded probes. `run` submits one Slurm worker; that worker performs the complete snapshot, normalization, static checks, optional probes, and report generation, then the CLI immediately returns the job ID. Wait for the job to complete (for example, with `squeue -j JOB_ID` or `sacct -j JOB_ID`) before running `verify` or `report`. The current backend is rejected outside the `amd-tw-verification` partition. Use `replay` to rerun from the locked snapshot, and `compare` to compare semantic results:

```sh
PYTHONPATH=src python -m rlaudit replay runs/toy --output runs/toy-replay --backend slurm
PYTHONPATH=src python -m rlaudit compare runs/toy runs/toy-replay
```

The run/replay backend is Slurm on `amd-tw-verification`; do not execute probes on a login node. Inspect the plan and source limits before submission. Replay requires the same audit engine and configured dependency versions. Comparison checks source/config fingerprints and semantic results; timestamps and other nonsemantic byte differences do not affect the result. See [docs/pipeline.md](docs/pipeline.md) for the configuration and trust model.

## Configuration and limits

Pipeline configs use `schema_version: "rlaudit.pipeline/v1"`. Sources use paths relative to the config file and can pin an expected SHA-256. Defaults cap aggregate source input at 256 MiB and 10,000 file/directory entries, normalized tasks at 10,000, and probes at 20 cases, 30 seconds per case, 120 seconds total, and 1 MiB output. CPU, memory, and job wall time are also bounded in the execution block. A single-file source hash covers its raw bytes. A directory source digest covers its canonical tree, including relative paths, entry kinds, file sizes and hashes, executable bits, and empty directories; source entries are recorded in `inputs.lock.json`. The default policy does not allow `trusted_process`; opt in only for explicitly reviewed code. Trusted processes use a minimal environment but have no network isolation. Docker images must be pinned by digest and probes run with network access disabled (`--network none`). Custom trusted drivers can still contact services, so review their code and dependencies for external calls and costs.

## Bringing another environment

For compatible Verifiers v0 environments, add a JSON environment contract, normalized task records, and probe cases. Reuse `python -m rlaudit.verifiers_adapter`; an environment does not need its own Python driver. Contracts declare the source loader, dataset-row assertions, completion or tool interaction, score component, and optional independent oracle. See [docs/environment-contracts.md](docs/environment-contracts.md) and the [fourth-environment example](examples/verifiers_demo/pipeline.json).

Other interfaces can supply a framework adapter through the existing JSON driver protocol. Export tasks as JSON Lines with `task_id`, `domain`, `prompt`, `metadata`, and `files`, then use `local_jsonl`. Declare all referenced source code and data. Start with `plan`, then submit `run` on Slurm. Unsupported checks report skips; they do not establish correctness. See [docs/pipeline.md](docs/pipeline.md) for the record and driver contracts.

## Run the cached MiMo examples

The MiMo configs use captured local parquet files, task bundles, and pinned grader sources. They require those local sources to exist. The Slurm worker uses `uv` to prepare the exact declared dependency versions on the compute node:

```sh
PYTHONPATH=src python -m rlaudit run examples/mimo_code.json --output runs/mimo-code
PYTHONPATH=src python -m rlaudit run examples/mimo_general.json --output runs/mimo-general
PYTHONPATH=src python -m rlaudit run examples/mimo_cyber.json --output runs/mimo-cyber
PYTHONPATH=src python -m rlaudit run examples/mimo_webdev.json --output runs/mimo-webdev
PYTHONPATH=src python -m rlaudit run examples/mimo_music.json --output runs/mimo-music
```

Code runs source checks over all 2,602 rows. General reproduces one DOCX grading component with paired inputs. Cyber, Webdev, and Music check all 1,000, 2,093, and 1,000 published records, respectively. Their native adapters preserve source rows and identifiers; their contracts check metadata only. Webdev also exercises a pinned reward-arithmetic component with synthetic inputs. These checks do not execute target images, judge rendered websites, or render ABC/MIDI music. None trains a policy. Wait for the job before calling `verify`, `report`, or `compare`.

To audit all three additional subsets and verify an independent frozen-input replay for each:

```sh
sbatch --output=research/mimo/other_subsets/audit-%j.log scripts/audit_mimo_subsets.slurm --output runs/mimo-other
```

The batch runner writes `summary.json` and retains each subset's report and replay. It continues after a failed subset and returns a nonzero status if any requested audit is incomplete. Choose a new output directory for every invocation. The pinned dataset inventory, acquisition script, and grader source manifest are in [research/mimo/other_subsets](research/mimo/other_subsets). Reacquisition and bulk inventory must also run on compute with `pyarrow==24.0.0`.

Every run also stores its engine source and a `replay.sh` helper. If the working repository later changes, use the recorded engine:

```sh
runs/toy/replay.sh --output runs/toy-archived-replay --backend slurm
```

The helper disables Python bytecode writes to preserve the evidence bundle. The locked configuration includes observed installed transitive dependency versions for replay. Use the recorded Python version as well; fingerprints expose runtime differences.

## Run the cached Prime Intellect examples

Three public Hub packages have SHA-verified archives, local source snapshots, and contracts for the shared Verifiers adapter:

- `examples/prime_reverse_text.json`: four real dataset rows; exact reversal, XML framing, and declared similarity-metric checks.
- `examples/prime_countdown.json`: one actual seeded puzzle; legal arithmetic controls and forbidden-operation/intermediate-result probes.
- `examples/prime_wordle.json`: two packaged answer words; direct state/tool replay for solving, guess limits, invalid guesses, and speed rewards.

Use the same pipeline CLI for an individual manifest, or run the collection with verification and frozen-input replay:

```sh
sbatch scripts/audit_prime.slurm --output runs/prime-new
```

The worker uses `verifiers==0.3.0`, `datasets==4.3.0`, and `pyarrow==24.0.0`; these packages use the legacy Verifiers API. Every probe runs on compute. Cases call the actual frozen environment code without inference, external judges, or paid services. These are parser/rubric or state/tool component checks; they do not execute an agent rollout or training. See [research/prime/catalog/README.md](research/prime/catalog/README.md) for package pins and [research/prime/integration/README.md](research/prime/integration/README.md) for contract integration. `scripts/audit_collection.py` can run other prepared manifests under an appropriately pinned compute environment.

## Development checks

The example-data checks use Python's standard `unittest` library:

```sh
sbatch scripts/test_pipeline.slurm
```

The test job runs on `amd-tw-verification`. Keep credentials, private data, generated run outputs, and mutable task bundles out of checked-in examples.

Git tracks the implementation, pinned public inputs, and reviewed research. Full `runs/` bundles and bulk inventory exports stay local; regenerate them with the audit commands above.
