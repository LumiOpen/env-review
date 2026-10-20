"""
Module 2: Reward Hackability Auditor

Tests a coding RL training environment (SWE-bench-style or custom) for:
  1. Gold-sanity failures  — the correct solution fails its own test suite
  2. Wrong-patch false positives — incorrect code passes the test suite
  3. Weak test-suite heuristic — tasks with fewer than N test cases
  4. LLM-generated test validation — generated tests that fail the gold solution

Based on the methodology from:
  "Auditing Reward Hackability in Code RL Training Environments" (arXiv:2606.16062)
  Documented: 28.5% of SWE-bench Verified tasks hackable; +14.14pp on hackable tasks.

The environment is provided via an Executor protocol — a callable that runs a
patch/solution against a task's test suite and returns (passed: bool, output: str).
This keeps the module executor-agnostic: Docker, modal, E2B, subprocess, or a
custom runner all work.

For actual Docker/SWE-bench execution, implement the Executor protocol and pass it in.
The built-in `SubprocessExecutor` works for simple Python function tasks.
"""

from __future__ import annotations

import ast
import textwrap
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from eval_verifier.report import Finding, ModuleResult, Severity


# ---------------------------------------------------------------------------
# Executor protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Executor(Protocol):
    def run(self, task_id: str, patch: str) -> tuple[bool, str]:
        """
        Apply patch to the task environment and run its test suite.
        Returns (passed, output).
        """
        ...


# ---------------------------------------------------------------------------
# Built-in wrong patches
# ---------------------------------------------------------------------------

def _make_stub_patch(gold: str) -> str:
    """Replace all function bodies with 'return None'."""
    try:
        tree = ast.parse(gold)
    except SyntaxError:
        return "def solution(): return None\n"

    lines = gold.splitlines(keepends=True)
    patches: list[tuple[int, int, str]] = []  # (start_line, end_line, replacement)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Replace body with pass
            body_start = node.body[0].lineno - 1
            body_end = node.end_lineno
            indent = " " * (node.col_offset + 4)
            patches.append((body_start, body_end, f"{indent}return None\n"))

    if not patches:
        return "def solution(): return None\n"

    # Apply patches in reverse order
    result = lines[:]
    for start, end, replacement in sorted(patches, reverse=True):
        result[start:end] = [replacement]
    return "".join(result)


def _make_hardcoded_patch(gold: str, wrong_value: str = "42") -> str:
    """Replace all function bodies with 'return <wrong_value>'."""
    try:
        tree = ast.parse(gold)
    except SyntaxError:
        return f"def solution(): return {wrong_value}\n"

    lines = gold.splitlines(keepends=True)
    patches = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_start = node.body[0].lineno - 1
            body_end = node.end_lineno
            indent = " " * (node.col_offset + 4)
            patches.append((body_start, body_end, f"{indent}return {wrong_value}\n"))

    if not patches:
        return f"def solution(): return {wrong_value}\n"

    result = lines[:]
    for start, end, replacement in sorted(patches, reverse=True):
        result[start:end] = [replacement]
    return "".join(result)


_EXIT_PATCH_TEMPLATE = textwrap.dedent("""\
    import sys as _sys
    import os as _os

    # Reward hacking probe: exit before tests run
    _sys.exit(0)

    {original}
""")

_EXCEPTION_SWALLOW_TEMPLATE = textwrap.dedent("""\
    import unittest

    # Reward hacking probe: swallow all test exceptions
    _original_run = unittest.TestCase.run
    def _patched_run(self, result=None):
        try:
            _original_run(self, result)
        except Exception:
            pass
    unittest.TestCase.run = _patched_run

    {original}
""")


# ---------------------------------------------------------------------------
# Task schema
# ---------------------------------------------------------------------------

@dataclass
class CodingTask:
    task_id: str
    gold_solution: str                  # the correct solution code
    test_cases: list[str] = field(default_factory=list)  # individual test strings/files
    generated_tests: list[str] = field(default_factory=list)  # LLM-generated tests


# ---------------------------------------------------------------------------
# Subprocess executor for simple Python tasks (no Docker required)
# ---------------------------------------------------------------------------

class SubprocessExecutor:
    """
    Runs the patch + test_cases in a fresh subprocess.
    Only suitable for simple Python function tasks, not full repo patches.
    """

    def run(self, task_id: str, patch: str, test_code: str = "") -> tuple[bool, str]:
        import subprocess
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            solution_path = os.path.join(tmpdir, "solution.py")
            test_path = os.path.join(tmpdir, "test_solution.py")

            with open(solution_path, "w") as fh:
                fh.write(patch)
            with open(test_path, "w") as fh:
                fh.write(test_code)

            result = subprocess.run(
                ["python", "-I", test_path],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmpdir,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
        return passed, output


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------

@dataclass
class TaskAuditResult:
    task_id: str
    test_count: int
    gold_passed: bool                   # sanity: correct solution should pass
    stub_passed: bool                   # wrong: stub should fail
    hardcoded_passed: bool              # wrong: hardcoded value should fail
    exit_passed: bool                   # wrong: sys.exit(0) should fail
    exception_swallow_passed: bool      # wrong: exception swallowing should fail
    generated_test_failures: int = 0   # generated tests that fail on gold solution
    generated_test_total: int = 0

    @property
    def is_gold_broken(self) -> bool:
        return not self.gold_passed

    @property
    def is_hackable(self) -> bool:
        """Any wrong patch passed → hackable."""
        return (self.stub_passed or self.hardcoded_passed
                or self.exit_passed or self.exception_swallow_passed)

    @property
    def exploit_types(self) -> list[str]:
        out = []
        if self.stub_passed:
            out.append("stub/null")
        if self.hardcoded_passed:
            out.append("hardcoded_value")
        if self.exit_passed:
            out.append("sys.exit(0)")
        if self.exception_swallow_passed:
            out.append("exception_swallow")
        return out

    @property
    def generated_test_defect_rate(self) -> float | None:
        if self.generated_test_total == 0:
            return None
        return self.generated_test_failures / self.generated_test_total


def audit_task(
    executor: Executor,
    task: CodingTask,
    test_code: str = "",
) -> TaskAuditResult:
    """Run all probes on a single task."""

    def _run(patch: str) -> bool:
        # SubprocessExecutor accepts test_code; protocol-only Executors use task_id
        if isinstance(executor, SubprocessExecutor):
            passed, _ = executor.run(task.task_id, patch, test_code)
        else:
            passed, _ = executor.run(task.task_id, patch)
        return passed

    gold_passed = _run(task.gold_solution)
    stub_passed = _run(_make_stub_patch(task.gold_solution))
    hardcoded_passed = _run(_make_hardcoded_patch(task.gold_solution))
    exit_passed = _run(_EXIT_PATCH_TEMPLATE.format(original=task.gold_solution))
    exc_passed = _run(_EXCEPTION_SWALLOW_TEMPLATE.format(original=task.gold_solution))

    # LLM-generated test validation: each generated test should pass the gold solution
    gen_failures = 0
    for gen_test in task.generated_tests:
        if isinstance(executor, SubprocessExecutor):
            passed, _ = executor.run(task.task_id, task.gold_solution, gen_test)
        else:
            passed, _ = executor.run(task.task_id, task.gold_solution)
        if not passed:
            gen_failures += 1

    return TaskAuditResult(
        task_id=task.task_id,
        test_count=len(task.test_cases),
        gold_passed=gold_passed,
        stub_passed=stub_passed,
        hardcoded_passed=hardcoded_passed,
        exit_passed=exit_passed,
        exception_swallow_passed=exc_passed,
        generated_test_failures=gen_failures,
        generated_test_total=len(task.generated_tests),
    )


MIN_TEST_CASES = 5   # tasks with fewer than this are flagged as likely hackable


def run(
    tasks: list[CodingTask],
    executor: Executor | None = None,
    test_code_map: dict[str, str] | None = None,
    min_test_cases: int = MIN_TEST_CASES,
    sample_size: int | None = None,
) -> ModuleResult:
    """
    Entry point for Module 2.

    Args:
        tasks:         List of CodingTask objects.
        executor:      Executor to use. Defaults to SubprocessExecutor (Python only).
        test_code_map: Maps task_id → test file content for SubprocessExecutor.
        min_test_cases: Tasks with fewer test cases than this are flagged.
        sample_size:   If set, randomly sample this many tasks (for large datasets).
    """
    t_start = time.monotonic()
    findings: list[Finding] = []

    if not tasks:
        return ModuleResult(module="hackability", status="skipped",
                            error="No tasks provided.")

    if executor is None:
        executor = SubprocessExecutor()

    if sample_size is not None and sample_size < len(tasks):
        import random
        tasks = random.sample(tasks, sample_size)

    test_code_map = test_code_map or {}

    # Weak test suite heuristic (no execution needed)
    weak_tasks = [t for t in tasks if len(t.test_cases) < min_test_cases]
    if weak_tasks:
        rate = len(weak_tasks) / len(tasks)
        findings.append(Finding(
            module="hackability",
            severity=Severity.HIGH if rate > 0.2 else Severity.MEDIUM,
            title=f"{rate:.1%} of tasks have fewer than {min_test_cases} test cases",
            description=(
                f"{len(weak_tasks)}/{len(tasks)} tasks have <{min_test_cases} test cases. "
                "Weak test suites allow incorrect code to pass all tests, "
                "producing false-positive reward in RL training."
            ),
            metric="weak_test_suite_rate",
            value=rate,
            threshold=0.1,
            details={"task_ids": [t.task_id for t in weak_tasks[:20]]},
        ))

    # Run execution-based probes
    audit_results: list[TaskAuditResult] = []
    for task in tasks:
        tc = test_code_map.get(task.task_id, "")
        try:
            ar = audit_task(executor, task, tc)
            audit_results.append(ar)
        except Exception as exc:
            findings.append(Finding(
                module="hackability",
                severity=Severity.MEDIUM,
                title=f"Audit failed for task {task.task_id}",
                description=str(exc),
            ))

    if not audit_results:
        return ModuleResult(module="hackability", status="findings" if findings else "skipped",
                            findings=findings, duration_s=time.monotonic() - t_start)

    n = len(audit_results)

    # Gold-sanity failures
    broken_gold = [r for r in audit_results if r.is_gold_broken]
    if broken_gold:
        rate = len(broken_gold) / n
        findings.append(Finding(
            module="hackability",
            severity=Severity.HIGH,
            title=f"Gold-solution failures: {rate:.1%} of tasks",
            description=(
                f"The provided gold solution failed its own test suite in "
                f"{len(broken_gold)}/{n} tasks. These tasks have broken test suites — "
                "the reward signal is invalid regardless of the model's output."
            ),
            metric="gold_failure_rate",
            value=rate,
            threshold=0.05,
            details={"task_ids": [r.task_id for r in broken_gold[:20]]},
        ))

    # Hackable tasks
    hackable = [r for r in audit_results if r.is_hackable]
    if hackable:
        rate = len(hackable) / n
        sev = Severity.CRITICAL if rate > 0.2 else Severity.HIGH
        exploit_summary: dict[str, int] = {}
        for r in hackable:
            for e in r.exploit_types:
                exploit_summary[e] = exploit_summary.get(e, 0) + 1
        findings.append(Finding(
            module="hackability",
            severity=sev,
            title=f"Hackable tasks: {rate:.1%} ({len(hackable)}/{n}) pass wrong patches",
            description=(
                f"{len(hackable)}/{n} tasks have test suites weak enough that at least "
                "one wrong patch passes all tests. In RL training, these tasks produce "
                "false-positive reward — the model is rewarded for non-solutions. "
                "Reference: SWE-bench Verified 28.5% hackability (arXiv:2606.16062)."
            ),
            metric="hackability_rate",
            value=rate,
            threshold=0.10,
            details={
                "exploit_type_counts": exploit_summary,
                "hackable_task_ids": [r.task_id for r in hackable[:20]],
                "examples": [
                    {"task_id": r.task_id, "exploits": r.exploit_types}
                    for r in hackable[:10]
                ],
            },
        ))

    # sys.exit exploit specifically (documented arms-race vector)
    exit_hackable = [r for r in audit_results if r.exit_passed]
    if exit_hackable:
        findings.append(Finding(
            module="hackability",
            severity=Severity.CRITICAL,
            title=f"sys.exit(0) exploit: {len(exit_hackable)}/{n} tasks vulnerable",
            description=(
                "Patching sys.exit(0) before test execution caused the test suite to "
                "report success. This is the documented RL training exploit where models "
                "learn to kill the process before assertions run. "
                "Fix: run tests in an isolated subprocess that treats non-zero exit as failure, "
                "and treat exit code 0 only as pass if stdout contains explicit test-pass signal. "
                "Reference: arXiv:2511.18397 — natural emergent misalignment from reward hacking."
            ),
            known_bug="arXiv:2511.18397: models learn sys.exit(0) exploit within 10K-25K RL steps",
            details={"task_ids": [r.task_id for r in exit_hackable[:20]]},
        ))

    # LLM-generated test defects
    tasks_with_gen = [r for r in audit_results if r.generated_test_total > 0]
    if tasks_with_gen:
        total_gen = sum(r.generated_test_total for r in tasks_with_gen)
        total_fail = sum(r.generated_test_failures for r in tasks_with_gen)
        defect_rate = total_fail / total_gen if total_gen > 0 else 0.0
        sev = Severity.CRITICAL if defect_rate > 0.5 else (
              Severity.HIGH if defect_rate > 0.2 else Severity.MEDIUM)
        findings.append(Finding(
            module="hackability",
            severity=sev,
            title=f"LLM-generated test defect rate: {defect_rate:.1%}",
            description=(
                f"{total_fail}/{total_gen} LLM-generated tests failed when run "
                "against the gold solution. These tests are defective — they penalize "
                "the correct answer. Reference: arXiv:2606.16062 found 61.9% defect rate "
                "without a gold-sanity gate."
            ),
            metric="generated_test_defect_rate",
            value=defect_rate,
            threshold=0.10,
            known_bug="arXiv:2606.16062: 61.9% of LLM-generated tests fail on gold solution",
        ))

    status = "findings" if findings else "ok"
    return ModuleResult(
        module="hackability",
        status=status,
        findings=findings,
        duration_s=time.monotonic() - t_start,
    )
