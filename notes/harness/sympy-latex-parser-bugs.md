# SymPy LaTeX Parser: Cross-Harness Implementation Bugs

Deferred observations on bugs in SymPy-backed LaTeX math verifiers used across
multiple RL training and evaluation harnesses. These are harness/verifier runner
bugs; they are not filed as dataset findings. The bugs affect any system that
uses `sympy.parsing.latex.parse_latex` to check mathematical equivalence.

Affected harnesses include: lm-evaluation-harness (minerva_math/leaderboard_math),
lmms-eval, inspect_evals, and custom RL verifier pipelines.

---

## 1. `antlr4` version mismatch causes silent 0% accuracy (inspect_evals #2219, open)

**What happens:** `sympy.parsing.latex.parse_latex` requires `antlr4-python3-runtime`
version exactly 4.11. When the installed version differs — a common occurrence in
environments that upgrade dependencies — the LaTeX parser fails silently. The
`expression_exact_match_sympy` scorer returns 0 for every sample with no exception
or warning. The evaluation completes and reports 0% accuracy as if it were a valid result.

**Impact:** A complete scorer failure that looks like a valid (if terrible) evaluation
result. Any comparison or training signal derived from such a run is invalid.

**Detection:** Check `antlr4.__version__ == "4.11"` before running any SymPy-backed
evaluation. The eval-verifier tool's verifier_fuzzer module performs this check.

**Status:** Open. See https://github.com/UKGovernmentBEIS/inspect_evals/issues/2219

---

## 2. `_fix_sqrt` corrupts indexed roots (lmms-eval #1505, open)

**What happens:** The normalization function `_fix_sqrt` in lmms-eval (and derived
harnesses) rewrites `\sqrt[3]{8}` to `\sqrt{[}3]{8}` — syntactically invalid LaTeX.
The parse_latex call on the corrupted string raises an exception. Most harness
implementations silently catch this exception and score the answer as 0.

**Impact:** Systematic false negative for any math answer expressed using nth-root
notation (`\sqrt[n]{...}` for n > 2). The correct answer `\sqrt[3]{8} = 2` is
scored as wrong whenever the model uses indexed root notation.

**Status:** Open. See https://github.com/EvolvingLMMs-Lab/lmms-eval/issues/1505

---

## 3. `\dfrac` not equated with `\frac`

**What happens:** SymPy's LaTeX parser treats `\dfrac` (display-style fraction) and
`\frac` (inline fraction) as distinct expressions. They are semantically equivalent
but parse to different internal representations that are not reduced to the same
symbolic form.

**Impact:** False negative whenever a model outputs `\dfrac{1}{2}` where the reference
is `\frac{1}{2}` or vice versa. Display-style fractions are common in model outputs
trained on LaTeX-heavy math corpora.

**Status:** Known; no standard fix in the harnesses reviewed.

---

## 4. Comma in LaTeX causes unhandled parser exception

**What happens:** Expressions using commas in mathematical notation (e.g., interval
notation `(0, 1)`, set notation `\{1, 2, 3\}`) cause `parse_latex` to raise an
exception. Most harness implementations silently catch this and return score 0.

**Impact:** False negative for any answer expressed in interval or set notation with
commas. This is common in precalculus and real analysis problems.

**Status:** Known. Documented in HARP paper (arXiv:2412.08819).

---

## 5. SymPy hangs on pathological expressions

**What happens:** Certain complex LaTeX expressions — particularly nested fractions
and derivatives of rational functions — cause `parse_latex` or subsequent symbolic
simplification to enter an indefinitely long computation. Harnesses without a
per-call timeout will hang the entire evaluation.

**Mitigation:** Wrap all SymPy calls with a SIGALRM timeout (Unix) or a
multiprocessing timeout. The eval-verifier tool applies a 10-second default timeout
during fuzzing.

**Status:** Known. Documented in HARP paper (arXiv:2412.08819).

---

## 6. Thousands-separator stripping fuses digit tuples

**What happens:** The thousands-separator normalization step in some harnesses strips
commas from numeric strings. When the input is a comma-separated pair or tuple
(e.g., `0,1` representing the pair (0, 1)), the commas are stripped, fusing the
values into a single number (`01` or `1`). The numerical value changes.

**Impact:** False negative or false positive depending on whether the fused result
happens to match the reference. Particularly affects combinatorics problems where
answers are given as ordered pairs.

**Status:** Fixed in lm-eval `minerva_math`; present in other harnesses that use
similar normalization.

---

## Summary of false-negative rates

The aggregate false-negative rate from these bugs on MATH-500 is approximately
10–15% depending on the harness configuration and the distribution of answer notation
styles. The HARP paper (arXiv:2412.08819) and "Checking the Checkers"
(arXiv:2610.17824) provide quantitative measurements. An additional finding from
"Checking the Checkers" is that 38.5% of rejected responses in a 226K-response audit
were actually correct — rejected due to notation differences, not incorrect answers.
This is the dominant source of training signal corruption in math RL pipelines using
SymPy-backed verifiers.
