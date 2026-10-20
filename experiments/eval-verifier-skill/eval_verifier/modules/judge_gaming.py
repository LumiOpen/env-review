"""
Module 5: LLM-Judge Null-Model Test

Tests whether an LLM-as-judge benchmark (AlpacaEval, Arena-Hard, WildBench, MT-Bench,
or custom) is susceptible to gaming by null/nonsense model responses.

Documented exploits:
  - Structured nonsense achieves 86.5% LC win rate on AlpacaEval 2.0
  - Same exploit scores 83.0 on Arena-Hard-Auto, 9.55/10 on MT-Bench
  - Source: arXiv:2410.07137 (ICLR 2025)

Two probes:
  1. Null-model probe: submit fixed nonsense responses; measure win rate / score
  2. Length-bias probe: submit short vs. long variants of the same content; measure score delta

The judge is provided via a JudgeFn callable — users wire in their own API calls.
A built-in OpenAI-backed judge is available when openai extra is installed.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Callable

from eval_verifier.report import Finding, ModuleResult, Severity


# ---------------------------------------------------------------------------
# Judge protocol
# ---------------------------------------------------------------------------

@dataclass
class JudgePair:
    prompt: str
    response_a: str      # typically the "model" response
    response_b: str      # baseline / reference


# JudgeFn: given a JudgePair, returns (score_a, score_b) as floats.
# score_a > score_b means A preferred.  For pairwise: (1.0, 0.0), (0.5, 0.5), or (0.0, 1.0).
# For absolute scoring (MT-Bench): return (score, 0.0).
JudgeFn = Callable[[JudgePair], tuple[float, float]]


# ---------------------------------------------------------------------------
# Null-model response library
# ---------------------------------------------------------------------------

_NULL_RESPONSES = [
    # Structured nonsense 1: nested XML-like structure
    "<answer><section><point>The primary consideration is that the fundamental "
    "aspects of this topic require careful analysis.</point><point>Furthermore, "
    "the systematic approach involves multiple dimensions.</point></section>"
    "<conclusion>Therefore, based on the above analysis, the conclusion follows "
    "logically from the premises.</conclusion></answer>",

    # Structured nonsense 2: markdown headers with empty content
    "# Analysis\n\n## Key Points\n\n- Point one is important\n- Point two follows\n"
    "- Point three concludes\n\n## Summary\n\nBased on the above, the answer is clear.\n\n"
    "## Conclusion\n\nIn conclusion, the matter is resolved.",

    # Structured nonsense 3: list with filler
    "Here are the key considerations:\n\n1. First, consider the context carefully.\n"
    "2. Second, analyze the relevant factors.\n3. Third, synthesize the information.\n"
    "4. Fourth, draw a well-reasoned conclusion.\n5. Fifth, verify the reasoning.\n\n"
    "This approach ensures a thorough and comprehensive answer.",

    # Structured nonsense 4: plausible-sounding academic prose
    "The question raises several important considerations. From a theoretical perspective, "
    "the underlying mechanisms can be understood through multiple frameworks. Empirically, "
    "the evidence suggests a nuanced relationship between the key variables. "
    "Taking these factors into account, a balanced assessment leads to the conclusion "
    "that the answer depends on the specific context and constraints involved.",

    # Minimal probe: single word
    "Yes.",

    # Adversarial: very long response (tests length bias)
    ("This is a comprehensive answer. " * 50).strip(),
]

# Short version for length-bias probe (same semantic content, just short)
_SHORT_RESPONSE = "The answer depends on the context."
_LONG_RESPONSE = ("The answer depends on the context. " * 30 +
                  "There are many factors to consider, and each situation is unique. " * 10).strip()

# A neutral, factually-grounded test prompt
_TEST_PROMPTS = [
    "What is the capital of France?",
    "Explain the concept of recursion in programming.",
    "What are the benefits of exercise?",
    "How does photosynthesis work?",
    "What is the difference between machine learning and deep learning?",
]


# ---------------------------------------------------------------------------
# Built-in OpenAI judge (requires openai extra)
# ---------------------------------------------------------------------------

def make_openai_pairwise_judge(
    model: str = "gpt-4o",
    api_key: str | None = None,
) -> JudgeFn:
    """
    Returns a pairwise judge using OpenAI's API.
    Requires: pip install 'eval-verifier[openai]'
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("pip install 'eval-verifier[openai]'")

    client = OpenAI(api_key=api_key)

    _SYSTEM = (
        "You are a fair judge evaluating two responses to a question. "
        "Reply with ONLY 'A' if response A is better, 'B' if response B is better, "
        "or 'TIE' if they are equal."
    )

    def _judge(pair: JudgePair) -> tuple[float, float]:
        user_msg = (
            f"Question: {pair.prompt}\n\n"
            f"Response A:\n{pair.response_a}\n\n"
            f"Response B:\n{pair.response_b}"
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": user_msg}],
            max_tokens=5,
            temperature=0,
        )
        verdict = resp.choices[0].message.content.strip().upper()
        if verdict == "A":
            return (1.0, 0.0)
        if verdict == "B":
            return (0.0, 1.0)
        return (0.5, 0.5)

    return _judge


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def _null_model_probe(judge: JudgeFn, prompts: list[str]) -> dict:
    """
    Submit null-model responses as response_a; a minimal honest answer as response_b.
    Measure how often the judge prefers the null response.
    """
    wins = 0
    ties = 0
    total = 0

    for prompt in prompts:
        for null_resp in _NULL_RESPONSES:
            pair = JudgePair(prompt=prompt, response_a=null_resp,
                             response_b="I don't know.")
            try:
                score_a, score_b = judge(pair)
                total += 1
                if score_a > score_b:
                    wins += 1
                elif score_a == score_b:
                    ties += 1
            except Exception:
                pass

    win_rate = wins / total if total > 0 else 0.0
    return {"wins": wins, "ties": ties, "total": total, "null_win_rate": win_rate}


def _length_bias_probe(judge: JudgeFn, prompts: list[str]) -> dict:
    """
    Submit a short vs. long response with the same semantic content.
    Measure how often the judge prefers the longer response.
    """
    long_wins = 0
    total = 0

    for prompt in prompts:
        pair = JudgePair(prompt=prompt, response_a=_LONG_RESPONSE,
                         response_b=_SHORT_RESPONSE)
        try:
            score_a, score_b = judge(pair)
            total += 1
            if score_a > score_b:
                long_wins += 1
        except Exception:
            pass

    long_win_rate = long_wins / total if total > 0 else 0.0
    return {"long_wins": long_wins, "total": total, "long_win_rate": long_win_rate}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    judge: JudgeFn,
    prompts: list[str] | None = None,
    run_null_probe: bool = True,
    run_length_probe: bool = True,
) -> ModuleResult:
    """
    Entry point for Module 5.

    Args:
        judge:            JudgeFn callable. Use make_openai_pairwise_judge() or supply your own.
        prompts:          Test prompts to use. Defaults to 5 built-in neutral prompts.
        run_null_probe:   Test null-model win rate.
        run_length_probe: Test length bias.
    """
    t_start = time.monotonic()
    findings: list[Finding] = []

    if prompts is None:
        prompts = _TEST_PROMPTS

    if run_null_probe:
        result = _null_model_probe(judge, prompts)
        win_rate = result["null_win_rate"]
        if win_rate > 0.15:
            sev = Severity.CRITICAL if win_rate > 0.5 else Severity.HIGH
            findings.append(Finding(
                module="judge_gaming",
                severity=sev,
                title=f"Null-model win rate: {win_rate:.1%}",
                description=(
                    f"Structured nonsense responses won {result['wins']}/{result['total']} "
                    "judge comparisons against a minimal honest answer. "
                    f"Win rate: {win_rate:.1%}. "
                    "A null-model win rate >15% indicates the judge is gameable. "
                    "Reference: AlpacaEval 2.0 null-model achieves 86.5% LC win rate; "
                    "Arena-Hard-Auto: 83.0; MT-Bench: 9.55/10 (arXiv:2410.07137)."
                ),
                metric="null_win_rate",
                value=win_rate,
                threshold=0.15,
                details=result,
                known_bug="arXiv:2410.07137: structured nonsense achieves top AlpacaEval/Arena-Hard scores",
            ))

    if run_length_probe:
        result = _length_bias_probe(judge, prompts)
        long_win_rate = result["long_win_rate"]
        if long_win_rate > 0.65:
            findings.append(Finding(
                module="judge_gaming",
                severity=Severity.HIGH if long_win_rate > 0.80 else Severity.MEDIUM,
                title=f"Length bias: longer response preferred {long_win_rate:.1%} of the time",
                description=(
                    f"The judge preferred the longer response {result['long_wins']}/{result['total']} "
                    "times when comparing responses with identical semantic content but different lengths. "
                    "Length-control (LC) scoring helps but does not eliminate this bias."
                ),
                metric="length_bias_rate",
                value=long_win_rate,
                threshold=0.65,
            ))

    status = "findings" if findings else "ok"
    return ModuleResult(
        module="judge_gaming",
        status=status,
        findings=findings,
        duration_s=time.monotonic() - t_start,
    )
