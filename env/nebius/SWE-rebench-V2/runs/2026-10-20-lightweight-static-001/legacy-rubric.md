# Labelling rubric: is this RL task's reward a signal or noise?

Setting: an RL policy sees only PROBLEM_STATEMENT and the repo at `base_commit`. It edits the repo. Then TEST PATCH is applied and the FAIL_TO_PASS (F2P) and PASS_TO_PASS (P2P) tests run. Reward = fraction of F2P tests passing, gated on P2P. GOLD PATCH is the reference fix. Its tests were execution-validated: they fail before the gold patch and pass after it.

Static analysis only. Read the task file; do not clone repos or run code. You may reason about the repo from the diffs.

## Core question

Imagine a competent engineer who reads only the PROBLEM_STATEMENT, explores the repo, and writes a correct, reasonable fix that differs from the gold patch.

1. `p_correct_fix_passes`: how likely does such a fix get full reward? `high` (>80%), `medium` (40–80%), `low` (<40%).
2. `wrong_fix_can_pass`: could an obviously incomplete or wrong fix get full reward? `yes` / `no`.

## Verdict

- `BROKEN`: `p_correct_fix_passes` = low, OR `wrong_fix_can_pass` = yes, OR the task is invalid (statement unrelated to or contradicting the patch and tests, or impossible).
- `QUESTIONABLE`: `p_correct_fix_passes` = medium.
- `VALID`: high, and not exploitable.

Judge against PROBLEM_STATEMENT alone. Separately, record whether INTERFACE would fix the issue.

## Issue classes (all that apply)

| Class | Meaning |
|---|---|
| `HIDDEN_INTERFACE` | Tests require names, signatures, files, or CLI flags not stated or inferable |
| `OVERSPECIFIED` | Tests assert exact strings, formats, error messages, or implementation details not specified |
| `SCOPE_CREEP` | Tests check behaviour beyond the statement, or the gold patch contains unrelated changes the tests depend on |
| `AMBIGUOUS` | Statement lacks expected behaviour or acceptance criteria; several reasonable fixes exist and tests pick one |
| `MISMATCH` | Statement and patch/tests are about different things, or contradict each other |
| `WEAK_TEST` | F2P tests do not really verify the stated fix (trivial assertions, snapshot-only, only checks "no exception") |
| `LEAK` | Statement contains the solution (code or exact diff) |
| `EXTERNAL_INFO` | Essential info only behind URLs or in implicit domain knowledge |
| `INFRA` | Nondeterminism, network, wall-clock time, unstable parametrised test IDs, unpinned deps that affect outcome |
| `TEST_COUPLING` | F2P/P2P include tests unrelated to the issue that a correct fix may break |
| `TRUNCATED` | The task file was truncated and you couldn't judge properly |

## Calibration examples

- The statement says "`parse()` crashes on empty input; it should return `[]`", and the test asserts `parse("") == []`. → VALID.
- The statement says "add support for YAML config", and the tests call `load_config_yaml(path, strict=True)`, a name and keyword argument that appear nowhere in it. → BROKEN, HIDDEN_INTERFACE. Interface resolves it = yes, if INTERFACE lists that signature.
- The statement says "improve the error message when the file is missing", and the test asserts the exact string `"Config file 'x' not found (searched: a, b)"`. → BROKEN, OVERSPECIFIED.
- The statement is a one-line title such as "Bug in date handling", and the tests encode one specific behaviour. → BROKEN, AMBIGUOUS.
- The statement asks for feature X, and the F2P tests check X plus an unrelated refactor rename done in the same PR. → BROKEN or QUESTIONABLE, SCOPE_CREEP.
- 40 F2P tests, where 38 are pre-existing tests that started passing only because the gold patch also bumped a dependency. → SCOPE_CREEP and/or INFRA.

Be calibrated, not harsh: many real tasks are fine. Do not mark BROKEN just because the task is hard.

## Output

Append one JSON object per task (one line, JSONL) to your output file:

```json
{"file": "007_owner__repo-123.md", "instance_id": "owner__repo-123", "verdict": "VALID|QUESTIONABLE|BROKEN", "p_correct_fix_passes": "high|medium|low", "wrong_fix_can_pass": "yes|no", "classes": ["HIDDEN_INTERFACE"], "interface_resolves": "yes|no|na", "confidence": 0.0-1.0, "evidence": "<=40 words, quote the decisive test line or statement gap"}
```
