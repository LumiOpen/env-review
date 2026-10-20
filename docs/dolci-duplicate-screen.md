# Reproducing the Dolci duplicate screen

The run is in
[`env/allenai/Dolci-Think-RL-7B/runs/2026-10-20-duplicate-screen`](../env/allenai/Dolci-Think-RL-7B/runs/2026-10-20-duplicate-screen).
It pins revision `0fb6466d31ef3a9dd16985ef635e6429e05a6491` and covers the 30180
rows with `dataset == "math"`, a subset of the 102014 published train rows.

## Checks

```sh
uv sync --locked --extra parquet
uv run python -m eval_audit.duplicate_screen \
  --root <snapshot> --subset math \
  --output env/allenai/Dolci-Think-RL-7B/runs/2026-10-20-duplicate-screen/candidates-math.json
uv run python scripts/check_dolci_dispersion.py \
  --root <snapshot> \
  --output env/allenai/Dolci-Think-RL-7B/runs/2026-10-20-duplicate-screen/dispersion-math.json
uv run python scripts/check_dolci_references.py --root <snapshot>
```

`<snapshot>` is a local HuggingFace snapshot directory containing `data/train-*.parquet`.
Verify it against the pinned revision before trusting any row index: the commit sha
and the per-file sha256 are in the download metadata under `.cache/huggingface/download`.
Parquet is read as data through pyarrow, which is an optional extra because the catalog
tools and the rest of the tests do not need it. Nothing from the dataset is imported or
executed.

## What the screen does

Rows sharing a byte-identical prompt are measurements of one task, so they can
disagree with each other observably, without running a model or a grader. The screen
groups rows on the SHA-1 of the prompt bytes and emits five kinds of candidate:
a placeholder reference answer, a duplicated prompt, copies whose references conflict
after normalization, copies whose references are the same value in different notation,
and copies that record different pass rates despite agreeing on the reference.

Reference normalization collapses cosmetic LaTeX. It is deliberately lenient, which
makes `conflicting_reference` conservative and `notation_variant_reference` permissive;
both classes were read by hand before adjudication.

## Outcomes

| Detector | Candidates | Reviewed | Current review outcome |
| --- | ---: | ---: | --- |
| `conflicting_reference` | 5 | 5 | 3 contradictions and 2 placeholder conflicts, all confirmed |
| `notation_variant_reference` | 38 | 38 | 30 behavior-only, 8 rejected for lacking a scoring consequence |
| `sentinel_reference` | 174 | 2 | 2 confirmed against a duplicate carrying the real answer |
| `duplicate_prompt` | 4087 | 2 | aggregate count confirmed; 2 exemplars reviewed individually |
| `unstable_passrate` | 1611 | 3 | 3 behavior-only exemplars |

Five findings came out of it: contradictory references (ER-a3060c49), `-1` placeholder
references (ER-1932eb19), notation-sensitive scoring (ER-24c4c0ef), the deduplication
claim (ER-2a252105), and pass rates that are not comparable across rows (ER-9ad782d0).

Six published reference answers are called wrong, in both cases by solving the problem
independently of the dataset — 729 pairs enumerated for one, a 60-step simulation for
the other. The recorded pass rates do not identify the correct label: they favour the
correct answer in one group and the wrong one in the other, where seven rollouts were
scored correct against a reference of 61 for a problem whose answer is 31.

## The dispersion test

`check_dolci_dispersion.py` asks whether duplicate copies disagree by more than sampling
noise permits. Conditional on the pooled correct count, the split between two copies of
one prompt is Hypergeometric, so the null needs no estimate of the underlying pass rate
and no asymptotic approximation.

The answer was the opposite of the expected one. Across 1700 same-reference pairs
measured with 8 rollouts each, the mean gap is 0.996 rollouts where independence
requires 1.462 — a ratio of 0.68 at z = -16.5. The copies agree *too* closely to be
independent measurements, and the deficit is spread across the whole gap distribution
rather than concentrated at zero, so it is not a subset of rows whose metadata was
copied verbatim. The consequence is that duplicate agreement cannot be used as evidence
that the published pass rates are precise. The mechanism is not identifiable from the
published columns.

## Scope

Only the math subset was screened, and only byte-identical prompts were compared, so
every duplicate count is a lower bound. A first pass over the other subsets found the
same pattern — in general-quality the prompt `hi, how are you?` appears 164 times with
31 distinct reference responses — but those rows were not inspected and are not claimed.
Unflagged rows are unlabeled, not known good.
