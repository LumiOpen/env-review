# Environment contracts

The pipeline runner owns snapshots, scheduling, resource limits, evidence, and replay. A framework adapter owns loading, reset, interactions, and upstream scoring. A small environment contract binds that interface to reviewed task rules. Add a framework adapter when the interface changes; add an oracle family when the semantics change.

## Add a compatible environment

1. Review and pin the environment package and task data as manifest sources.
2. Export selected tasks as normalized JSONL. Keep original row IDs, seeds, and independently established answers in `metadata`.
3. Add a `rlaudit.environment/v1` contract. Use [the Prime contracts](../examples/contracts/) as examples.
4. Declare the contract as a source and reuse this command for every probe:

   ```json
   ["{python}", "-m", "rlaudit.verifiers_adapter", "--contract", "{source:contract}"]
   ```

5. Supply valid controls and targeted invalid or equivalent variants. Declare `expected`, `invariant`, or `nondecreasing` relations with a justification. Run `plan`, then submit the audit and frozen replay on `amd-tw-verification`.

[The token-copy example](../examples/verifiers_demo/) adds an unrelated fourth environment using only source, task data, and JSON configuration. It needs no custom driver.

## Contract fields

| Field | Purpose |
| --- | --- |
| `loader` | Declared source ID, dotted module, public factory, and keyword arguments. |
| `task` | `dataset` or `eval_dataset`, row index, and required row-field assertions. Assert the prompt and relevant answer/info fields to prevent a wrong-row test. |
| `interaction` | `completion`, or bounded `tool_sequence` with allowed tools, stop method, and state captures. |
| `score` | Actual source metric or `reward`, plus required finite metric names. |
| `capture` | Whether to record the source parser's answer. |
| `oracle` | Optional independent arithmetic, exact-text, or LCS reference calculation. |

Values support recursive references: `{"task":"metadata.seed"}` and `{"source":"dataset"}`. Oracle inputs also support `{"case":"input.completion"}`. These reserved reference keys cannot be ordinary object keys. Unknown schema fields and missing references fail explicitly. No expressions or Python code are evaluated from contracts.

Completion cases use `input.completion`. Tool cases use `input.calls`, for example:

```json
{"calls":[{"tool":"guess","args":{"word":"apple"}}]}
```

The adapter calls source setup, argument injection, tool transitions, stop method, and rubric. It enforces the declared call cap and the source's `max_turns` when exposed. Each case runs in a fresh process. Captured `details.state` and `details.tool_calls` describe these direct calls; empty framework trajectory metrics do not represent an agent rollout.

## Reference checks and evidence

Arithmetic uses bounded AST traversal and exact fractions, checking declared operators, number multiplicity, signs, and intermediate values. Exact text preserves whitespace. LCS uses an independent dynamic-programming implementation with bounded work. Optional `tag` extraction reads the actual completion without trimming its answer; missing or repeated tags are malformed candidates. Oracle configuration/reference errors fail the case.

The source score remains the primary `reward`. Reference facts appear under `details.oracle.expected_reward`; they never replace the score being audited. Relations remain explicit hypotheses: attaching an oracle does not automatically create a finding or establish that its specification is correct. Wordle currently uses declared relations and recorded feedback, without an independent game oracle.

## Runtime and limits

This adapter supports the reviewed **Verifiers v0** interface with `verifiers==0.3.0` and `datasets==4.3.0`; the examples also pin `pyarrow==24.0.0`. Other framework versions require an adapter and validation. Source modules load under a private namespace, preserving relative imports. Required row assertions and framework grading-error logs cause failures instead of misleading zero scores; exceptions swallowed inside source reward functions remain a limitation.

Use `trusted_process` with explicit opt-in for these reviewed examples. It is not a sandbox. Module drivers receive only the archived engine in `PYTHONPATH`; inherited host module paths are excluded. The shared adapter is not provisioned inside Docker by this change. Replay archives both adapter and oracle code alongside sources and contracts.

The collection runner replays inside the same pinned compute environment. Separate `replay.sh --backend slurm` submission can fail when locked site-specific wheels, such as the cluster's ROCm torch build, are absent from the package index. Provision the matching runtime on a compute node and use the archived helper with `--backend current`, or configure an index containing those wheels. Dependency locking currently also records installed optional requirements; reducing that overcapture is separate work.
