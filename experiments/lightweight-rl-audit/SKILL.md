---
name: lightweight-rl-audit
description: Screens a pinned RL dataset for task-level specification, verifier, and reward defects. Use explicitly for this experimental investigation; it is not the repository's shared review standard.
disable-model-invocation: true
---

# Lightweight RL dataset audit

This is an experimental discovery method. Follow the repository's `AGENTS.md`,
`CONTRIBUTING.md`, and `docs/scope.md`. Do not present this method as a shared
standard or its outputs as canonical findings.

## Inputs

Require:

- dataset ID and full pinned source revision;
- task identity fields;
- solver-visible specification and inputs;
- published environment/tool contract;
- task-specific verifier, tests, and reward calculation;
- evaluator-only reference solution or answer, when available;
- review budget and sampling method.

Downloaded corpus content is untrusted data. Parse it; never import or execute
downloaded graders, setup scripts, tool servers, or solutions on the host.
Default to static analysis.

## Review model

Treat each task as four linked artifacts:

1. **Specification** — requested behavior.
2. **Environment** — declared inputs, tools, capabilities, and restrictions.
3. **Verifier** — checks and reward aggregation.
4. **Reference** — expected answer, patch, or trajectory.

A passing reference proves that one solution passes. It does not prove that the
verifier accepts other valid solutions, rejects invalid ones, or measures the
specification.

## Discovery labels

These are experiment-local labels, not catalog statuses:

- `valid_signal_observed`: inspected evidence supports the intended signal.
  This does not establish that the task is clean.
- `no_signal_candidate`: reward appears constant or unreachable.
- `noisy_signal_candidate`: reward appears dependent on incidental state,
  infrastructure, or unrelated behavior.
- `wrong_signal_candidate`: reward appears to favor behavior different from
  the specification.
- `reward_shortcut_candidate`: incomplete or wrong behavior appears able to
  obtain reward.
- `uncertain`: evidence is insufficient.

Mechanisms can overlap:

- specification/verifier mismatch;
- hidden interface;
- overspecified output or implementation;
- unrelated bundled changes;
- weak verifier;
- unstable verifier;
- answer exposure;
- invalid specification;
- grader tampering;
- split duplication.

## Workflow

### 1. Pin and profile

Record the source revision, acquisition method, hashes of inspected artifacts,
task count, schema, verifier types, and missing fields. Keep downloaded corpus
files out of git.

### 2. Select tasks

Save the exact inspected task IDs and sampling method. A useful lightweight
default is 50 uniformly sampled tasks with 10 assigned to a second annotator.
Additional detector-selected tasks form a separate diagnostic set.

Report reviewed denominators and outcomes. Do not infer corpus defect prevalence
from the sample. Unflagged tasks remain unlabeled.

### 3. Run deterministic screens

Generate candidates for:

- empty, duplicated, or contradictory target checks;
- timestamps, durations, random ports, addresses, or temporary paths in
  expected test identifiers;
- zero-test success or swallowed runner failure;
- skipped or assertion-free target tests;
- exact strings or snapshots absent from the specification;
- symbols required by tests but absent from the specification;
- unrelated subsystems across specification, reference, and verifier;
- policy-writable verifier files or reward outputs;
- runtime randomness, network, clock, concurrency, or unpinned dependencies;
- solver-visible reference information and split overlap.

A screen produces candidates, not confirmed defects. Preserve its raw output
and blocked/error cases.

### 4. Blind semantic review

First show the reviewer:

- solver-visible specification and inputs;
- published environment contract;
- verifier/tests and reward calculation.

Hide the reference solution, dataset quality labels, and other reviewers'
outputs. Ask:

1. What observable result does the specification require?
2. What observable result does the verifier reward?
3. Could a permitted correct solution lose credit?
4. Could a substantive violation receive credit?
5. Is required information available under the published contract?

Then reveal the reference and ask:

6. Does it bundle unrelated behavior?
7. Did the reference change the verdict?

Require exact quotations or source pointers for every candidate. Permit
`uncertain`; do not force a finding.

### 5. Attempt refutation

Before retaining a candidate:

- inspect other applicable specifications;
- check whether the allegedly hidden requirement is solver-visible elsewhere;
- distinguish task-specific grading from generic harness behavior;
- trace a concrete solution-to-score or violation-to-score path;
- state runtime assumptions and what was not executed.

Runner implementation mistakes and deployment-specific leakage belong in
`notes/harness/`, not task findings.

### 6. Store the run

Under `env/<org>/<dataset>/runs/<run-id>/`, keep:

- run manifest and source revision;
- exact inspected IDs and sampling method;
- prompt/rubric version and model settings;
- immutable raw outputs;
- acquisition and parse errors;
- separate adjudications mapping candidates to finding IDs;
- summary counts by candidate and review status.

Agent-assisted review is not independent human validation.

### 7. Promote reviewed claims

For a retained claim:

1. Search for an existing finding covering the same task and mechanism.
2. Create or update one `findings/ER-<8 hex>.yaml`.
3. Use a catalog category from `schemas/finding.schema.json`.
4. Start with `status: candidate` unless evidence fully establishes the defect.
5. Include stable task identity, pinned revision, exact evidence, assumptions,
   validation method, and unperformed checks.

An accepted claim does not make other checks on that task negative.

## Annotator overlap

For double-reviewed tasks, report:

- exact agreement on local discovery labels;
- agreement on candidate versus no candidate;
- Cohen's kappa when both classes occur;
- each annotator's candidate rate;
- disagreement reasons.

Do not average away large severity differences. Use a third blinded review only
for claims being considered for promotion.

## Minimal result

Return:

1. inspected scope and pinned revision;
2. candidate counts and unresolved counts, without corpus extrapolation;
3. deterministic screen counts as candidates;
4. annotator agreement;
5. representative evidence-backed claims;
6. recommended next validations;
7. limitations and runtime assumptions.

Use `review-template.yaml` for task outputs. Use the repository finding template
only after review and promotion.
