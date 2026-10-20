# Prime Intellect environment audit

This pilot checks three public Hub packages using their actual frozen environment code, crafted completions, and direct tool/state replay. It uses seven real task rows and 34 cases, with frozen-input replay and semantic comparison. It measures selected grader and transition properties, not model performance or training effects.

All three audits completed on `amd-tw-verification` (Slurm **55684**), and every replay matched the original fingerprint and semantic results. Independent review confirmed four component findings: two Countdown false acceptances, one Reverse Text underreward, and one declared-metric mismatch. The 14 selected Wordle cases raised no concern.

| Environment | Frozen package | Task rows | Cases |
| --- | --- | ---: | ---: |
| [will/reverse-text](https://app.primeintellect.ai/dashboard/environments/will/reverse-text) | 0.1.4 / `9523b627a28d…` | 4 | 12 |
| [sami/countdown](https://app.primeintellect.ai/dashboard/environments/sami/countdown) | 0.1.0 / `e821f68a918d…` | 1 | 8 |
| [apple999/wordle](https://app.primeintellect.ai/dashboard/environments/apple999/wordle) | 0.1.1 / `7cea003c4fb9…` | 2 | 14 |

All source archives matched their published SHA-256 values; extracted files were verified against archive bytes. The runtime is `verifiers==0.3.0`, `datasets==4.3.0`, and `pyarrow==24.0.0` on Python 3.13. The packages use the legacy Verifiers API. See [catalog metadata](catalog/README.md), [source manifest](source_manifest.json), and [framework notes](framework/adapter_notes.md).

## Countdown: full reward for invalid solutions

The package's own generator, seed **339**, produces numbers **[2, 5, 3, 2, 50, 7]** and target **125**. Its system prompt permits only addition, subtraction, multiplication, and division, and requires every intermediate result to be a positive integer.

| Submitted solution | Rule validity | Exact-match reward | Full weighted reward |
| --- | --- | ---: | ---: |
| `(5*50)/2` | Legal control | 1.0 | 1.4 |
| `(5/2)*50` | Fractional intermediate `5/2` | 1.0 | 1.4 |
| `5**3` | Exponentiation is forbidden | 1.0 | 1.4 |

These are **confirmed component false acceptances**. The actual parser and rubric award the same full reward to the invalid expressions as to the legal control. An independent AST/Fraction checker rejects both invalid cases and accepts the control. The validator's character whitelist permits repeated `*`, and it never traces intermediate arithmetic. [Source](sources/sami__countdown__e821f68a918d/countdown.py), [independent reproduction](review/verify_countdown.55676.out), [pipeline evidence](../../runs/prime-v1/prime-countdown/probes.json).

A repair should validate an expression's AST, numeric-literal availability, permitted operators, and each exact intermediate result. Retain the legal control and the existing Unicode-operator normalization as regressions. Intentional partial rewards are separate from these full exact-match failures.

## Reverse Text: answer underreward and metric mismatch

**Exact answer underreward.** Real dataset row **49** ends with a space; its character reversal starts with that space. The probe submits the exact 103-character source gold answer, but the XML parser strips the leading space. The resulting 102-character answer receives **0.9951219512 instead of 1.0**. This is a small but reproducible penalty on a correct response. Preserve the answer field's significant whitespace, or explicitly redefine and document the task's normalization policy. [Independent review](review/reverse_findings.json).

**Declared metric mismatch.** The package describes its metric as longest common subsequence similarity but calls `difflib.SequenceMatcher`. For a perturbed answer to real row **0**, independent dynamic programming and bitset implementations find LCS length **15** for two 41-character strings: **0.3658536585** normalized similarity. The actual rubric returns **0.2926829268**. This is an implementation-versus-metric-description mismatch; the perturbed answer is incorrect, so it does not demonstrate another correct-answer penalty. [Environment source](sources/will__reverse-text__9523b627a28d/reverse_text.py), [Python's algorithm description](https://docs.python.org/3.13/library/difflib.html#the-difflib-algorithm), [pipeline evidence](../../runs/prime-v1/prime-reverse-text/probes.json).

The dataset is pinned at `b6dc8a0d8c9f59cbd4b38c490aed11f5a31c8c7f`. Selection includes three prefix rows and one whitespace edge case, not a random prevalence sample.

## Wordle coverage

Two packaged targets, `abbey` and `apple`, exercise first-guess solving, six-guess exhaustion, invalid-guess nonconsumption, solve-speed rewards, and duplicate-letter examples. The driver calls actual state setup, argument injection, guess, stop, and rubric functions. Each case respects the source's call limit. Per-letter feedback remains in evidence; reward equality alone cannot validate every feedback mark.

There is no model or full assistant/tool orchestration. Framework completion and trajectory objects are empty scaffolds, so their turn/tool metrics are not rollout evidence. The source game state and recorded direct-call feedback carry the observations. [Pipeline evidence](../../runs/prime-v1/prime-wordle/probes.json).

## Reproduction and interpretation

```sh
sbatch scripts/audit_prime.slurm --output runs/prime-new
```

Use a fresh output directory. The generic collection runner executes, verifies, replays, and compares every manifest independently. Existing bundles also contain a recorded engine and `replay.sh`. The [collection summary](../../runs/prime-v1/summary.json), [validation record](validation.json), and [reviewed findings](reviewed_findings.json) record final status, hashes, candidate IDs, and reviewed classifications. Sealed pipeline reports keep their automatic candidate labels; independent review is recorded separately.

The full suite passed **56 tests**, including an injected framework scorer failure: the drivers now turn logged scoring exceptions into inconclusive probes rather than accepting a substituted zero. Environment reward functions that internally catch their own exceptions remain a limitation. All execution used `amd-tw-verification`, with no GPUs, model calls, paid judges, or training. Findings apply to these frozen packages, framework, rows, and cases; they do not estimate Hub-wide defect prevalence or demonstrate learned exploitation.
