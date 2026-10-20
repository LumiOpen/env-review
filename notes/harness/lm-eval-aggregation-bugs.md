# lm-evaluation-harness: Aggregation and Scoring Implementation Bugs

Deferred observations on EleutherAI/lm-evaluation-harness implementation defects.
These are harness runner bugs, not dataset defects; they are not filed as task findings.
Source repository: https://github.com/EleutherAI/lm-evaluation-harness

---

## 1. `nanmean` silently shrinks denominator on NaN predictions (Issue #4319, open)

**What happens:** When a model fails to generate a valid prediction for one or more
samples, the result is NaN. The harness uses `np.nanmean`, which silently excludes
NaN values from both the numerator and denominator. The effective sample count shrinks
from N to N−k without any warning.

**Impact:** Reported accuracy is inflated when any samples fail to generate. The degree
of inflation scales with the failure rate and is invisible to the user.

**Status:** Open as of 2026-10-20. See https://github.com/EleutherAI/lm-evaluation-harness/issues/4319

---

## 2. Generative tasks conflate unparseable responses with wrong answers (Issue #4007, open)

**What happens:** `RegexFilter` substitutes the string `"[invalid]"` when its pattern
does not match the model output. The `"[invalid]"` placeholder is then scored against
the reference and always produces score 0. There is no mechanism to distinguish a
failed parse from a genuinely wrong answer.

**Impact:** Affects 2,936 of 4,524 generative tasks (64.9%). Parse failure rates are
invisible in reported metrics. Tasks with high parse failure rates appear to have low
model accuracy when the model may be generating correct content in a different format.

**Status:** Open as of 2026-10-20. See https://github.com/EleutherAI/lm-evaluation-harness/issues/4007

---

## 3. Size-weighted group metrics use wrong sample count (Issue #4322, open)

**What happens:** Group-level aggregation uses the task's single `sample_len` value
as the weight for all metrics in the group, even when different metrics within the
task have different effective sample counts.

**Impact:** Group-level weighted scores are incorrect when tasks contribute metrics
with unequal sample counts. Weights can be off by orders of magnitude.

**Status:** Open as of 2026-10-20. See https://github.com/EleutherAI/lm-evaluation-harness/issues/4322

---

## 4. Group stderr uses wrong pooling formula

**What happens:** The pooled standard error for group-level scores applies a
size-weighted pooling formula even when the point estimate uses an unweighted mean.

**Impact:** Reported error bars are up to ~3× too narrow for group-level metrics.
This affects statistical comparisons between models at the group level.

**Status:** Unknown fix status as of 2026-10-20.

---

## 5. Regex alternation "leftmost-wins" bug (fixed)

**What happens:** Answer extraction regex with alternation (e.g., `Guilty|Guilty of
Romance`) matches the shorter prefix inside the longer correct answer string, scoring
a correct answer as wrong.

**Impact:** Affected BBH `movie_recommendation` and any task using alternation patterns
where one option is a prefix of another.

**Status:** Fixed in a prior release.

---

## 6. `minerva_math` normalization chain bugs (fixed)

**What happens:** Two bugs in the answer normalization pipeline:
- `_fix_sqrt` corrupts indexed roots: `\sqrt[3]{8}` is rewritten to `\sqrt{[}3]{8}`
  (syntactically invalid), then the exception is silently swallowed and the answer
  is scored as wrong.
- Thousands-separator stripping fuses digit tuples: `0,1` (a tuple) becomes `01`
  (a single integer), changing the answer value.

**Impact:** False negatives on math tasks containing nth-root notation or
comma-separated numeric tuples. Magnitude not quantified.

**Status:** Fixed in `minerva_math`. See note below.

---

## 7. `leaderboard_math` and `minerva_math` deliberately diverge

**What happens:** Normalization fixes were applied to `minerva_math` but not to
`leaderboard_math`. The `leaderboard_math` task was frozen to reproduce Open LLM
Leaderboard v2 results exactly.

**Impact:** The two tasks produce different scores for the same model on the same
problems. Cross-paper comparison using `leaderboard_math` in one paper and
`minerva_math` in another is not valid even though both are labeled as "MATH" results.

**Status:** By design, but an undocumented footgun for practitioners.

---

## 8. BBQ task hardcodes unknown-answer indices at `[2:13]`

**What happens:** The BBQ task implementation assumes a fixed index range for
unknown-answer options. When the dataset has a different answer distribution, the
hardcoded range silently misclassifies answers.

**Impact:** Up to 8,000 samples may be scored incorrectly. Fix status unknown.

**Source:** arXiv:2605.24213 (Towards Evaluation Engineering).

---

## 9. ROUGE-L near-1.0 bug for LLaMA-3.1-8B on LongBench

**What happens:** A metric computation bug causes LLaMA-3.1-8B to score near-perfect
ROUGE-L on all LongBench summarization tasks.

**Impact:** Summarization scores for affected model-task combinations are completely
invalid. Fix status unknown.

**Source:** arXiv:2605.24213 (Towards Evaluation Engineering).

---

## Cross-version note

`leaderboard_math` and `minerva_math` are the primary examples of a broader pattern:
normalization and scoring decisions made at different points in the harness's history
mean that results labeled with the same benchmark name are not always comparable
across papers, even when using the same harness version. Always record the exact
task name and harness git revision alongside reported metrics.
