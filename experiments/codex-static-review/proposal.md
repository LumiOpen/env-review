# Codex static-review experiment proposal

Author: Codex, from this investigation with Jonathan. Status: proposed; not
validated or adopted by the collaboration. This is one possible detection
method to compare with independent investigations. It is not a repository
standard or a required next step for contributors.

The initial Codex/Luna exploration did not apply this checklist uniformly;
its original prompts and outcomes remain in the initial run. No corpus-wide
run of this proposed method has been completed.

The current proposal reviews tasks at pinned dataset revisions under the
[intended-presentation assumption](../../docs/scope.md). It focuses on dataset
defects, with harness bugs deferred. The sections below describe this method's
suggested procedure, not the shared contribution requirements.

## State relevant presentation assumptions

Distinguish the task-solving agent, the grading agent, and our audit agents.
Audit agents can inspect private grading materials as evidence; this does not
make those materials visible to the task-solving agent.

For checks that depend on presentation, record the relevant assumptions and
sources. Distinguish declared behavior, source inference, runtime observation,
and unknown facts. A complete harness audit is not a prerequisite. Useful
context can include:

- Agent-visible prompt and tool schemas, including shell and file tools.
- File and database visibility, mount permissions, process users, and timing:
  setup, rollout, grading, and reset between tasks.
- Network reachability separately for setup, rollout, and grading; distinguish
  local services, allowed external destinations, and arbitrary outbound access.
- Instructions about external information, reference solutions, hidden tests,
  and grading materials. Record `unspecified` when the inspected instructions
  say nothing; this is not evidence of either permission or technical blocking.
- Intended restrictions: tool allowlists, file isolation, and cleanup. Assume
  the harness enforces published requirements for the dataset review, but do
  not supply unstated restrictions. Material omissions or contradictions in
  the contract are dataset issues; implementation failures belong in deferred
  harness notes.
- Grader inputs, execution identity, feedback exposed during rollout, and
  opportunities for repeated submissions or state reuse.
- Public availability of task solutions or grading artifacts at the time of
  the run. A release published after training cannot establish a training leak.

The [deferred MiMo runtime note](../../notes/harness/mimo-reference-runtime.md)
provides background. This method does not require extending that investigation.

## Criteria

| ID | Criterion | Required investigation |
| --- | --- | --- |
| inputs | Required information | Can the solver obtain necessary assets and facts through the intended interface? Distinguish uncached assets from absent source assets. |
| specification | Coherent task | Are essential task requirements consistent and sufficiently determined? Identify consequential ambiguity, not stylistic preferences. |
| environment_specification | Environment contract | Does the task depend on a capability or access restriction that the published environment contract omits or contradicts? No answer leak is required for this check. |
| false_negative | Valid behavior rejected | Does a permitted answer, equivalent representation, or allowed sequence fail an actual grading condition? |
| false_positive | Invalid behavior rewarded | Can a substantive obligation or prohibition be violated without affecting the relevant grade? Include state and trajectory requirements. |
| reference | Correct references | Reconcile authoritative data, calculations, identifiers, dates, and expected values. |
| feasibility | Reachable result | Can exposed tools transform initial state into the required result? Check tool-enforced invariants and alternative paths. |
| verifier | Task grading logic | Inspect the supplied task checks and evidence requirements, assuming correct delivery by the runner. Defer generic runner failures. |
| reward | Meaningful scoring | Explain weights, defaults, gates, aggregation, and no-op behavior. An unusual reward offset is not automatically a defect. |
| answer_exposure | Answers in intended inputs | Do intended task materials or tool responses reveal reference answers or solutions that undermine the task? A complete environment specification does not rule out exposure. Defer accidental harness leaks. |
| grader_tampering | Grading process influence | Can intended task inputs or permitted tool actions influence grading without satisfying the task, while evaluator-only files remain protected? |

## Answer exposure and reward hacking

For `answer_exposure`, examine:

- Answer keys, reference solutions, hidden tests, private rubric details, and
  label-bearing fields accidentally included in prompts or tool responses.
- Intended workspace files, notebooks, task-provided logs and history, or other
  deliberately visible materials that contain answers.
- Task tool APIs whose declared responses expose answer-bearing columns or
  files. Generic isolation and dispatch failures are outside this pass.
- Online lookup of public benchmark answers, upstream fixes, solved versions,
  or task-specific discussions when external retrieval is allowed, or when the
  task depends on a restriction absent from the published contract. Unknown
  deployed egress does not resolve the specification question or prove a hack.
- Feedback that lets the solver extract hidden answers or optimize against a
  supposedly held-out test through repeated submissions.

For `grader_tampering`, consider task-tool changes to source evidence and
instructions embedded in a submitted artifact that try to redirect an LLM
judge. A suggestive phrase alone does not prove that the judge follows it.
Access to protected judge files or reward outputs caused by a harness mistake
is deferred rather than counted as a dataset defect.

Every candidate must describe the chain:

> protected information or grading authority → reachable interface → observable
> information or effective change → advantage under the actual grader

Name every unresolved link. A public file listing or a field named `answer` is
a discovery signal, not proof of solver access. Source data that the task
explicitly asks the agent to consult is not a hidden answer. A public rubric may
be an intentional specification. Web research may be an intended capability;
the intended information boundary determines whether lookup is a shortcut.

Keep pretrained memorization separate from retrieval during a rollout. Static
inspection can identify a contamination opportunity, but cannot establish that
a model memorized or actually used a particular solution.

## Reviewer procedure and output

1. Extract the user-visible obligations and permitted information sources.
2. Map obligations to grader checks, tools, and evidence.
3. Review every criterion, tracing relevant source and data paths.
4. For a candidate, construct a minimal witness or precise contradiction.
5. Try to refute it: inspect task-tool validation, alternate legitimate paths,
   the intended information boundary, and counterevidence in the task materials.

Produce a per-task coverage record with every criterion marked:

- `checked_no_issue`: no issue found in the stated inspected scope; not a clean
  task label or proof that all possible behaviors were checked.
- `candidate`: a concrete claim and its evidence need adjudication.
- `blocked`: the check could not be completed; list the missing evidence.
- `not_applicable`: explain why the criterion does not apply.

For every criterion, include inspected sources, a short rationale, limitations,
and candidate IDs where applicable. Save the exact prompt, model/effort,
source/profile references, and available timing and usage measurements. These
coverage states are separate from the canonical finding statuses.

No corpus code, tools, setup scripts, graders, or solutions may be imported or
executed on the audit host. Source parsing and immutable read-only database
queries can support static conclusions. Runtime-dependent claims stay unresolved
until an appropriate isolated reproduction is available.

## Scaling and adjudication

Review identical task grading/tool components once per hash, then
check applicability to each task under intended presentation. Defer generic
harness components. This experiment proposes cheap structural checks on tasks;
give each task a bounded model review using the same protocol. Independently
review candidates and a random sample of unflagged tasks. Keep source evidence
and raw detector output separate from adjudication.

Count task instances, unique mechanisms, unresolved claims, and confirmed
findings separately. Convert recurring mechanisms into deterministic screens.
Freeze reference snapshots and hold out related families or datasets before
reporting detection performance.
