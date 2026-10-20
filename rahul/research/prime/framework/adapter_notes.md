# Model-free grading for three Prime Intellect Hub environments

These framework-discovery notes describe the original pilot and smoke fixtures. Current audits use the [shared adapter and environment contracts](../../../docs/environment-contracts.md). Reverse Text now reads a local pinned JSON dataset directory through its unmodified loader; current audits do not patch `load_dataset`.

The selected Hub packages (`will/reverse-text`, `sami/countdown`, `apple999/wordle`) use the legacy top-level `verifiers` API. Pin `verifiers==0.3.0` ([Git tag at commit `0a4d872f021022310a08ec213a25f4efb4a0244a`](https://github.com/PrimeIntellect-ai/verifiers/tree/0a4d872f021022310a08ec213a25f4efb4a0244a)). Its root exports `Rubric`, `SingleTurnEnv`, `StatefulToolEnv`, and `XMLParser`. Release `0.3.1` removes the legacy environment/rubric exports; `0.4.0` exposes only `verifiers.v1`. The `0.3.0` PyPI wheel SHA-256 is `b4c734c962a48afc1f9e836f20c04b1790b168ec8d47dbbefe45d175ecc58569` ([release metadata](https://pypi.org/pypi/verifiers/0.3.0/json)). Use `datasets==4.3.0` with it, satisfying `verifiers`' `datasets>=3.3,<6` requirement ([datasets release metadata](https://pypi.org/pypi/datasets/4.3.0/json)). Python 3.13 is supported by both.

The minimal JSON driver should load the **actual environment module** and call its **actual rubric** on a manufactured completion or replayed state. [`Rubric.score_rollout`](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/rubrics/rubric.py#L319-L356) is async and mutates `state["reward"]` and `state["metrics"]`. [`Rubric.score_objects`](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/rubrics/rubric.py#L125-L157) passes `prompt`, `completion`, `answer`, `state`, `info`, parser, and extra input-row fields to reward functions. Minimal call shape:

```python
state = {
    "prompt": [{"role": "user", "content": task_prompt}],
    "completion": [{"role": "assistant", "content": candidate_reply}],
    "answer": reference_answer,
    "info": reference_info,
    "trajectory": [],
}
await env.rubric.score_rollout(state)
result = {"reward": state["reward"], "metrics": state["metrics"]}
```

`trajectory` is required because [`MultiTurnEnv` adds a `num_turns` metric](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/envs/multiturn_env.py#L32-L38). The rubric [catches reward-function exceptions and substitutes zero](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/rubrics/rubric.py#L184-L219), so capture stderr/logs and check expected metric keys; a numeric zero can hide a fixture error. Call `env.rubric` for the full grade. Label direct source reward-function calls as component probes.

For Reverse Text, `load_environment` downloads a Hugging Face dataset by default. A bounded audit can substitute a frozen one-row `datasets.Dataset` at its `load_dataset` boundary, then call the actual `load_environment` and rubric. Its nested `lcs_reward_func` in [reverse_text.py](../sources/will__reverse-text__9523b627a28d/reverse_text.py) uses `parser.parse_answer(completion)`. [`XMLParser.parse_answer`](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/parsers/xml_parser.py#L91-L115) accepts a string or message list; use a list to match a completion trace.

For Countdown, `load_environment` creates a three-function weighted rubric (1.0 exact match, 0.3 closeness, 0.1 format) in [countdown.py](../sources/sami__countdown__e821f68a918d/countdown.py). A frozen small dataset may be injected at its builder boundary. `state["info"]` must contain `numbers` and `target`. Its `parse_completion` reads the last message from a list, so a string is unsuitable. A source-valid perfect answer totals `1.4`; this reward is not capped at 1.

For Wordle, [WordleEnv](../sources/apple999__wordle__7cea003c4fb9/wordle/wordle.py) builds a 2,300-row local dataset without a model or API. Start with `state["answer"]` and `await env.setup_state(state)`; inherited [`MultiTurnEnv.setup_state`](https://github.com/PrimeIntellect-ai/verifiers/blob/0a4d872f021022310a08ec213a25f4efb4a0244a/verifiers/envs/multiturn_env.py#L99-L101) exists. For replayed actions, the environment's `update_tool_args` injects the hidden answer and mutable game; `await env.guess(word, answer, game)` executes the actual tool transition, then `await env.rubric.score_rollout(state)` grades it. Supplying `game` directly tests only the grader state, not the tool path.

The [pipeline contract](../../../docs/pipeline.md) accepts exact PyPI distribution versions. Use `execution.dependencies: {"verifiers":"0.3.0","datasets":"4.3.0"}` and record environment archive hashes as sources; the worker records installed transitive versions. It cannot express the Git commit or wheel hash as a dependency spec, so record those separately as provenance. Review imports and avoid default remote dataset loads, model clients, and judges. Each case returns one finite reward and metrics as details; a grader/setup exception should cause nonzero driver exit. Interpret results only for the frozen task row, reply/action sequence, and pinned source versions.

The [smoke fixture](smoke_legacy.py) used actual environment imports and rubric calls with frozen local rows, no model or API calls. On `amd-tw-verification`, Slurm job `55677` completed in 7 seconds after packages were cached: Reverse Text reward `1.0`, Countdown `1.4`, Wordle initial-game `0.0`; framework and source metrics were present. Cold-install job `55674` completed in 21 seconds and peaked at about 2.9 GiB RSS, so request 4 GiB for a cold `uv` run. Command:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python /shared_silo/scratch/rahul.aralikatte@amd.com/miniconda3/bin/python --with verifiers==0.3.0 --with datasets==4.3.0 python -B research/prime/framework/smoke_legacy.py
```

The fixture substitutes local single-row datasets for Reverse Text and Countdown to avoid network access and generation. It does not prove a model rollout or Wordle action sequence; paired pipeline probes must supply and record the concrete cases they claim to test.
