# Prime shared-adapter integration

All three reviewed packages use one command:

```text
python -m rlaudit.verifiers_adapter --contract ENVIRONMENT_CONTRACT.json
```

The [contracts](../../../examples/contracts/) declare loader arguments, dataset-row assertions, interaction mode, and source metric. The [contract guide](../../../docs/environment-contracts.md) explains how to add an environment. There are no environment-name branches in the adapter. The former three bespoke drivers are retained in historical run snapshots only.

Runtime pins are `verifiers==0.3.0`, `datasets==4.3.0`, and `pyarrow==24.0.0`. Review the complete source directory and any loader data before enabling trusted execution. Run on Slurm `amd-tw-verification`:

```sh
sbatch scripts/test_pipeline.slurm
sbatch scripts/audit_prime.slurm --output runs/prime-new
```

`research/prime/prepare_configs.py` regenerates reviewed probe fixtures and manifests. It selects cases per environment; runtime loading, interaction, and grading are shared. It performs only local metadata preparation.

## Binding and scoring

Reverse Text loads four frozen real prompts through its unmodified `load_environment(dataset_name=LOCAL_DIRECTORY)`. The local JSON dataset preserves original `source_row_id`; dense fixture index 3 binds original row49. Assertions check the source question, original ID, and answer. The independent LCS oracle reads the literal tagged completion and preserves answer whitespace.

Countdown invokes its actual seeded fallback generator (`num_examples=1`, `eval_examples=1`, `seed=339`). Assertions check prompt, numbers, target, and empty source answer. The contract returns source `exact_match_reward`; details retain the full weighted rubric, whose perfect score is1.4. The independent AST/Fraction oracle enforces the prompt's operators and positive integer intermediates.

Wordle selects shipped answer rows and replays generic `input.calls` through source setup, argument injection, tools, stop method, and rubric. The state is captured under `details.state.game`, and responses under `details.tool_calls`. Its 12-call cap matches the source turn cap. There is no independent Wordle oracle yet; the declared relations and recorded duplicate-letter feedback support only their stated checks.

## Evidence limits

These are model-free parser/rubric or state/tool component checks, without full assistant orchestration or training. Framework completion and trajectory are empty scaffolds for tool replay; framework turn/tool metrics do not measure the direct calls. Grading-time framework ERROR logs fail the case; exceptions caught internally by source reward functions cannot be distinguished from legitimate zero without further instrumentation.

The original reviewed evidence remains in [the pilot report](../report.md) and [baseline validation](../validation.json). The shared-adapter migration has a separate [report](../shared_adapter_report.md) and [validation record](../shared_adapter_validation.json); changing the engine intentionally changes run fingerprints. Migration parity compares case scores, source metrics, relation outcomes, and finding IDs, while each new run's frozen replay must match its own fingerprint and semantic digest.
