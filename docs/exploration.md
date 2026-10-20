# Reproducing the initial exploration

This records the Codex/Luna investigation's methods and outcomes. These screens
are independent experiments, not the repository's required detection method.
The later [static-review proposal](../experiments/codex-static-review/proposal.md)
is another unvalidated proposal from this investigation.

The initial discovery run is in
[`env/XiaomiMiMo/MiMo-V2.6-RL-oss/runs/2026-10-20-initial`](../env/XiaomiMiMo/MiMo-V2.6-RL-oss/runs/2026-10-20-initial).
It pins revision `e8e81e4945270b6212204bad99de1e598f7fb077` and records 34 task IDs.
The sample contains one random task per domain/language stratum using seed 42,
plus two additional prior reconnaissance tasks. A third reconnaissance task was
already selected by the stratification.

## Static checks

```sh
uv sync --locked
uv run python -m eval_audit.acquire
uv run python -m eval_audit.structural \
  --root data/mimo/general/envs \
  --inventory data/mimo/dataset-api.raw \
  --output reports/structural.json
uv run python -m eval_audit.readonly_screen \
  --root data/mimo/general/envs \
  --output reports/readonly.json
uv run python scripts/check_seed_evidence.py
```

The downloader bootstraps a pinned file inventory. It downloads Python as inert
source text, JSON, instructions, schemas, and initial SQLite databases, excluding
workspace document assets. Defaults are 8 workers, a 25-second request timeout,
at most 3 attempts, and a 20 MB per-file cap. A cache is tied to its inventory
revision. Use a different cache for another revision.

No downloaded Python is imported or executed. The evidence checker uses our
own read-only SQL queries and independent arithmetic. Catalog validation checks
record structure, not whether the claim is true; source quotation verification
is a separate check.

The structural detector checks JSON/Python syntax, rubric IDs and function
references, weights, and uploaded-asset existence. The read-only detector is a
rule derived from a discovered defect family: it recognizes specific audited
verifier/dispatcher hashes, answer-only rubrics, and exposed literal SQL writes.
Its 21 flags are review candidates; only the original finance instance has been
adjudicated. This is not a held-out result.

## Initial outcomes

| Screen | Tasks inspected | Candidates | Current review outcome |
| --- | ---: | ---: | --- |
| Structural v1 | 34 | 2 | 2 established scoring behaviors; impact unresolved |
| Luna shared verifier | 3 | 4 | 1 static defect, 1 behavior, 1 unresolved candidate, 1 rejected |
| Luna task contract | 6 | 0 | No concrete finding in that screen; tasks remain unlabeled |
| Derived read-only rule | 34 | 21 | 1 known instance confirmed, 20 awaiting adjudication |

The growing reference contains **one confirmed static defect, two behavior-only
records, one candidate, and one rejected claim**. These five findings concern four
tasks. Repeated detection of the finance defect does not create another canonical
defect. No full agent rollout or original grader execution was performed.

The model screens used native Codex `gpt-6-luna` subagents with high reasoning
effort. Their raw outputs preserve scope, source hashes, timings, candidate
mechanisms, counterarguments, and per-task outcomes. Tokens and dollar cost were
not exposed and are recorded as null. These small, differently scoped discovery
runs do not support a model ranking, recall estimate, or dataset defect rate.

## Extend the experiments

Keep new runs in their own directories. Preserve exact inputs, detector version
or prompt, selected tasks, raw outputs, and a separate adjudication file. Use
`eval_audit.registry.summarize_run` to count review decisions without converting
unknown tasks into negatives. Add accepted findings as individual YAML files;
retain rejected claims as potential controls. Freeze reference snapshots before
using them for a reported evaluation and hold out related task families or new
datasets.
