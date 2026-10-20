# Static review rubric v1

This is the protocol for the next systematic pass. The initial exploration did
not apply this rubric uniformly; its original prompts and outcomes remain in
the initial run. No v1 corpus-wide run has been completed.

The review unit is a task at a dataset revision **under a named execution
profile**. Pin the harness and dependency revisions, resolved configuration,
and image digest when known. A different runner can change answer visibility,
reachable actions, and grading. Record unknown deployment facts explicitly.

## Establish the execution profile first

Distinguish the task-solving agent, the grading agent, and our audit agents.
Audit agents can inspect private grading materials as evidence; this does not
make those materials visible to the task-solving agent.

Record these properties, with source references and one of `declared`,
`inferred_from_source`, `observed_runtime`, or `unknown` for each conclusion:

- Agent-visible prompt and tool schemas, including shell and file tools.
- File and database visibility, mount permissions, process users, and timing:
  setup, rollout, grading, and reset between tasks.
- Network reachability separately for setup, rollout, and grading; distinguish
  local services, allowed external destinations, and arbitrary outbound access.
- Instructions about external information, reference solutions, hidden tests,
  and grading materials. Record `unspecified` when the inspected instructions
  say nothing; this is not evidence of either permission or technical blocking.
- Enforced restrictions: network policy, tool allowlists, action guards, file
  isolation, and cleanup. Follow the actual execution path to confirm that a
  configured restriction is used.
- Grader inputs, execution identity, feedback exposed during rollout, and
  opportunities for repeated submissions or state reuse.
- Public availability of task solutions or grading artifacts at the time of
  the run. A release published after training cannot establish a training leak.

See the [MiMo runtime review](mimo-runtime.md) for the first source-based profile.

## Criteria

| ID | Criterion | Required investigation |
| --- | --- | --- |
| inputs | Required information | Can the solver obtain necessary assets and facts through the intended interface? Distinguish uncached assets from absent source assets. |
| specification | Coherent task | Are essential requirements consistent and sufficiently determined? Identify consequential ambiguity, not stylistic preferences. |
| false_negative | Valid behavior rejected | Does a permitted answer, equivalent representation, or allowed sequence fail an actual grading condition? |
| false_positive | Invalid behavior rewarded | Can a substantive obligation or prohibition be violated without affecting the relevant grade? Include state and trajectory requirements. |
| reference | Correct references | Reconcile authoritative data, calculations, identifiers, dates, and expected values. |
| feasibility | Reachable result | Can exposed tools transform initial state into the required result? Check tool-enforced invariants and alternative paths. |
| verifier | Reliable grading | Trace actual evidence selection, exceptions, truncation, skipped checks, and runtime assumptions. |
| reward | Meaningful scoring | Explain weights, defaults, gates, aggregation, and no-op behavior. An unusual reward offset is not automatically a defect. |
| answer_exposure | Protected information reachable | Trace hidden answers, tests, private grading details, or reference solutions to an agent-visible observation during the task. |
| grader_tampering | Grading process influence | Can the solver alter grading inputs, protected state, test infrastructure, reward files, or judge instructions to gain reward without satisfying the task? |

## Answer exposure and reward hacking

For `answer_exposure`, examine:

- Answer keys, reference solutions, hidden tests, private rubric details, and
  label-bearing fields accidentally included in prompts or tool responses.
- Container contents, workspace files, temporary files, logs, caches, notebooks,
  build residue, Git history, remote refs, and artifacts from earlier attempts.
- Tool APIs that expose more columns or files than intended, unrestricted query
  interfaces, and paths that cross a filesystem or service boundary.
- Online lookup of public benchmark answers, upstream fixes, solved versions,
  task-specific discussions, or the released dataset's own grading materials.
- Feedback that lets the solver extract hidden answers or optimize against a
  supposedly held-out test through repeated submissions.

For `grader_tampering`, include changes to the judge's environment, test runner,
reward output, or source evidence, and instructions embedded in a submitted
artifact that try to redirect an LLM judge. A suggestive phrase alone does not
prove that the judge follows it.

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
5. Try to refute it: inspect tool validation, alternate paths, mount boundaries,
   cleanup, upload timing, and the actual dispatch path.

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

Review identical runtime components once per hash and execution profile, then
check applicability to each task. Apply cheap structural checks to all tasks;
give each task a bounded model review using the same protocol. Independently
review candidates and a random sample of unflagged tasks. Keep source evidence
and raw detector output separate from adjudication.

Count task instances, unique mechanisms, unresolved claims, and confirmed
findings separately. Convert recurring mechanisms into deterministic screens.
Freeze reference snapshots and hold out related families or datasets before
reporting detection performance.
