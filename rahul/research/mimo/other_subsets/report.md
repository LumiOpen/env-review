# MiMo Cyber, Webdev, and Music audit

All **4,093 remaining rows** completed the bounded pipeline, with no adapter errors or findings from the implemented static contracts. Every frozen-input replay matched its original fingerprint and semantic results. This establishes reproducibility of these checks, not environment correctness.

Dataset revision: `e8e81e4945270b6212204bad99de1e598f7fb077`. Parquet SHA-256 values match the published LFS hashes. Grader snapshots use MiMo-Agent `c3df8469f250b15e7906487a6d52be4c1827a509` and verl `79090e58195e80a9cfe251c95ae7a78a2132b6e2`.

| Subset | Rows checked | Static findings | Replay |
| --- | ---: | ---: | --- |
| Cyber | 1,000 | 0 | Identical |
| Webdev | 2,093 | 0 | Identical |
| Music | 1,000 | 0 | Identical |

## What was checked

- **Cyber:** target-description parseability, prompt/target consistency, identifiers, and image-tag naming.
- **Webdev:** prompt/query consistency, identifiers, category, and image reference presence.
- **Music:** positive integer BPM/voice metadata and positive-fraction meter. This does not check generated compositions or every prompt requirement.
- **All three:** normalized schema, source-domain identity, malformed required fields, and repeated native identifiers. No rows were excluded.

A paired Webdev component probe ran the SHA-pinned `reward_one` arithmetic with synthetic judge inputs. Changing the runtime factor from 0 to 1 produced the expected rewards **0.0 → 0.8333**. It does not validate a rendered website or a visual judge.

## Deferred work and observations

Image-backed Cyber execution, website rendering/visual judging, and ABC/MIDI rendering remain deferred. No model calls, paid judges, training, or GPUs were used.

The pinned Music `compute_score` accepts but does not use task metadata; requested BPM, meter, and voice count are not explicitly enforced there. The Cyber server records the expected source file but compares function, sanitizer, and error type in its match expression. Both are source observations requiring separate semantic/runtime investigation, not demonstrated reward defects. See [source evidence](contracts/evidence.json).

## Pipeline improvements

Added native adapters, source-backed contracts, pinned manifests, and a batch audit/replay runner. Invalid records now skip their affected probe targets while independent valid targets continue; reports retain data errors. Domain checks guard malformed schemas. Wrong-source rows produce errors, repeated native IDs remain visible, and deferred coverage is explicit.

Independent review found and corrected three implementation gaps. **52 tests passed** in Slurm job **55671**; the audits and six run/replay bundles completed in job **55672**, on `amd-tw-verification`.

## Reproduce and inspect

From the repository root, with the cached pinned inputs:

```sh
sbatch scripts/audit_mimo_subsets.slurm --output runs/mimo-other-new
```

Use a fresh output directory. For an existing bundle after repository changes, use its saved `replay.sh`. The [run summary](../../../runs/mimo-other-v1/summary.json), [inventory](inventory.json), [source pins](contracts/source_manifest.json), and [validation record](validation.json) preserve evidence and limits. Each run contains normalized tasks, source snapshots, engine code, dependency versions, reports, and integrity hashes.
