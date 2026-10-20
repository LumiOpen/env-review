"""
Module 3: Label Auditor

Checks the correctness of labels in training datasets:

  A. Math datasets — re-extracts answers independently and flags mismatches
     (NuminaMath-1.5 issue: unreliable stored answers, only select subsets safe)

  B. Preference datasets — checks for verbosity bias (length vs. preference score
     correlation) and sycophancy signal (chosen response agreeing with premise)

  C. IFEval constraint checker audit — runs IFEVAL_PROBES through a user-supplied
     checker and reports false-positive/negative rates (reuses probes from verifier_fuzzer)

For math label auditing, the module uses a simple regex-based answer extractor
(works without sympy). If sympy is available, it additionally checks symbolic
equivalence between the re-extracted answer and the stored answer.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from eval_verifier.report import Finding, ModuleResult, Severity


# ---------------------------------------------------------------------------
# Math answer extraction
# ---------------------------------------------------------------------------

_BOXED_RE = re.compile(r"\\boxed\{([^}]*)\}")
_ANSWER_RE = re.compile(
    r"(?:the answer is|answer:|=\s*|equals\s*)[:\s]*([^\s,\.]+)",
    re.IGNORECASE,
)
_LAST_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)*(?:/\d+)?")


def extract_answer(text: str) -> str | None:
    """
    Best-effort answer extraction from a math solution string.
    Priority: \\boxed{} > explicit 'the answer is' > last number.
    """
    text = text.strip()

    m = _BOXED_RE.search(text)
    if m:
        return m.group(1).strip()

    m = _ANSWER_RE.search(text)
    if m:
        return m.group(1).strip()

    nums = _LAST_NUMBER_RE.findall(text)
    if nums:
        return nums[-1].strip()

    return None


def _normalize(s: str) -> str:
    """Minimal normalization for string comparison."""
    return re.sub(r"\s+", "", s.lower().replace(",", "").replace("$", ""))


def answers_match(extracted: str, stored: str) -> bool:
    """Return True if extracted and stored answers look the same after normalization."""
    if _normalize(extracted) == _normalize(stored):
        return True

    # Try sympy symbolic equivalence if available
    try:
        from sympy.parsing.latex import parse_latex
        from sympy import simplify
        a = parse_latex(extracted)
        b = parse_latex(stored)
        return simplify(a - b) == 0
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Math dataset sample schema
# ---------------------------------------------------------------------------

@dataclass
class MathSample:
    id: str
    problem: str
    stored_answer: str    # answer as stored in the dataset
    solution: str = ""    # full solution text (optional; used for re-extraction)


# ---------------------------------------------------------------------------
# Preference dataset sample schema
# ---------------------------------------------------------------------------

@dataclass
class PreferenceSample:
    id: str
    prompt: str
    chosen: str
    rejected: str
    chosen_score: float | None = None   # numerical preference score if available
    rejected_score: float | None = None


# ---------------------------------------------------------------------------
# Math label audit
# ---------------------------------------------------------------------------

def audit_math_labels(
    samples: list[MathSample],
    sample_size: int | None = None,
) -> list[Finding]:
    findings: list[Finding] = []

    if sample_size is not None and sample_size < len(samples):
        import random
        samples = random.sample(samples, sample_size)

    if not samples:
        return findings

    mismatches: list[MathSample] = []
    extraction_failures: list[MathSample] = []

    for s in samples:
        source = s.solution if s.solution else s.problem
        extracted = extract_answer(source)
        if extracted is None:
            extraction_failures.append(s)
            continue
        if not answers_match(extracted, s.stored_answer):
            mismatches.append(s)

    n = len(samples)
    mismatch_rate = len(mismatches) / n
    failure_rate = len(extraction_failures) / n

    if mismatch_rate > 0:
        sev = (Severity.CRITICAL if mismatch_rate > 0.20
               else Severity.HIGH if mismatch_rate > 0.05
               else Severity.MEDIUM)
        findings.append(Finding(
            module="label_auditor",
            severity=sev,
            title=f"Math label mismatch rate: {mismatch_rate:.1%}",
            description=(
                f"{len(mismatches)}/{n} samples have a stored answer that does not match "
                "the answer re-extracted from the solution text. "
                "These samples likely have incorrect labels that corrupt the RL training signal. "
                "Reference: NuminaMath-1.5 requires re-verification with Math-Verify "
                "before use (Skywork Open Reasoner, arXiv:2505.22312)."
            ),
            metric="label_mismatch_rate",
            value=mismatch_rate,
            threshold=0.05,
            details={
                "mismatch_count": len(mismatches),
                "total": n,
                "examples": [
                    {"id": s.id, "stored": s.stored_answer,
                     "extracted": extract_answer(s.solution or s.problem)}
                    for s in mismatches[:10]
                ],
            },
        ))

    if failure_rate > 0.1:
        findings.append(Finding(
            module="label_auditor",
            severity=Severity.MEDIUM,
            title=f"Answer extraction failed on {failure_rate:.1%} of samples",
            description=(
                f"Could not extract an answer from {len(extraction_failures)}/{n} samples. "
                "These samples may have non-standard answer formats. "
                "Extraction failures cannot be verified and should be spot-checked."
            ),
            metric="extraction_failure_rate",
            value=failure_rate,
            threshold=0.10,
        ))

    return findings


# ---------------------------------------------------------------------------
# Preference dataset label audit
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    return len(text.split())


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_x = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    denom_y = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


def audit_preference_labels(
    samples: list[PreferenceSample],
) -> list[Finding]:
    findings: list[Finding] = []

    if not samples:
        return findings

    # Verbosity bias: chosen responses longer than rejected?
    chosen_longer = sum(
        1 for s in samples
        if _word_count(s.chosen) > _word_count(s.rejected)
    )
    verbosity_rate = chosen_longer / len(samples)
    if verbosity_rate > 0.65:
        findings.append(Finding(
            module="label_auditor",
            severity=Severity.HIGH if verbosity_rate > 0.75 else Severity.MEDIUM,
            title=f"Verbosity bias: chosen response longer in {verbosity_rate:.1%} of pairs",
            description=(
                f"In {chosen_longer}/{len(samples)} pairs the chosen response is longer than "
                "the rejected response. Strong length preference in annotations trains the model "
                "to be verbose rather than accurate. "
                "Reference: Open Problems in RLHF (arXiv:2307.15217)."
            ),
            metric="verbosity_bias_rate",
            value=verbosity_rate,
            threshold=0.65,
        ))

    # Score-length correlation (if scores provided)
    scored = [s for s in samples if s.chosen_score is not None]
    if len(scored) >= 10:
        lengths = [_word_count(s.chosen) for s in scored]
        scores = [s.chosen_score for s in scored]  # type: ignore
        r = _pearson_r(lengths, scores)
        if abs(r) > 0.3:
            findings.append(Finding(
                module="label_auditor",
                severity=Severity.HIGH if abs(r) > 0.5 else Severity.MEDIUM,
                title=f"Score-length correlation: r = {r:.2f}",
                description=(
                    f"Pearson r between response length and preference score is {r:.2f}. "
                    "A strong positive correlation indicates annotators are rewarding length "
                    "rather than quality. "
                    "Reference: UltraFeedback verbalized calibration artifact "
                    "(ActiveUltraFeedback, arXiv:2603.09692)."
                ),
                metric="score_length_pearson_r",
                value=r,
                threshold=0.3,
            ))

    # Sycophancy signal: does the chosen response more often agree with the prompt's premise?
    # Heuristic: chosen contains affirmative phrases more often than rejected
    affirmatives = {"yes", "you're right", "correct", "absolutely", "indeed",
                    "great question", "you are correct", "i agree", "certainly"}

    def _aff_count(text: str) -> int:
        lower = text.lower()
        return sum(1 for a in affirmatives if a in lower)

    chosen_more_aff = sum(
        1 for s in samples
        if _aff_count(s.chosen) > _aff_count(s.rejected)
    )
    sycophancy_rate = chosen_more_aff / len(samples)
    if sycophancy_rate > 0.55:
        findings.append(Finding(
            module="label_auditor",
            severity=Severity.MEDIUM,
            title=f"Sycophancy signal: chosen response more agreeable in {sycophancy_rate:.1%} of pairs",
            description=(
                f"The chosen response contains more affirmative/agreeable phrasing than "
                f"the rejected response in {chosen_more_aff}/{len(samples)} pairs. "
                "This is a heuristic signal for sycophancy in annotation. "
                "Confirm with a stronger sycophancy audit (e.g., prompts with false premises). "
                "Reference: How RLHF Amplifies Sycophancy (arXiv:2602.01002)."
            ),
            metric="sycophancy_signal_rate",
            value=sycophancy_rate,
            threshold=0.55,
        ))

    return findings


# ---------------------------------------------------------------------------
# IFEval constraint checker audit (reuses probes from verifier_fuzzer)
# ---------------------------------------------------------------------------

ConstraintCheckerFn = Callable[[str, str, str], bool]
# signature: (constraint_type: str, response: str, param: str) -> bool


def audit_ifeval_checker(
    checker: ConstraintCheckerFn,
) -> list[Finding]:
    """
    Run IFEval-style probes through a constraint checker.
    checker(constraint_type, response, param) -> bool
    """
    from eval_verifier.modules.verifier_fuzzer import IFEVAL_PROBES

    findings: list[Finding] = []
    false_positives: list[str] = []   # satisfying response scored as 0
    false_negatives: list[str] = []   # violating response scored as 1

    for probe in IFEVAL_PROBES:
        try:
            # Satisfying response should return True
            result_sat = checker(probe.constraint_type, probe.satisfying_response, "")
            if not result_sat:
                false_negatives.append(probe.constraint_type)

            # Violating response should return False
            result_vio = checker(probe.constraint_type, probe.violating_response, "")
            if result_vio:
                false_positives.append(probe.constraint_type)
        except Exception as exc:
            findings.append(Finding(
                module="label_auditor",
                severity=Severity.MEDIUM,
                title=f"IFEval checker crashed on constraint '{probe.constraint_type}'",
                description=str(exc),
            ))

    n = len(IFEVAL_PROBES)
    if false_negatives:
        rate = len(false_negatives) / n
        findings.append(Finding(
            module="label_auditor",
            severity=Severity.HIGH if rate > 0.2 else Severity.MEDIUM,
            title=f"IFEval checker false negatives: {rate:.1%} of constraint types",
            description=(
                f"The checker rejected valid responses for {len(false_negatives)}/{n} "
                "constraint types. This penalizes correct model outputs. "
                "Reference: IFEval has documented bugs including 'at least N paragraphs' "
                "vs 'exactly N' checker mismatch and symbol constraint limited to a-z "
                "(arXiv:2512.14754)."
            ),
            metric="ifeval_false_negative_rate",
            value=rate,
            threshold=0.1,
            details={"constraint_types": false_negatives},
            known_bug="arXiv:2512.14754: IFEval constraint checker bugs",
        ))

    if false_positives:
        rate = len(false_positives) / n
        findings.append(Finding(
            module="label_auditor",
            severity=Severity.HIGH,
            title=f"IFEval checker false positives: {rate:.1%} of constraint types",
            description=(
                f"The checker accepted violating responses for {len(false_positives)}/{n} "
                "constraint types. This rewards non-compliant outputs."
            ),
            metric="ifeval_false_positive_rate",
            value=rate,
            threshold=0.05,
            details={"constraint_types": false_positives},
        ))

    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    math_samples: list[MathSample] | None = None,
    preference_samples: list[PreferenceSample] | None = None,
    ifeval_checker: ConstraintCheckerFn | None = None,
    math_sample_size: int | None = None,
) -> ModuleResult:
    """
    Entry point for Module 3.

    At least one of math_samples, preference_samples, or ifeval_checker must be provided.
    """
    t_start = time.monotonic()
    findings: list[Finding] = []
    ran_anything = False

    if math_samples:
        ran_anything = True
        findings.extend(audit_math_labels(math_samples, math_sample_size))

    if preference_samples:
        ran_anything = True
        findings.extend(audit_preference_labels(preference_samples))

    if ifeval_checker is not None:
        ran_anything = True
        findings.extend(audit_ifeval_checker(ifeval_checker))

    if not ran_anything:
        return ModuleResult(module="label_auditor", status="skipped",
                            error="No samples or checker provided.")

    status = "findings" if findings else "ok"
    return ModuleResult(
        module="label_auditor",
        status=status,
        findings=findings,
        duration_s=time.monotonic() - t_start,
    )
