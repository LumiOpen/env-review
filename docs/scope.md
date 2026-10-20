# Repository purpose and current review scope

The shared output is a versioned reference of task-level claims and their
evidence. Independent investigators can use different detection methods,
contribute discoveries, and later measure what their methods find or miss.
No method or rubric is designated as the collaboration's standard.

Finding schemas and evidence requirements make results mergeable and
reviewable. They do not prescribe how to discover a problem. Candidate,
confirmed, disputed, behavior-only, rejected, and fixed records retain their
distinct meanings; an unflagged task remains unlabeled.

## Dataset review under intended presentation

The current question is: **does the task have a defect when its intended
materials, tools, and grading are presented correctly?**

For this phase, assume the harness:

- Supplies the intended prompt, available task assets, and tool interfaces.
- Starts from the intended task state and handles resets correctly.
- Keeps evaluator-only answers and artifacts outside the solver's view.
- Routes tool calls correctly and delivers the intended answer and state to
  the task's grader, then returns its result correctly.
- Enforces the intended access boundaries without introducing extra leakage.

These are working assumptions for reviewing the dataset, not claims that a
particular deployed harness has been verified. They do not assume reference
answers, test expectations, rubric criteria, or supplied task-specific grading
logic are correct. Those are central subjects of the dataset review.

The boundary follows the cause of a defect, not which repository contains a
file or whether code is shared by several tasks.

| Example | Treatment in this phase |
| --- | --- |
| Prompt contradicts itself or the reference answer | Dataset review |
| Required fact is absent from all intended task materials | Dataset review |
| Task criteria reject a valid answer or reward a task violation | Dataset review |
| An intended task input or tool response exposes an answer key | Dataset review |
| A valid use of an intended task tool yields a grading shortcut | Dataset review |
| Runner accidentally omits an available document or tool | Deferred harness observation |
| Runner mounts grader-only files into the solver's workspace | Deferred harness observation |
| An anti-hack setting is ignored by tool dispatch | Deferred harness observation |
| Online retrieval depends on unknown or broken egress restrictions | Record the dependency; do not label the task broken on that basis |

Answer exposure therefore remains relevant. Investigate what the dataset
deliberately presents to the solver; do not rely on an accidental harness leak.
If online retrieval is part of a task's intended capabilities, a claim about
answer lookup can be investigated under that explicit assumption. Publicly
available grading files alone do not establish a task defect.

Do not silently invent a missing presentation rule or repair a task's flawed
grading criteria. State the relevant assumption in `validation.assumptions`;
leave a claim unresolved when that assumption determines whether it is a defect.
Unknown deployment details need not block unrelated dataset checks.

## Where work belongs

- `env/<org>/<dataset>/findings/`: task claims, evidence, and review decisions;
  these feed the generated index and reference snapshots.
- `env/<org>/<dataset>/runs/`: independent detector outputs, scope, provenance,
  and adjudications. A detector's output is not automatically canonical truth.
- `experiments/<investigation>/`: optional method proposals and notes owned by
  an investigation. Contributors need not follow another experiment's method.
- `notes/harness/`: deferred implementation and deployment observations. These
  are not indexed as broken tasks or counted in dataset detection results.

The [MiMo reference-runtime note](../notes/harness/mimo-reference-runtime.md)
preserves an incidental harness investigation. It is background for a possible
later layer of work, not a requirement to investigate harnesses now. A separate
harness schema or benchmark can be considered when that work becomes active.
