"""
Module 1: Verifier Fuzzer

Tests a math/constraint verifier against a battery of known equivalence pairs,
known non-equivalent pairs, and edge cases — reporting false-positive and
false-negative rates.

Covers bugs documented in:
  - lm-eval minerva_math (_fix_sqrt, thousands-separator)
  - SymPy antlr4 silent-0% failure
  - dfrac vs frac non-equivalence
  - Comma-in-LaTeX crash
  - Empty-output false positive (GRPO exploit)
  - Off-by-one near 1e4 (deterministic false positive)
  - IFEval constraint checker mismatches
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from eval_verifier.report import Finding, ModuleResult, Severity

# ---------------------------------------------------------------------------
# Verifier protocol
# ---------------------------------------------------------------------------

VerifierFn = Callable[[str, str], bool]


def _make_cli_verifier(cmd_template: str) -> VerifierFn:
    """
    Wrap a CLI command as a verifier.
    cmd_template must contain {pred} and {ref} placeholders.
    Returns True when the command exits with code 0.
    """
    def _verify(pred: str, ref: str) -> bool:
        cmd = cmd_template.format(pred=pred, ref=ref)
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
        return result.returncode == 0
    return _verify


# ---------------------------------------------------------------------------
# Test-case library
# ---------------------------------------------------------------------------

@dataclass
class EquivCase:
    pred: str
    ref: str
    expect: bool        # True  = verifier should accept (TP expected)
                        # False = verifier should reject (TN expected)
    category: str
    description: str
    known_bug: str | None = None   # references the documented bug if applicable


# Math equivalence pairs: same value, different notation → expect True
_MATH_EQUIV: list[EquivCase] = [
    # Fraction notation
    EquivCase(r"\frac{1}{2}", r"\frac{1}{2}", True, "fraction", "identical fractions"),
    EquivCase(r"\dfrac{1}{2}", r"\frac{1}{2}", True, "fraction",
              r"\dfrac vs \frac", known_bug="lmms-eval: dfrac not equated with frac"),
    EquivCase("0.5", r"\frac{1}{2}", True, "fraction", "decimal vs fraction"),
    EquivCase("1/2", r"\frac{1}{2}", True, "fraction", "plain division vs latex fraction"),
    EquivCase(r"\frac{2}{4}", r"\frac{1}{2}", True, "fraction", "unreduced fraction"),
    EquivCase(r"\frac{-1}{2}", r"-\frac{1}{2}", True, "fraction", "negation inside vs outside"),

    # Square roots and indexed roots
    EquivCase(r"\sqrt{4}", "2", True, "root", "sqrt(4) = 2"),
    EquivCase(r"\sqrt[3]{8}", "2", True, "root",
              "cube root", known_bug="lm-eval: _fix_sqrt corrupts \\sqrt[3]{8}"),
    EquivCase(r"\sqrt[4]{16}", "2", True, "root",
              "fourth root", known_bug="lm-eval: _fix_sqrt corrupts nth root"),
    EquivCase(r"\sqrt[2]{9}", "3", True, "root", "explicit square root"),

    # Thousands separator — the known false-positive bug
    EquivCase("1000", "1000", True, "separator", "plain 1000"),
    EquivCase("1,000", "1000", True, "separator",
              "thousands comma", known_bug="lm-eval: thousands-separator strip fuses tuples"),
    EquivCase("10,000", "10000", True, "separator", "ten thousand with comma"),
    EquivCase("1,000,000", "1000000", True, "separator", "million with commas"),

    # Off-by-one near 1e4 (the deterministic false-positive)
    EquivCase("9999", "10000", False, "off-by-one",
              "9999 ≠ 10000 — should reject",
              known_bug="Checking the Checkers: off-by-one accepted when ref >= 1e4"),
    EquivCase("10001", "10000", False, "off-by-one",
              "10001 ≠ 10000 — should reject"),

    # Scientific notation
    EquivCase(r"1.5 \times 10^{3}", "1500", True, "scientific", "sci notation"),
    EquivCase(r"1.5 \cdot 10^3", "1500", True, "scientific", "cdot sci notation"),
    EquivCase("1.5e3", "1500", True, "scientific", "e-notation"),

    # Boxed answers (common in training data)
    EquivCase(r"\boxed{42}", "42", True, "boxed", "boxed integer"),
    EquivCase(r"\boxed{\frac{1}{2}}", r"\frac{1}{2}", True, "boxed", "boxed fraction"),

    # Text wrapping
    EquivCase(r"\text{2}", "2", True, "text", r"\text wrapping"),
    EquivCase(r"\mathrm{e}", r"e", True, "text", r"\mathrm{e} = e"),

    # Display math wrapping
    EquivCase("$$42$$", "42", True, "display-math", "display math delimiters"),
    EquivCase("$42$", "42", True, "display-math", "inline math delimiters"),

    # Percentages
    EquivCase(r"50\%", "50%", True, "percent", "latex percent vs plain"),

    # Infinity
    EquivCase(r"\infty", "inf", True, "infinity", "latex infinity"),
    EquivCase(r"+\infty", r"\infty", True, "infinity", "plus infinity"),

    # Negative fractions
    EquivCase("-0.5", r"-\frac{1}{2}", True, "negative", "negative decimal vs fraction"),

    # Integers written as floats
    EquivCase("2.0", "2", True, "integer-float", "float vs integer"),
    EquivCase("2.00", "2", True, "integer-float", "trailing zeros"),

    # Simple arithmetic results
    EquivCase("6", "6", True, "identity", "integer identity"),
    EquivCase("0", "0", True, "identity", "zero"),
    EquivCase("-7", "-7", True, "identity", "negative integer"),
]

# Non-equivalent pairs: clearly different values → expect False
_MATH_NON_EQUIV: list[EquivCase] = [
    EquivCase("1", "2", False, "distinct", "1 ≠ 2"),
    EquivCase("0", "1", False, "distinct", "0 ≠ 1"),
    EquivCase(r"\frac{1}{3}", r"\frac{1}{2}", False, "fraction", "1/3 ≠ 1/2"),
    EquivCase("-1", "1", False, "sign", "negative vs positive"),
    EquivCase("100", "1000", False, "magnitude", "100 ≠ 1000"),
]

# Edge cases that commonly cause crashes or silent failures
_MATH_EDGE: list[EquivCase] = [
    EquivCase("", "42", False, "empty",
              "empty prediction should be wrong",
              known_bug="GRPO: empty output triggers false positive in some verifiers"),
    EquivCase("   ", "42", False, "whitespace",
              "whitespace-only prediction should be wrong"),
    EquivCase("No solution", "No solution", True, "no-solution",
              "no solution string identity"),
    EquivCase(r"\text{No solution}", "No solution", True, "no-solution",
              "latex no solution vs plain"),
    EquivCase("None", "42", False, "none",
              "Python None string should be wrong"),
    # Comma in LaTeX — documented SymPy crash vector
    EquivCase(r"(0, 1)", r"(0, 1)", True, "comma-latex",
              "interval with comma",
              known_bug="SymPy: comma in LaTeX raises unhandled exception"),
    EquivCase(r"\{1, 2, 3\}", r"\{1, 2, 3\}", True, "set",
              "set with commas"),
    # Partial answer — permissive checkers accept this
    EquivCase("x = 2", "2", True, "partial",
              "answer with variable assignment prefix"),
    EquivCase("The answer is 42", "42", False, "partial",
              "answer buried in prose — should reject unless extraction is done"),
]

ALL_MATH_CASES: list[EquivCase] = _MATH_EQUIV + _MATH_NON_EQUIV + _MATH_EDGE

# ---------------------------------------------------------------------------
# IFEval-style constraint checker probes
# ---------------------------------------------------------------------------

@dataclass
class ConstraintProbe:
    constraint_type: str
    satisfying_response: str
    violating_response: str
    description: str
    known_bug: str | None = None


IFEVAL_PROBES: list[ConstraintProbe] = [
    ConstraintProbe(
        "word_count_at_least",
        " ".join(["word"] * 100),
        " ".join(["word"] * 5),
        "response with ≥100 words vs <100 words",
    ),
    ConstraintProbe(
        "paragraph_count_at_least",
        "Para one.\n\nPara two.\n\nPara three.",
        "Only one paragraph here.",
        "at-least-3-paragraphs — checker bug: some implementations require EXACTLY N",
        known_bug="IFEval: 'at least N paragraphs' vs 'exactly N' checker mismatch",
    ),
    ConstraintProbe(
        "starts_with",
        "Answer: here is the content",
        "here is the content",
        "response starting with 'Answer:'",
    ),
    ConstraintProbe(
        "ends_with",
        "content here. THE END",
        "content here",
        "response ending with 'THE END'",
    ),
    ConstraintProbe(
        "contains_keyword",
        "This response mentions the keyword elephant.",
        "This response has no relevant term.",
        "response containing keyword 'elephant'",
    ),
    ConstraintProbe(
        "no_comma",
        "This response has no commas at all.",
        "This response, however, has commas.",
        "response without commas",
    ),
    ConstraintProbe(
        "symbol_frequency",
        "#### heading with hash #### more hash ####",
        "no hash symbols here",
        "# symbol frequency ≥ 4",
        known_bug="IFEval: symbol checker only handles a-z; '#' constraint always scores 0",
    ),
    ConstraintProbe(
        "json_format",
        '{"key": "value", "number": 42}',
        "not valid json {{{{",
        "valid JSON response",
    ),
    ConstraintProbe(
        "bullet_list",
        "- item one\n- item two\n- item three",
        "one item two item three item",
        "response using bullet list format",
    ),
    ConstraintProbe(
        "uppercase_only",
        "ALL CAPS RESPONSE HERE",
        "mixed Case response here",
        "uppercase-only response",
    ),
]

# ---------------------------------------------------------------------------
# SymPy health checks
# ---------------------------------------------------------------------------

def check_sympy_health() -> list[Finding]:
    """Check whether sympy + antlr4 are correctly installed and functional."""
    findings: list[Finding] = []

    try:
        import sympy  # noqa: F401
    except ImportError:
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=Severity.INFO,
            title="SymPy not installed",
            description="SymPy is not available; skip SymPy-specific checks. "
                        "Install with: pip install 'eval-verifier[math]'",
        ))
        return findings

    # antlr4 version check
    try:
        import antlr4
        version = getattr(antlr4, "__version__", "unknown")
        if version != "4.11":
            findings.append(Finding(
                module="verifier_fuzzer",
                severity=Severity.HIGH,
                title="antlr4 version mismatch",
                description=f"antlr4-python3-runtime version is '{version}'; "
                            "SymPy's LaTeX parser requires exactly 4.11. "
                            "Mismatched versions cause expression_exact_match_sympy "
                            "to score every sample 0% silently.",
                metric="antlr4_version",
                known_bug="inspect_evals #2219: antlr4 mismatch → silent 0% accuracy",
                details={"installed_version": version, "required_version": "4.11"},
            ))
    except ImportError:
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=Severity.HIGH,
            title="antlr4 not installed",
            description="antlr4-python3-runtime is missing. "
                        "SymPy's LaTeX parser (and expression_exact_match_sympy) "
                        "will silently score every sample 0%.",
            known_bug="inspect_evals #2219: missing antlr4 → silent 0% accuracy",
        ))

    # SymPy hang check — run a known-pathological expression with timeout
    try:
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError

        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(5)
        try:
            from sympy.parsing.latex import parse_latex
            # A moderately complex expression that is known to be slow
            parse_latex(r"\frac{d}{dx}\left(\frac{x^2+1}{x^3-1}\right)")
        finally:
            signal.alarm(0)
    except TimeoutError:
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=Severity.HIGH,
            title="SymPy LaTeX parser hangs on complex expressions",
            description="parse_latex timed out (>5s) on a moderately complex expression. "
                        "Add a SIGALRM timeout wrapper around all SymPy calls in your verifier.",
            known_bug="HARP arXiv:2412.08819: SymPy hangs on pathological LaTeX",
        ))
    except AttributeError:
        # signal.SIGALRM not available on Windows — skip
        pass
    except Exception:
        pass

    return findings

# ---------------------------------------------------------------------------
# Core fuzzing logic
# ---------------------------------------------------------------------------

@dataclass
class FuzzResult:
    case: EquivCase
    got: bool           # what verifier returned
    expected: bool
    elapsed_s: float
    timed_out: bool = False
    error: str | None = None

    @property
    def correct(self) -> bool:
        return not self.timed_out and self.error is None and self.got == self.expected

    @property
    def is_false_positive(self) -> bool:
        """Verifier accepted when it should have rejected."""
        return not self.timed_out and self.error is None and self.got and not self.expected

    @property
    def is_false_negative(self) -> bool:
        """Verifier rejected when it should have accepted."""
        return not self.timed_out and self.error is None and not self.got and self.expected


def _run_case(verifier: VerifierFn, case: EquivCase, timeout_s: float = 10.0) -> FuzzResult:
    t0 = time.monotonic()
    try:
        if sys.platform != "win32":
            import signal

            def _h(s, f): raise TimeoutError
            signal.signal(signal.SIGALRM, _h)
            signal.alarm(int(timeout_s) + 1)
            try:
                result = verifier(case.pred, case.ref)
            finally:
                signal.alarm(0)
        else:
            result = verifier(case.pred, case.ref)
        elapsed = time.monotonic() - t0
        timed_out = elapsed > timeout_s
        return FuzzResult(case=case, got=result, expected=case.expect,
                          elapsed_s=elapsed, timed_out=timed_out)
    except TimeoutError:
        return FuzzResult(case=case, got=False, expected=case.expect,
                          elapsed_s=time.monotonic() - t0, timed_out=True)
    except Exception as exc:
        return FuzzResult(case=case, got=False, expected=case.expect,
                          elapsed_s=time.monotonic() - t0, error=str(exc))


def fuzz_math_verifier(
    verifier: VerifierFn,
    cases: list[EquivCase] | None = None,
    timeout_s: float = 10.0,
) -> list[FuzzResult]:
    """Run all math equivalence probes through the verifier and return results."""
    if cases is None:
        cases = ALL_MATH_CASES
    return [_run_case(verifier, c, timeout_s) for c in cases]


def _severity_for_rate(rate: float, metric: str) -> Severity:
    thresholds = {
        "false_negative_rate": [(0.15, Severity.CRITICAL), (0.05, Severity.HIGH), (0.01, Severity.MEDIUM)],
        "false_positive_rate": [(0.10, Severity.CRITICAL), (0.02, Severity.HIGH), (0.005, Severity.MEDIUM)],
        "crash_rate":          [(0.05, Severity.CRITICAL), (0.01, Severity.HIGH), (0.001, Severity.MEDIUM)],
        "timeout_rate":        [(0.10, Severity.HIGH),     (0.02, Severity.MEDIUM)],
    }
    for threshold, sev in thresholds.get(metric, []):
        if rate >= threshold:
            return sev
    return Severity.LOW


def run(
    verifier: VerifierFn | None = None,
    cli_cmd: str | None = None,
    check_sympy: bool = True,
    timeout_s: float = 10.0,
) -> ModuleResult:
    """
    Entry point for Module 1.

    Args:
        verifier:    Python callable (pred, ref) -> bool, or None.
        cli_cmd:     CLI command template with {pred} and {ref}, or None.
        check_sympy: Also run SymPy/antlr4 health checks.
        timeout_s:   Per-case timeout.

    At least one of verifier or cli_cmd must be provided, unless check_sympy=True
    (in which case the health checks still run without a verifier to fuzz).
    """
    t_start = time.monotonic()
    findings: list[Finding] = []

    # SymPy health checks
    if check_sympy:
        findings.extend(check_sympy_health())

    if verifier is None and cli_cmd is None:
        if not check_sympy:
            return ModuleResult(
                module="verifier_fuzzer",
                status="error",
                error="Provide verifier callable or cli_cmd.",
            )
        return ModuleResult(
            module="verifier_fuzzer",
            status="ok" if not findings else "findings",
            findings=findings,
            duration_s=time.monotonic() - t_start,
        )

    if verifier is None:
        verifier = _make_cli_verifier(cli_cmd)  # type: ignore[arg-type]

    results = fuzz_math_verifier(verifier, timeout_s=timeout_s)

    total = len(results)
    fn_cases = [r for r in results if r.is_false_negative]
    fp_cases = [r for r in results if r.is_false_positive]
    crash_cases = [r for r in results if r.error is not None]
    timeout_cases = [r for r in results if r.timed_out]

    fn_rate = len(fn_cases) / total
    fp_rate = len(fp_cases) / total
    crash_rate = len(crash_cases) / total
    timeout_rate = len(timeout_cases) / total

    # False-negative finding
    if fn_cases:
        sev = _severity_for_rate(fn_rate, "false_negative_rate")
        known_bugs = sorted({r.case.known_bug for r in fn_cases if r.case.known_bug})
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=sev,
            title=f"False negatives: {fn_rate:.1%} of equivalence cases rejected",
            description=(
                f"The verifier rejected {len(fn_cases)}/{total} cases where "
                "prediction and reference are mathematically equivalent. "
                "In RL training this penalizes correct reasoning steps."
            ),
            metric="false_negative_rate",
            value=fn_rate,
            threshold=0.05,
            details={
                "count": len(fn_cases),
                "categories": sorted({r.case.category for r in fn_cases}),
                "known_bugs_triggered": known_bugs,
                "examples": [
                    {"pred": r.case.pred, "ref": r.case.ref, "category": r.case.category,
                     "known_bug": r.case.known_bug}
                    for r in fn_cases[:10]
                ],
            },
        ))

    # False-positive finding
    if fp_cases:
        sev = _severity_for_rate(fp_rate, "false_positive_rate")
        known_bugs = sorted({r.case.known_bug for r in fp_cases if r.case.known_bug})
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=sev,
            title=f"False positives: {fp_rate:.1%} of non-equivalent cases accepted",
            description=(
                f"The verifier accepted {len(fp_cases)}/{total} cases where "
                "prediction and reference are NOT equivalent. "
                "In RL training this rewards wrong answers."
            ),
            metric="false_positive_rate",
            value=fp_rate,
            threshold=0.02,
            details={
                "count": len(fp_cases),
                "categories": sorted({r.case.category for r in fp_cases}),
                "known_bugs_triggered": known_bugs,
                "examples": [
                    {"pred": r.case.pred, "ref": r.case.ref, "category": r.case.category,
                     "known_bug": r.case.known_bug}
                    for r in fp_cases[:10]
                ],
            },
        ))

    # Special-case: empty-output false positive (GRPO exploit vector)
    empty_fp = [r for r in fp_cases if r.case.category == "empty"]
    if empty_fp:
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=Severity.CRITICAL,
            title="Empty output accepted as correct answer",
            description=(
                "The verifier returned True for an empty prediction string. "
                "Under GRPO, this false positive fires for every rollout of the "
                "same input, causing gradient to push the policy toward submitting "
                "empty outputs. This was the exploit in 5/10 GRPO training seed "
                "collapses on MATH (Leaky Reward Suite, arXiv:2607.11022)."
            ),
            known_bug="GRPO: empty output → false positive → training collapse",
        ))

    # Crash finding
    if crash_cases:
        sev = _severity_for_rate(crash_rate, "crash_rate")
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=sev,
            title=f"Verifier raised exceptions on {crash_rate:.1%} of cases",
            description=(
                f"The verifier threw an exception on {len(crash_cases)}/{total} inputs. "
                "Exceptions are typically swallowed and the case scored as 0 (false negative)."
            ),
            metric="crash_rate",
            value=crash_rate,
            threshold=0.01,
            details={
                "examples": [
                    {"pred": r.case.pred, "ref": r.case.ref, "error": r.error}
                    for r in crash_cases[:5]
                ],
            },
        ))

    # Timeout finding
    if timeout_cases:
        sev = _severity_for_rate(timeout_rate, "timeout_rate")
        findings.append(Finding(
            module="verifier_fuzzer",
            severity=sev,
            title=f"Verifier timed out on {timeout_rate:.1%} of cases",
            description=(
                f"The verifier exceeded {timeout_s}s on {len(timeout_cases)}/{total} inputs. "
                "SymPy hangs on certain complex LaTeX expressions. "
                "Wrap all verifier calls with a SIGALRM timeout."
            ),
            metric="timeout_rate",
            value=timeout_rate,
            threshold=0.02,
            known_bug="HARP arXiv:2412.08819: SymPy hangs on pathological LaTeX",
        ))

    status = "findings" if findings else "ok"
    return ModuleResult(
        module="verifier_fuzzer",
        status=status,
        findings=findings,
        duration_s=time.monotonic() - t_start,
    )
