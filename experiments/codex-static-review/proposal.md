# Codex static-review experiment

Author: Codex, from this investigation with Jonathan. Status: experimental
draft; not validated or adopted by the collaboration. This is one detection
method to compare with independent investigations.

## Rubric and agent response

Use the [v0.1 rubric](rubric.md) as the agent review instructions and the
[YAML response template](review-template.yaml) for results. The rubric defines
checks, evidence, counterexamples, intentional versus incidental environment
repair, and the distinction between a candidate and an unreviewed task.

The runner prepares task materials and identifies their roles: solver
instructions, intended inputs and tool interfaces, environment/design
specification, evaluator-only references, and task-specific grading logic.
Missing materials remain explicit. The agent cites source paths and supporting
text. No dataset commit or other provenance bookkeeping is required in the
agent response or as a model-visible review input.

The method uses the [intended-presentation scope](../../docs/scope.md). It
reviews the dataset under its published contract, including missing or
contradictory environment requirements and answer exposure. Harness
implementation bugs remain in the deferred layer.

The [ALE blog comparison](ale-blog-coverage.md) motivates several checks and
records gaps in implemented detection. These examples do not establish recall
or constitute adjudicated ALE findings. The
[MiMo runtime note](../../notes/harness/mimo-reference-runtime.md) is deferred
background; using the rubric does not require extending that harness audit.

## Provenance belongs to the runner

Record task IDs, dataset commits, external source versions/hashes, packet
contents, exact rubric/prompt version, model settings, timing, and usage in the
run manifest. Attach this provenance to the agent response when storing it.
Use null for unavailable measurements. The collector resolves source citations
against the recorded input snapshot when producing canonical finding records.

Canonical findings retain the affected dataset commit. If upstream fixes a
claim, preserve that history and record the fix commit and validation evidence.
Different revisions need distinct applicability checks; do not silently carry a
finding or a clean result forward to a new dataset version.

## Trial and scaling

The initial Codex/Luna exploration did not apply this rubric uniformly. Its
original prompts and outcomes remain in the
[initial run](../../env/XiaomiMiMo/MiMo-V2.6-RL-oss/runs/2026-10-20-initial).
No corpus-wide run of this rubric has been completed.

First exercise the rubric on development cases and close counterexamples:
hidden output formats, incidental versus intentional repair, unspecified
versus explicit offline boundaries, ordering leakage, and apparent bypasses
blocked by tool invariants. Existing findings and the ALE examples can guide
selection after recovering the underlying evidence. Cases used to design the
rubric are not held-out validation.

Then freeze the prompt and a reviewed reference snapshot for a trial. Keep raw
agent responses separate from adjudication. Independently review candidates
and some unflagged tasks. Report known-claim recall, adjudicated outcomes of new
flags, task/check coverage, blocked checks, and cost separately. Match claims by
task, affected revision, and mechanism; deduplicate overlapping checks. New
claims need review before being called false positives. Unflagged tasks remain
unlabeled. Full rollout failure is not required to support a static proof.

For scaling, reuse analysis of identical task grading/tool components by hash,
then check applicability to each task. Give tasks bounded model reviews and
record unattempted or blocked checks. Convert recurring mechanisms into
deterministic screens. Hold out related task families or new datasets for
subsequent generalization tests.
