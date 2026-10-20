# env-review

Collect canonical, evidence-backed information about broken tasks in evaluation
datasets and RL environments. Independent investigations contribute findings
to a shared, versioned reference set so different detection methods can be
evaluated against it.

The repository standardizes finding records and evidence, not a detection
method. Contributors can use different models, prompts, tools, and review
procedures; a joint method can be developed after comparing their results.

Findings describe specific tasks and source revisions. An unflagged task is
**unlabeled**, not known good. A rejected finding rejects that claim, not every
possible problem with the task.

The current focus is dataset defects under presentation conforming to the
published task/environment contract. Answers in intended inputs and missing
restrictions that the task depends on are in scope; harness implementation bugs
are deferred separately. See [review scope](docs/scope.md) for this boundary.

## Datasets

- [XiaomiMiMo / MiMo-V2.6-RL-oss](env/XiaomiMiMo/MiMo-V2.6-RL-oss): initial exploration of exposed knowledge-work environments.
- [allenai / Dolci-Think-RL-7B](env/allenai/Dolci-Think-RL-7B): full-split audit with an instruction-contradiction witness, and a duplicate-prompt screen of the math subset covering contradictory and placeholder reference answers and pass rates that are not comparable across rows.
- [allenai / Dolci-Think-SFT-7B](env/allenai/Dolci-Think-SFT-7B): IF-source audit of contradictory constraints and final-answer violations.
- [LumiOpen / AutoIF-FI](env/LumiOpen/AutoIF-FI): full-split audit of saved prompts and focused verifier review.
- [nebius / SWE-rebench-V2](env/nebius/SWE-rebench-V2): exploratory agent-assisted static review of specification and verifier alignment.

## Layout

```text
env/<org>/<dataset>/
  dataset.yaml                 # source, pinned revision, task identity
  findings/ER-<8 hex>.yaml      # one claim and its evidence per file
  evidence/ER-<8 hex>/          # small witnesses and validation records
  runs/<run-id>/               # raw detector outputs, scope, adjudications
schemas/                       # JSON Schemas for the YAML records
templates/finding.yaml         # copy to contribute a finding
src/eval_audit/                # small screening and catalog utilities
experiments/<investigation>/  # optional independent method proposals and notes
notes/harness/                # deferred harness observations, outside the task index
tests/
```

The finding files are the human-readable, machine-readable source of truth.
Generate the combined task index instead of editing a shared list. Separate
files and random IDs keep independent contributions easy to merge.

## Quick start

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync --locked
uv run python -m unittest discover -s tests
uv run python -m eval_audit.catalog validate
uv run python -m eval_audit.catalog index --output reports/index.json
```

The generated index includes each task's finding IDs, statuses, categories, and
source revisions. It does not convert candidates into confirmed defects.
CI validates contributions and publishes the generated index as a workflow artifact.

## Contributing

Copy the [finding template](templates/finding.yaml), give it a random ID such as
`ER-7b62a981`, and open a pull request. Include a stable task locator, exact source
revision, expected and actual behavior, quoted evidence, and a concrete witness
or a precise validation procedure. Start with `status: candidate` when uncertain.

See [CONTRIBUTING.md](CONTRIBUTING.md) for statuses, review expectations, and how
to add detector runs. See [the exploration guide](docs/exploration.md) to reproduce
the initial MiMo screens. Downloaded corpus files stay in ignored `data/` and
are never imported or executed by these screens.

Code and original contributions are licensed under Apache-2.0. Upstream datasets
and quotations retain their original attribution and licensing; see [NOTICE](NOTICE).
