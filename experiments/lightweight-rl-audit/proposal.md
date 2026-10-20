# Lightweight RL audit experiment

Author: Cursor agent with Raimondas Luuk. Status: experimental draft; not
validated or adopted by the collaboration.

## Question

Can a small, static, agent-assisted review identify task-level cases where an
RL verifier does not measure the solver-visible specification, cheaply enough
to screen a dataset before expensive rollouts?

## Method

The method combines:

1. deterministic corpus screens for mechanically suspicious artifacts;
2. a bounded random task review;
3. blinded comparison of the solver-visible specification with the verifier;
4. a second pass with the evaluator-only reference revealed;
5. overlapping assignments to measure reviewer consistency.

The review separates an observed mechanism from its possible RL effect. Local
effect labels distinguish apparent absent, noisy, wrong, and shortcut reward
signals. These labels are detector output and do not replace repository finding
statuses or categories.

The operational instructions are in [SKILL.md](SKILL.md), and the agent response
shape is in [review-template.yaml](review-template.yaml).

## Repository boundaries

- This is one independent investigation, not a required review workflow.
- Corpus files are parsed as untrusted data and are not executed on the host.
- Task-specific specification and grading defects are in scope.
- Generic runner/deployment defects remain deferred to `notes/harness/`.
- An unflagged task is unlabeled, not known good.
- Sample outcomes describe inspected tasks and are not corpus prevalence.
- Raw detector outputs remain separate from adjudicated canonical findings.

## Initial trial

The development case is `nebius/SWE-rebench-V2`. The exploratory work predates
this frozen experiment and therefore is not held-out evaluation of the method.
Cases used to design the rubric, including `eslint__eslint-14837`, must be
identified as development cases.

The trial should preserve:

- full source revision and artifact hashes;
- random seed and exact sampled task IDs;
- input packet construction;
- model and reasoning settings;
- raw per-task responses;
- overlap assignments;
- adjudication decisions and promoted finding IDs.

## Evaluation

Report:

- inspected tasks and completed checks;
- candidates, observations, blocked checks, and parse/acquisition errors;
- reviewed, promoted, rejected, and unresolved claims;
- reviewer agreement and reviewer-specific candidate rates;
- cost and elapsed time when available.

Do not report false-positive rate or recall against an incomplete reference set.
New detections require review; unknown detections are not automatic errors.

## Revisit conditions

Revise or retire the method if:

- reviewers cannot reach useful agreement;
- deterministic screens have poor precision after adjudication;
- the task packet omits material specified inputs;
- reference revelation systematically changes judgments;
- runtime validation repeatedly overturns static claims.

Freeze a version only after development cases and counterexamples have been
reviewed. Evaluate generalization on later datasets or held-out task families.
