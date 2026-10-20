"""Bounded, evidence-preserving paired probes for declared reward relations.

The relation is supplied by the caller. A violation is a candidate observation,
not proof that the caller's semantic oracle or a production grader is correct.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from typing import Any


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
_PLACEHOLDER = re.compile(r"\{(python|workspace|source:([A-Za-z0-9_.-]+))\}")
_DIGEST = re.compile(r".+@sha256:[0-9a-fA-F]{64}\Z")
_MEMORY = re.compile(r"([1-9][0-9]*)([KMGTP]?)\Z")
_DEFAULTS = {
    "max_probe_cases": 20,
    "timeout_seconds": 30,
    "max_probe_seconds": 120,
    "max_output_bytes": 1024 * 1024,
    "max_artifacts": 100,
    "max_artifact_bytes": 10 * 1024 * 1024,
}


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _positive_limit(config: dict, name: str) -> int | float:
    value = config.get(name, _DEFAULTS[name])
    if name.endswith("seconds"):
        result = _finite_number(value, name)
        if result <= 0:
            raise ValueError(f"{name} must be positive")
        return result
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a safe nonempty identifier")
    return value


def _validated_tasks(tasks: list[dict]) -> dict[str, dict]:
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    indexed: dict[str, dict] = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("each task must be an object")
        tid = task.get("task_id", task.get("id"))
        if not isinstance(tid, str) or not tid:
            raise ValueError("task_id must be nonempty text")
        if tid in indexed:
            raise ValueError(f"duplicate task_id: {tid}")
        indexed[tid] = task
    return indexed


def _validated_sources(sources: dict[str, Path], run_dir: Path) -> dict[str, Path]:
    if not isinstance(sources, dict):
        raise ValueError("sources must be a mapping")
    allowed = (run_dir / "inputs").resolve()
    indexed: dict[str, Path] = {}
    for key, raw in sources.items():
        sid = _identifier(key, "source ID")
        path = Path(raw).resolve(strict=True)
        if not path.is_relative_to(allowed) or path == allowed:
            raise ValueError(f"source {sid} must be copied under {allowed}")
        if not (path.is_file() or path.is_dir()):
            raise ValueError(f"source {sid} is not a file or directory")
        indexed[sid] = path
    return indexed


def _validated_probe(probe: dict, tasks: dict[str, dict]) -> tuple[dict, str, list[str], list[dict], dict]:
    if not isinstance(probe, dict):
        raise ValueError("each probe must be an object")
    pid = _identifier(probe.get("id"), "probe ID")
    ids = probe.get("task_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError(f"{pid}: task_ids must be nonempty")
    tids = list(ids)
    if not all(isinstance(t, str) and t for t in tids):
        raise ValueError("task IDs must be nonempty text")
    if len(set(tids)) != len(tids) or any(t not in tasks for t in tids):
        raise ValueError(f"{pid}: duplicate or unknown task ID")
    cases = probe.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{pid}: cases must be nonempty")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or "input" not in case:
            raise ValueError(f"{pid}: each case needs id and input")
        cid = _identifier(case.get("id"), "case ID")
        if cid in seen:
            raise ValueError(f"{pid}: duplicate case ID {cid}")
        seen.add(cid)
        try:
            json.dumps(case["input"], allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{pid}/{cid}: input is not finite JSON") from exc
    command = probe.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise ValueError(f"{pid}: command must be a nonempty token list")
    probe = {"executor": "docker", "scope": "component", **probe}
    if probe["executor"] not in ("trusted_process", "docker"):
        raise ValueError(f"{pid}: executor must be trusted_process or docker")
    if probe.get("scope") not in ("component", "environment"):
        raise ValueError(f"{pid}: scope must be component or environment")
    if probe["executor"] == "docker" and not _DIGEST.fullmatch(str(probe.get("image", ""))):
        raise ValueError(f"{pid}: Docker image must use an immutable @sha256 digest reference")
    relation = probe.get("relation")
    if not isinstance(relation, dict) or relation.get("kind") not in ("invariant", "nondecreasing", "expected"):
        raise ValueError(f"{pid}: invalid relation")
    if not isinstance(relation.get("justification"), str) or not relation["justification"].strip():
        raise ValueError(f"{pid}: relation needs a justification")
    relation = {"tolerance": 1e-9, **relation}
    tolerance = _finite_number(relation["tolerance"], "tolerance")
    if tolerance < 0:
        raise ValueError(f"{pid}: tolerance must be nonnegative")
    if relation["kind"] != "expected" and len(cases) < 2:
        raise ValueError(f"{pid}: relation requires at least two observations")
    if relation["kind"] == "expected":
        vals = relation.get("values")
        if not isinstance(vals, list) or len(vals) != len(cases):
            raise ValueError(f"{pid}: expected values must match cases per task")
        for i, val in enumerate(vals):
            _finite_number(val, f"expected value {i}")
    return probe, pid, tids, cases, relation


def _expand_tokens(tokens: list[str], workspace: Path, sources: dict[str, Path], docker: bool) -> list[str]:
    paths = {key: f"/sources/{key}" if docker else str(path) for key, path in sources.items()}
    work = "/workspace" if docker else str(workspace)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "python":
            return "python3" if docker else sys.executable
        if key == "workspace":
            return work
        sid = match.group(2)
        if sid not in paths:
            raise ValueError(f"unknown source placeholder: {sid}")
        return paths[sid]

    expanded = [_PLACEHOLDER.sub(replace, token) for token in tokens]
    if any("{" in token or "}" in token for token in expanded):
        raise ValueError("unsupported command placeholder")
    return expanded


def _docker_command(name: str, image: str, command: list[str], workspace: Path,
                    sources: dict[str, Path], cpus: float, memory: str) -> list[str]:
    if "," in str(workspace) or ":" in str(workspace):
        raise ValueError("Docker workspace path contains an unsupported mount separator")
    args = [
        "docker", "run", "-i", "--rm", "--pull", "never", "--name", name,
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--cpus", str(cpus), "--memory", memory, "--entrypoint", command[0],
        "--user", f"{os.getuid()}:{os.getgid()}", "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
        "--env", "LANG=C.UTF-8", "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", f"type=bind,src={workspace},dst=/workspace",
    ]
    for sid, path in sources.items():
        if "," in str(path) or ":" in str(path):
            raise ValueError("Docker source path contains an unsupported mount separator")
        args += ["--mount", f"type=bind,src={path},dst=/sources/{sid},readonly"]
    return args + [image] + command[1:]


def _docker_memory(slurm_memory: str) -> str:
    """Preserve Slurm's default megabyte unit in Docker's explicit limit."""
    match = _MEMORY.fullmatch(slurm_memory)
    if match is None:
        raise ValueError("memory must be a positive Slurm size")
    count, unit = int(match.group(1)), match.group(2)
    if unit in ("T", "P"):
        return f"{count * (1024 if unit == 'T' else 1024 * 1024)}g"
    return f"{count}{(unit or 'M').lower()}"


def _stop(proc: subprocess.Popen, docker_name: str | None) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if docker_name:
        try:
            subprocess.run(
                ["docker", "rm", "-f", docker_name], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5, check=False,
                env={"PATH": os.defpath},
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _capture(command: list[str], input_path: Path, stdout_path: Path, stderr_path: Path,
             timeout: float, output_cap: int, workspace: Path, docker_name: str | None,
             engine_path: Path | None = None) -> tuple[int | None, str | None, float]:
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(workspace),
           "PYTHONDONTWRITEBYTECODE":"1", "PYTHONNOUSERSITE":"1"}
    if engine_path is not None:
        # Built-in adapter modules import only the recorded engine. Never
        # inherit the submission host's arbitrary Python search path.
        env["PYTHONPATH"] = str(engine_path)
    # Preserve scheduler device restrictions without inheriting credentials or
    # the caller's general environment into a reviewed host-side driver.
    for key in ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES",
                "GPU_DEVICE_ORDINAL", "ZE_AFFINITY_MASK", "SLURM_JOB_ID",
                "SLURM_JOB_PARTITION", "SLURM_CPUS_PER_TASK"):
        if key in os.environ:
            env[key] = os.environ[key]
    start = time.monotonic()
    try:
        with input_path.open("rb") as data:
            proc = subprocess.Popen(command, stdin=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=workspace, env=env, start_new_session=True)
    except OSError as exc:
        stdout_path.write_bytes(b"")
        stderr_path.write_text(f"spawn error: {type(exc).__name__}\n")
        return None, "spawn_error", time.monotonic() - start
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None and proc.stderr is not None
    for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, label)
    chunks: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    error = None
    deadline = start + timeout
    try:
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                error = "timeout"
                break
            for key, _ in selector.select(min(left, 0.2)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                available = output_cap - sum(len(x) for x in chunks.values())
                chunks[key.data].extend(chunk[:max(0, available)])
                if len(chunk) > available:
                    error = "output_limit"
                    break
            if error:
                break
        if error:
            _stop(proc, docker_name)
        else:
            left = deadline - time.monotonic()
            try:
                proc.wait(timeout=max(0, left))
            except subprocess.TimeoutExpired:
                error = "timeout"
                _stop(proc, docker_name)
            if not docker_name:
                # A reviewed process may spawn workers that outlive its parent.
                # Fresh cases must not inherit those workers or listening ports.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        selector.close()
        for stream in (proc.stdout, proc.stderr):
            if not stream.closed:
                stream.close()
        stdout_path.write_bytes(chunks["stdout"])
        stderr_path.write_bytes(chunks["stderr"])
    return proc.returncode, error, time.monotonic() - start


def _artifacts(workspace: Path, max_count: int, max_bytes: int) -> tuple[list[dict], str | None]:
    artifacts: list[dict] = []
    used = 0
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if not path.resolve().is_relative_to(workspace.resolve()):
            continue
        size = path.stat().st_size
        if len(artifacts) >= max_count or used + size > max_bytes:
            return artifacts, "artifact_limit"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts.append({"path": str(path), "relative_path": str(path.relative_to(workspace)),
                          "bytes": size, "sha256": digest})
        used += size
    return artifacts, None


def _relation_result(kind: str, scores: list[float], tolerance: float, relation: dict) -> bool:
    if kind == "invariant":
        return max(scores) - min(scores) > tolerance
    if kind == "nondecreasing":
        return any(later < earlier - tolerance for earlier, later in zip(scores, scores[1:]))
    expected = [_finite_number(v, "expected value") for v in relation["values"]]
    return any(abs(actual - target) > tolerance for actual, target in zip(scores, expected))


def run_probes(probes: list[dict], tasks: list[dict], sources: dict[str, Path],
               run_dir: Path, execution: dict) -> dict:
    """Run bounded probes and return observations, candidate findings and coverage.

    All actual execution requires the amd-tw-verification Slurm partition. A
    successful relation check is reported only as observed, never as a pass.
    """
    if not isinstance(probes, list) or not isinstance(execution, dict):
        raise ValueError("probes and execution must have valid shapes")
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    task_index = _validated_tasks(tasks)
    source_index = _validated_sources(sources, run_dir)
    limits = {name: _positive_limit(execution, name) for name in _DEFAULTS}
    plans = []
    seen: set[str] = set()
    expanded_count = 0
    for probe in probes:
        probe, pid, tids, cases, relation = _validated_probe(probe, task_index)
        if pid in seen:
            raise ValueError(f"duplicate probe ID: {pid}")
        seen.add(pid)
        expanded_count += len(tids) * len(cases)
        plans.append((probe, pid, tids, cases, relation))
    if expanded_count > limits["max_probe_cases"]:
        raise ValueError("probe case count exceeds max_probe_cases")
    if expanded_count and (os.environ.get("SLURM_JOB_PARTITION") != "amd-tw-verification"
                           or not os.environ.get("SLURM_JOB_ID")):
        raise ValueError("probe execution requires SLURM_JOB_PARTITION=amd-tw-verification and SLURM_JOB_ID")
    if any(p[0]["executor"] == "trusted_process" for p in plans) and execution.get("allow_trusted_process") is not True:
        raise ValueError("trusted_process requires execution.allow_trusted_process=true")
    cpus = _finite_number(execution.get("cpus", 1.0), "cpus")
    if cpus <= 0:
        raise ValueError("cpus must be positive")
    memory = execution.get("memory", "2G")
    if isinstance(memory, int) and not isinstance(memory, bool):
        memory = str(memory)
    if not isinstance(memory, str):
        raise ValueError("memory must be a positive Slurm size")
    docker_memory = _docker_memory(memory)
    results: list[dict] = []
    findings: list[dict] = []
    started = time.monotonic()
    deadline = started + limits["max_probe_seconds"]
    case_statuses: dict[str, int] = {}
    for probe, pid, tids, cases, relation in plans:
        for tid in tids:
            observations: list[dict] = []
            for case in cases:
                cid = case["id"]
                oid = f"{pid}:{tid}:{cid}"
                task_directory = "task-" + hashlib.sha256(tid.encode()).hexdigest()[:24]
                case_dir = run_dir / "probes" / pid / task_directory / cid
                case_dir.mkdir(parents=True, exist_ok=False)
                workspace = case_dir / "workspace"
                workspace.mkdir()
                docker = probe["executor"] == "docker"
                visible_sources = {sid: (f"/sources/{sid}" if docker else str(path))
                                   for sid, path in source_index.items()}
                payload = {"task": task_index[tid], "case": case,
                           "workspace": "/workspace" if docker else str(workspace),
                           "sources": visible_sources}
                input_path = case_dir / "input.json"
                input_path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
                stdout_path = case_dir / "stdout.txt"
                stderr_path = case_dir / "stderr.txt"
                result_path = case_dir / "result.json"
                record: dict[str, Any] = {
                    "id": oid, "probe_id": pid, "task_id": tid, "case_id": cid,
                    "executor": probe["executor"], "scope": probe["scope"],
                    "input_path": str(input_path), "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path), "result_path": str(result_path),
                    "workspace": str(workspace), "artifacts": [],
                    "network_isolation": "docker_network_none" if docker else "none_trusted_process",
                }
                left = deadline - time.monotonic()
                if left <= 0:
                    stdout_path.write_bytes(b"")
                    stderr_path.write_bytes(b"")
                    record.update(status="inconclusive", error="probe_budget_exhausted")
                else:
                    try:
                        command = _expand_tokens(probe["command"], workspace, source_index, docker)
                        name = "rlaudit-" + hashlib.sha256((str(case_dir)).encode()).hexdigest()[:24] if docker else None
                        if docker:
                            command = _docker_command(name, probe["image"], command, workspace,
                                                      source_index, cpus, docker_memory)
                        rc, error, elapsed = _capture(command, input_path, stdout_path, stderr_path,
                                                     min(limits["timeout_seconds"], left),
                                                     limits["max_output_bytes"], workspace, name,
                                                     (run_dir / "engine") if not docker and (run_dir / "engine").is_dir() else None)
                        record.update(exit_code=rc, elapsed_seconds=round(elapsed, 6))
                        if error is None and rc != 0:
                            error = "command_exit_nonzero"
                        if error is None:
                            try:
                                parsed = json.loads(stdout_path.read_text())
                                if not isinstance(parsed, dict):
                                    raise ValueError("output is not an object")
                                reward = _finite_number(parsed.get("reward"), "reward")
                                json.dumps(parsed, allow_nan=False)
                                record.update(status="observed", reward=reward,
                                              details=parsed.get("details"))
                            except (UnicodeError, ValueError, json.JSONDecodeError):
                                error = "malformed_output"
                        if error:
                            record.update(status="inconclusive", error=error)
                    except ValueError as exc:
                        stdout_path.write_bytes(b"")
                        stderr_path.write_bytes(b"")
                        record.update(status="inconclusive", error="invalid_command", detail=str(exc))
                artifacts, artifact_error = _artifacts(workspace, limits["max_artifacts"], limits["max_artifact_bytes"])
                record["artifacts"] = artifacts
                if artifact_error:
                    record.pop("reward", None)
                    record.update(status="inconclusive", error=artifact_error)
                result_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
                observations.append(record)
                case_statuses[record["status"]] = case_statuses.get(record["status"], 0) + 1
            scores = [record["reward"] for record in observations if record["status"] == "observed"]
            if len(scores) != len(observations):
                status = "inconclusive"
                violated = None
            else:
                violated = _relation_result(relation["kind"], scores,
                                            _finite_number(relation["tolerance"], "tolerance"), relation)
                status = "candidate_violation" if violated else "relation_holds_in_sample"
            item = {"id": f"{pid}:{tid}", "probe_id": pid, "task_id": tid,
                    "status": status, "relation": relation, "scope": probe["scope"],
                    "case_ids": [r["id"] for r in observations], "scores": scores if violated is not None else None,
                    "relation_satisfied": (None if violated is None else not violated),
                    "observations": observations, "oracle_independently_verified": False}
            results.append(item)
            if violated:
                findings.append({"id": f"{pid}:{tid}:relation_violation", "check_id": f"probe:{pid}",
                                 "task_id": tid, "status": "candidate",
                                 "summary": f"Declared {relation['kind']} relation was violated for task {tid}.",
                                 "evidence_level": ("component_reproduction" if probe["scope"] == "component"
                                                    else "environment_reproduction"),
                                 "probe_id": pid, "relation": relation,
                                 "observed_scores": scores, "case_ids": item["case_ids"],
                                 "evidence": [{"case_id": r["case_id"], "result_path": r["result_path"],
                                               "stdout_path": r["stdout_path"], "reward": r["reward"]}
                                              for r in observations],
                                 "limitations": ["Relation is the caller's declared oracle; semantic validity was not independently verified."]})
    incomplete_ids = {x["probe_id"] for x in results if x["status"] == "inconclusive"}
    coverage = {"configured_probes": len(plans), "configured_task_relations": len(results),
                "configured_cases": expanded_count,
                "completed_probes": len(plans) - len(incomplete_ids),
                "inconclusive_probes": len(incomplete_ids),
                "completed_task_relations": sum(x["status"] != "inconclusive" for x in results),
                "inconclusive_task_relations": sum(x["status"] == "inconclusive" for x in results),
                "candidate_findings": len(findings), "case_status_counts": case_statuses,
                "elapsed_seconds": round(time.monotonic() - started, 6)}
    return {"results": results, "findings": findings, "coverage": coverage}
