# Stanford HELM: Metric Computation Implementation Bugs

Deferred observations on metric computation defects in the Stanford HELM evaluation
framework. These are harness runner bugs, not dataset defects; they are not filed as
task findings. Source repository: https://github.com/stanford-crfm/helm

---

## 1. `float_equiv` returns wrong value for non-float inputs (Issue #4340, open)

**What happens:** The `float_equiv` metric function is documented to return `1.0`
when both the prediction and reference cannot be parsed as floats (treating two
non-numeric strings as equivalent in the float-comparison context). The actual
implementation returns `0.0` in this case. Additionally, the guard condition fires
when *either* value fails to parse, not when both fail — meaning a valid float
compared to a non-numeric string is also mishandled.

**Impact:** False negatives in financial QA tasks and other tasks where correct
non-numeric answers are compared using `float_equiv`. Valid responses to questions
with non-numeric correct answers are systematically penalised.

**Status:** Open. See https://github.com/stanford-crfm/helm/issues/4340

---

## 2. `f1_score` collapses empty gold reference to zero (Issue #4340, open)

**What happens:** When the gold reference is an empty string, the `f1_score`
implementation scores any model prediction as 0.0. An empty gold reference is a
data defect in the underlying dataset, but the harness treats it as a model failure.

**Impact:** Biases scores downward for any task or split that contains entries with
empty references. The magnitude depends on the fraction of empty-reference entries
in the evaluated task.

**Status:** Open. See https://github.com/stanford-crfm/helm/issues/4340

---

## 3. `normalize_metric` uses arbitrary fixed denominators

**What happens:** HELM normalises efficiency metrics (latency, cost) before computing
composite scores. The normalization uses hardcoded denominators: latency is
normalised by 1000 ms, cost by $0.05. These values were calibrated to specific
hardware and pricing at the time of HELM's initial release.

**Impact:** As hardware performance and API pricing diverge from the calibration
values, efficiency subscores become nonsensical. A model with 50 ms latency on
modern hardware receives a very different normalised score than one with 50 ms
latency on the original hardware, making cross-time comparisons invalid.

**Status:** Open; by design as a static benchmark, but the calibration values have
not been updated to reflect current hardware.

---

## Cross-framework note: MMLU score divergence

An additional harness-level observation is that MMLU accuracy diverges by 10–30
percentage points across three faithful implementations — the Hendrycks original
script, HELM, and lm-evaluation-harness — for the same model. None of the
implementations are necessarily buggy; the divergence arises from differences in
prompt formatting, few-shot selection, answer extraction, and normalisation. This
makes cross-paper MMLU comparisons unreliable even when both papers use a harness
that is internally correct.

**Implication:** When comparing MMLU results across papers, always verify that the
same harness version, task configuration, and normalisation settings were used.
Reporting MMLU results without specifying the evaluation framework is insufficient
for reproducibility.

---

## References

- HELM issue tracker: https://github.com/stanford-crfm/helm/issues/4340
- Towards Evaluation Engineering (cross-harness systematic study): arXiv:2605.24213
- Non-determinism in LLM evaluations: arXiv:2410.03492
