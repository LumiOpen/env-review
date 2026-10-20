# Contributing

## Add or review a finding

1. Choose `env/<source-org>/<dataset>/`. Add `dataset.yaml` when introducing a dataset.
2. Search existing findings for the same task and mechanism. Add evidence to the existing finding if it is the same claim.
3. Copy `templates/finding.yaml` to `findings/ER-<8 random hex characters>.yaml`. The filename must match its ID. Generate an ID with `python -c 'import uuid; print("ER-" + uuid.uuid4().hex[:8])'`.
4. Identify the affected task using a stable ID and, where useful, its configuration, split, source path, and row index. Row indices are meaningful only at a pinned revision.
5. Describe the precise mismatch. Include exact source quotes and line numbers or a JSON pointer, plus a witness, calculation, or reproduction procedure.
6. Record assumptions and work not performed. Static code-path proof and an end-to-end reproduction are different forms of evidence.
7. Run the tests and `uv run python -m eval_audit.catalog validate`, then open a pull request.

One finding can cover several task instances when the same mechanism has been
validated for each listed instance. Shared-code similarity alone is insufficient
to list every task as affected. Keep broader extrapolations in a detector run.

## Status meanings

| Status | Meaning |
| --- | --- |
| `candidate` | A specific hypothesis needing more evidence. |
| `confirmed` | Evidence establishes the stated defect within the recorded assumptions and validation scope. May be a static proof; read `validation.method`. |
| `behavior_only` | The behavior is established, but whether it is a defect or materially harmful remains unresolved. |
| `disputed` | Reviewers disagree; record the competing evidence. |
| `rejected` | Counterevidence refutes this particular candidate. Does not label the whole task clean. |
| `fixed` | The defect is confirmed and a fix is evidenced in the discussion, with its revision. Preserve the original affected revision. |

Provenance should identify the actual detector or reviewer. Agent-assisted
adjudication must not be represented as independent human validation. For an
initial contribution, prefer `candidate` unless the proof is complete. Reviewers
should try to refute the finding before accepting it.

Evidence paths refer to the dataset repository at the finding's revision.
Repository-local witness paths belong in `validation.reproducer`. Link externally
in `discussion` when useful. Do not include secrets, full rollout credentials,
or unrelated private material. Avoid committing entire source datasets.

## Record an experiment

Use a new directory under the dataset's `runs/`, with a date and a unique suffix.
Keep immutable raw candidate outputs separate from adjudications. Record:

- Dataset revision and exact inspected task IDs; sampling method and exclusions.
- Detector implementation/version or prompt, model, reasoning settings, and available runtime/cost measurements. Use null for unavailable measurements.
- Candidates, no-finding outcomes, acquisition/parse errors, and uninspectable inputs.
- A separate mapping from candidate IDs to finding IDs, review decisions, and reasons.

Report candidate counts, confirmed claims, affected task instances, unresolved
claims, and rejected claims separately. Do not report corpus defect prevalence
from a selected sample. Unknown cases do not provide false-positive-rate labels.
The initial runs are discovery experiments with different scopes, not a model
leaderboard. A detector derived from a finding has seen that case; it must not be
presented as held-out detection success.

As the reference set grows, freeze evaluation versions and hold out task families
and later datasets. Evaluate only against adjudicated claims, with review of
previously unknown detections instead of automatically counting them as errors.
