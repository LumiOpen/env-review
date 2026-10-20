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

The current question is: **does the task have a defect when presented in a way
that conforms to its published task and environment contract?**

Correct presentation means implementing that contract faithfully. It does not
mean silently supplying missing restrictions or repairing the task's design.
The completeness and consistency of the contract are themselves in scope.

For this phase, assume the harness:

- Supplies the prompt, available task assets, and tool interfaces as specified.
- Starts from the intended task state and handles resets correctly.
- Keeps materials designated as evaluator-only outside the solver's view;
  does not silently remove answer-bearing material specified as solver input.
- Routes tool calls correctly and delivers the intended answer and state to
  the task's grader, then returns its result correctly.
- Enforces specified access boundaries without introducing extra leakage;
  does not invent an unstated offline mode or other protective restriction.

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
| Task validity depends on no internet, but the published contract does not require that restriction | Dataset specification review; establish the dependency and missing requirement |
| Task and environment specifications give contradictory rules about allowed information sources | Dataset specification review |
| Runner accidentally omits an available document or tool | Deferred harness observation |
| Runner mounts grader-only files into the solver's workspace | Deferred harness observation |
| An anti-hack setting is ignored by tool dispatch | Deferred harness observation |
| Runner permits internet access despite an explicit applicable offline requirement | Deferred harness observation |
| We have not inspected the applicable network specification | Investigation gap; not evidence that the specification is missing |

Answer exposure therefore remains relevant. Investigate what the dataset
specifies as solver-visible, including unintended answers within those inputs;
do not rely on an accidental harness leak. If online retrieval is allowed, or
the task materially depends on a restriction absent from the published
contract, an answer-lookup claim is in scope. Publicly available grading files
alone do not establish a task defect.

## Two distinct failure modes

| Failure mode | Catalog category | Claim |
| --- | --- | --- |
| Answer exposure | `answer_exposure` | A reference answer or solution is reachable through the information surface available under conforming presentation, undermining the task. |
| Environment misspecification | `environment_specification` | The task depends on a capability or access condition that its published environment contract omits or contradicts. |

Answer exposure can exist in a fully specified environment: the declared input
bundle may include a reference solution. Environment misspecification can
exist without any demonstrated exposure: the task may need an offline boundary
or a tool capability that the environment contract never defines. Neither
failure mode requires the other. Both can occur on the same task; distinguish
independently supported claims without counting the same mechanism twice.

### Environment misspecification

"Task-environment specification mismatch" is another description of this
failure mode. The issue can exist even if every line of the harness executes
correctly.

For example, a task may depend on solving from supplied evidence, while an
exact reference answer is available online and the published environment
contract does not specify whether the solver may use the internet. A plausible conforming harness
could then allow answer retrieval. The finding concerns the missing boundary;
it need not claim that the original training deployment actually had internet
access or that a model used it.

Evidence should establish the relevant dependence, not merely the absence of
the words "no internet" in one prompt. An applicable dataset-wide rule,
system prompt, environment specification, or required configuration may already
define the restriction. Conversely, an unavailable private deployment policy
does not supply a missing public requirement. Distinguish an author's stated
goal from our inference about the task's intended capability.

Identify the answer-bearing material or shortcut and explain how it undermines
the task or its grade. Reading documentation, accessing ordinary source data,
or using web research when that is the task's purpose is not automatically
reward hacking. A confirmed specification gap and a demonstrated reward hack
are different claims and can require different evidence.

Use the separate categories above when recording these claims. The general
`specification` category still covers other task ambiguities or contradictions;
`reward_shortcut` covers other ways to gain reward without satisfying the task.
Explain the mechanism and reviewed specification sources in `problem` and
`evidence`, and the relevant conforming configuration in
`validation.assumptions`. Keep untested exploitation in `validation.not_run`;
do not turn an unverified deployment into a fact.

Do not silently invent a missing presentation rule or repair a task's flawed
grading criteria. State the relevant assumption in `validation.assumptions`;
leave exploitation unresolved when it depends on an unverified runtime condition.
An evidenced specification mismatch can still be adjudicated on its own terms.
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
