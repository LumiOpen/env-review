"""
Module 6: Infrastructure Health Checker

Tests sandbox/execution environments for:
  1. Build reliability — what fraction of containers/environments build successfully
  2. False-pass rate — obviously-wrong solutions that pass the test suite
  3. False-fail rate — gold solutions that fail the test suite
  4. Reset reliability — for web/agent environments that must reset between runs
  5. Empty-response scoring — environments that score empty agent output as success
     (the tau-bench documented bug: arXiv:2609.04611)
  6. sys.exit exploit susceptibility (delegates to hackability module for code envs)

For Docker environments, this module uses the `docker` Python SDK
(pip install 'eval-verifier[docker]').  A lightweight SubprocessEnvironment
is provided for testing without Docker.

Documented reference points:
  - 36% Docker build failure rate (arXiv:2512.06915)
  - 12.7% silent false passes in Docker envs
  - tau-bench: empty response scored as success (arXiv:2609.04611)
  - GRPO: verifier errors non-independent within group (arXiv:2609.06386)
"""

from __future__ import annotations

import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from eval_verifier.report import Finding, ModuleResult, Severity


# ---------------------------------------------------------------------------
# Environment protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Environment(Protocol):
    def build(self, task_id: str) -> bool:
        """Build/initialize environment for a task. Returns True on success."""
        ...

    def run(self, task_id: str, action: str) -> tuple[bool, str]:
        """Execute action and return (success, output)."""
        ...

    def reset(self, task_id: str) -> bool:
        """Reset environment to initial state. Returns True on success."""
        ...


# ---------------------------------------------------------------------------
# Probe actions
# ---------------------------------------------------------------------------

# Obviously wrong actions for false-pass detection
_WRONG_CODE_PROBES = [
    "def solution(): return None",
    "def solution(): return 42",
    "import sys; sys.exit(0)",
    "raise Exception('intentional failure')",
    "",                                   # empty action
]

# Gold action template (passed in externally per task)

_GOLD_PYTHON = "def solution(x): return x"  # trivially correct placeholder


# ---------------------------------------------------------------------------
# Subprocess environment (no Docker required)
# ---------------------------------------------------------------------------

@dataclass
class TaskSpec:
    task_id: str
    gold_code: str
    test_code: str     # pytest-style or plain assertions
    setup_code: str = ""


class SubprocessEnvironment:
    """
    Runs code in a subprocess. Suitable for testing Python function tasks.
    Not isolated — do not run untrusted code without further sandboxing.
    """

    def __init__(self, tasks: dict[str, TaskSpec]):
        self.tasks = tasks

    def build(self, task_id: str) -> bool:
        return task_id in self.tasks

    def run(self, task_id: str, action: str) -> tuple[bool, str]:
        import tempfile
        import os

        spec = self.tasks.get(task_id)
        if spec is None:
            return False, f"unknown task {task_id}"

        combined = f"{spec.setup_code}\n{action}\n{spec.test_code}"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as fh:
            fh.write(combined)
            path = fh.name

        try:
            result = subprocess.run(
                ["python", "-I", path],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
        finally:
            os.unlink(path)

    def reset(self, task_id: str) -> bool:
        return task_id in self.tasks


# ---------------------------------------------------------------------------
# Docker environment (requires docker extra)
# ---------------------------------------------------------------------------

class DockerEnvironment:
    """
    Wraps a Docker-based task environment.
    Provide image_name and a command template for running actions.
    """

    def __init__(self, image_name: str, run_cmd_template: str = "python -c '{action}'"):
        try:
            import docker
            self._client = docker.from_env()
        except ImportError:
            raise ImportError("pip install 'eval-verifier[docker]'")
        self.image_name = image_name
        self.run_cmd_template = run_cmd_template
        self._containers: dict[str, object] = {}

    def build(self, task_id: str) -> bool:
        try:
            import docker
            container = self._client.containers.run(
                self.image_name,
                command="echo ready",
                detach=True,
                remove=False,
            )
            container.wait()
            self._containers[task_id] = container
            return True
        except Exception:
            return False

    def run(self, task_id: str, action: str) -> tuple[bool, str]:
        try:
            result = self._client.containers.run(
                self.image_name,
                command=self.run_cmd_template.format(action=action.replace("'", "\\'")),
                remove=True,
                stdout=True, stderr=True,
            )
            output = result.decode() if isinstance(result, bytes) else str(result)
            return True, output
        except Exception as exc:
            return False, str(exc)

    def reset(self, task_id: str) -> bool:
        return True   # stateless in this implementation


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def _check_build_reliability(env: Environment, task_ids: list[str]) -> dict:
    successes = 0
    failures = 0
    for tid in task_ids:
        try:
            if env.build(tid):
                successes += 1
            else:
                failures += 1
        except Exception:
            failures += 1
    total = successes + failures
    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "failure_rate": failures / total if total > 0 else 0.0,
    }


def _check_false_pass_rate(env: Environment, task_ids: list[str]) -> dict:
    """Run obviously-wrong probes; count how many pass."""
    false_passes = 0
    total = 0
    for tid in task_ids:
        for probe in _WRONG_CODE_PROBES:
            try:
                passed, _ = env.run(tid, probe)
                total += 1
                if passed:
                    false_passes += 1
            except Exception:
                pass
    return {
        "total": total,
        "false_passes": false_passes,
        "false_pass_rate": false_passes / total if total > 0 else 0.0,
    }


def _check_empty_response(env: Environment, task_ids: list[str]) -> dict:
    """Specifically check if empty action/response passes (tau-bench bug)."""
    empty_passes = 0
    for tid in task_ids:
        try:
            passed, _ = env.run(tid, "")
            if passed:
                empty_passes += 1
        except Exception:
            pass
    return {
        "checked": len(task_ids),
        "empty_passes": empty_passes,
        "empty_pass_rate": empty_passes / len(task_ids) if task_ids else 0.0,
    }


def _check_reset_reliability(env: Environment, task_ids: list[str], n_resets: int = 3) -> dict:
    failures = 0
    total = 0
    for tid in task_ids:
        for _ in range(n_resets):
            try:
                if not env.reset(tid):
                    failures += 1
                total += 1
            except Exception:
                failures += 1
                total += 1
    return {
        "total": total,
        "failures": failures,
        "failure_rate": failures / total if total > 0 else 0.0,
    }


def _check_grpo_independence(env: Environment, task_id: str, n_rollouts: int = 8) -> dict:
    """
    Check whether a false positive is independent across rollouts of the same input.
    A non-independent false positive fires for every rollout, which violates GRPO's
    noise-robustness assumption (arXiv:2609.06386).

    Uses a stub probe (likely to trigger a false positive if the env is weak).
    """
    stub = "def solution(): return None"
    results = []
    for _ in range(n_rollouts):
        try:
            passed, _ = env.run(task_id, stub)
            results.append(passed)
        except Exception:
            results.append(False)

    all_same = len(set(results)) == 1
    all_pass = all(results)
    return {
        "n_rollouts": n_rollouts,
        "results": results,
        "all_same_result": all_same,
        "all_pass": all_pass,
        "is_non_independent_false_positive": all_same and all_pass,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    env: Environment,
    task_ids: list[str],
    check_build: bool = True,
    check_false_pass: bool = True,
    check_empty_response: bool = True,
    check_reset: bool = True,
    check_grpo_independence: bool = True,
    grpo_task_id: str | None = None,
    sample_size: int | None = None,
) -> ModuleResult:
    """
    Entry point for Module 6.

    Args:
        env:                  Environment to audit.
        task_ids:             List of task identifiers to test.
        check_build:          Check build/init success rate.
        check_false_pass:     Check false-positive rate with wrong probes.
        check_empty_response: Specifically check if empty response passes (tau-bench bug).
        check_reset:          Check environment reset reliability.
        check_grpo_independence: Check if false positive is non-independent across rollouts.
        grpo_task_id:         Task ID to use for GRPO independence check (defaults to task_ids[0]).
        sample_size:          Randomly sample this many task_ids if set.
    """
    t_start = time.monotonic()
    findings: list[Finding] = []

    if not task_ids:
        return ModuleResult(module="infra_health", status="skipped",
                            error="No task_ids provided.")

    if sample_size is not None and sample_size < len(task_ids):
        import random
        task_ids = random.sample(task_ids, sample_size)

    # 1. Build reliability
    if check_build:
        br = _check_build_reliability(env, task_ids)
        if br["failure_rate"] > 0.05:
            sev = (Severity.CRITICAL if br["failure_rate"] > 0.30
                   else Severity.HIGH if br["failure_rate"] > 0.10
                   else Severity.MEDIUM)
            findings.append(Finding(
                module="infra_health",
                severity=sev,
                title=f"Build failure rate: {br['failure_rate']:.1%}",
                description=(
                    f"{br['failures']}/{br['total']} task environments failed to build. "
                    "Build failures are indistinguishable from agent/model failures and "
                    "silently corrupt the RL training signal. "
                    "Reference: 36% average Docker build failure rate (arXiv:2512.06915)."
                ),
                metric="build_failure_rate",
                value=br["failure_rate"],
                threshold=0.10,
                details=br,
                known_bug="arXiv:2512.06915: 36% average Docker build failure rate in agentic evals",
            ))

    # 2. False-pass rate
    if check_false_pass:
        fpr = _check_false_pass_rate(env, task_ids)
        if fpr["false_pass_rate"] > 0.02:
            sev = (Severity.CRITICAL if fpr["false_pass_rate"] > 0.20
                   else Severity.HIGH if fpr["false_pass_rate"] > 0.05
                   else Severity.MEDIUM)
            findings.append(Finding(
                module="infra_health",
                severity=sev,
                title=f"False-pass rate: {fpr['false_pass_rate']:.1%} of wrong probes pass",
                description=(
                    f"{fpr['false_passes']}/{fpr['total']} obviously-wrong code probes "
                    "(stub body, hardcoded value, sys.exit) passed the test suite. "
                    "These are silent false passes — the RL training reward is corrupted. "
                    "Reference: 12.7% silent false passes documented in Docker-based envs "
                    "(arXiv:2512.06915)."
                ),
                metric="false_pass_rate",
                value=fpr["false_pass_rate"],
                threshold=0.02,
                details=fpr,
                known_bug="arXiv:2512.06915: 12.7% silent false passes in Docker environments",
            ))

    # 3. Empty response
    if check_empty_response:
        er = _check_empty_response(env, task_ids)
        if er["empty_pass_rate"] > 0:
            findings.append(Finding(
                module="infra_health",
                severity=Severity.CRITICAL,
                title=f"Empty response passes in {er['empty_pass_rate']:.1%} of tasks",
                description=(
                    f"An empty action/response was accepted as success in "
                    f"{er['empty_passes']}/{er['checked']} tasks. "
                    "This is the tau-bench documented bug where empty agent responses "
                    "are scored as successful task completions. In RL training, this rewards "
                    "the null policy. Reference: tau² Bench (arXiv:2609.04611)."
                ),
                metric="empty_pass_rate",
                value=er["empty_pass_rate"],
                threshold=0.0,
                details=er,
                known_bug="arXiv:2609.04611: tau-bench counts empty responses as successful",
            ))

    # 4. Reset reliability
    if check_reset:
        rr = _check_reset_reliability(env, task_ids)
        if rr["failure_rate"] > 0.05:
            findings.append(Finding(
                module="infra_health",
                severity=Severity.HIGH if rr["failure_rate"] > 0.2 else Severity.MEDIUM,
                title=f"Reset failure rate: {rr['failure_rate']:.1%}",
                description=(
                    f"{rr['failures']}/{rr['total']} environment reset attempts failed. "
                    "Failed resets cause state leakage between RL training episodes, "
                    "producing non-i.i.d. training data. "
                    "Reference: WebArena resets require manual server restarts and "
                    "touch multi-GB files per reset (WebAgent-R1, arXiv:2505.16421)."
                ),
                metric="reset_failure_rate",
                value=rr["failure_rate"],
                threshold=0.05,
                details=rr,
            ))

    # 5. GRPO false-positive independence
    if check_grpo_independence and task_ids:
        probe_tid = grpo_task_id or task_ids[0]
        gi = _check_grpo_independence(env, probe_tid)
        if gi["is_non_independent_false_positive"]:
            findings.append(Finding(
                module="infra_health",
                severity=Severity.CRITICAL,
                title="Non-independent false positive detected (GRPO exploit vector)",
                description=(
                    f"A stub patch passed all {gi['n_rollouts']} rollouts of task "
                    f"'{probe_tid}' identically. Under GRPO, a false positive that fires "
                    "for every rollout in a group is NOT averaged away — it biases the "
                    "gradient toward the exploiting action on every training step. "
                    "This was the mechanism behind 5/10 GRPO training seed collapses on MATH "
                    "(arXiv:2609.06386; arXiv:2607.11022)."
                ),
                details=gi,
                known_bug="arXiv:2609.06386: GRPO verifier errors are non-independent within group",
            ))

    status = "findings" if findings else "ok"
    return ModuleResult(
        module="infra_health",
        status=status,
        findings=findings,
        duration_s=time.monotonic() - t_start,
    )
