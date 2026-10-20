"""Strict configuration validation; parsing never imports environment code."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

SCHEMA = "rlaudit.pipeline/v1"
PARTITION = "amd-tw-verification"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
DEFAULT_EXECUTION = {
    "partition": PARTITION,
    "cpus": 1,
    "gpus": 0,
    "memory": "2G",
    "time_limit": "00:05:00",
    "max_source_bytes": 268435456,
    "max_source_files": 10000,
    "max_tasks": 10000,
    "max_probe_cases": 20,
    "timeout_seconds": 30,
    "max_probe_seconds": 120,
    "max_output_bytes": 1048576,
    "max_artifacts": 100,
    "max_artifact_bytes": 10485760,
    "allow_trusted_process": False,
    "dependencies": {},
}


def identifier(value, context):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{context} must be a simple identifier (letters, digits, _, -, .)")
    return value


def object_keys(value, allowed, context):
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {context} keys: {', '.join(sorted(unknown))}")


def number(value, context, minimum=0, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < minimum or (integer and not isinstance(value, int)):
        raise ValueError(f"Invalid {context}")


def validate(config):
    object_keys(config, {"schema_version", "name", "sources", "adapter", "checks", "probes", "execution", "provenance"}, "manifest")
    if config.get("schema_version") != SCHEMA:
        raise ValueError(f"schema_version must be {SCHEMA}")
    identifier(config.get("name"), "name")
    if not isinstance(config.get("provenance", {}), dict):
        raise ValueError("provenance must be an object of declared source context")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a nonempty list")
    source_ids = set()
    for source in sources:
        object_keys(source, {"id", "path", "sha256"}, "source")
        sid = identifier(source.get("id"), "source.id")
        if sid in source_ids:
            raise ValueError(f"Duplicate source ID: {sid}")
        source_ids.add(sid)
        if not isinstance(source.get("path"), str) or not source["path"]:
            raise ValueError("source.path must name a local file or directory")
        if "sha256" in source and not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            raise ValueError("source.sha256 must be a lowercase SHA-256")
    adapter = config.get("adapter")
    object_keys(adapter, {"kind", "source", "ids", "limit"}, "adapter")
    if adapter.get("kind") not in {"local_jsonl", "mimo_code", "mimo_general", "mimo_cyber", "mimo_webdev", "mimo_music"}:
        raise ValueError("Unsupported adapter kind; export another environment to local_jsonl")
    if adapter.get("source") not in source_ids:
        raise ValueError("adapter.source references an unknown source ID")
    if "ids" in adapter and (not isinstance(adapter["ids"], list) or not all(isinstance(x, str) for x in adapter["ids"])):
        raise ValueError("adapter.ids must be a list of task IDs")
    if "limit" in adapter:
        number(adapter["limit"], "adapter.limit", minimum=1, integer=True)
    checks = config.get("checks", ["schema"])
    if not isinstance(checks, list) or not all(isinstance(x, str) and x in {"schema", "code_static", "general_contract", "mimo_contract"} for x in checks):
        raise ValueError("Unknown check; supported: schema, code_static, general_contract, mimo_contract")
    if len(set(checks)) != len(checks):
        raise ValueError("Duplicate checks")
    execution = config.get("execution", {})
    object_keys(execution, DEFAULT_EXECUTION, "execution")
    execution = {**DEFAULT_EXECUTION, **execution}
    if execution["partition"] != PARTITION:
        raise ValueError(f"This workspace requires partition {PARTITION}")
    for key in ["cpus", "max_source_bytes", "max_source_files", "max_tasks", "max_probe_cases", "max_output_bytes", "max_artifacts", "max_artifact_bytes"]:
        number(execution[key], f"execution.{key}", minimum=1, integer=True)
    number(execution["gpus"], "execution.gpus", integer=True)
    for key in ["timeout_seconds", "max_probe_seconds"]:
        number(execution[key], f"execution.{key}", minimum=0.01)
    if not isinstance(execution["allow_trusted_process"], bool):
        raise ValueError("allow_trusted_process must be boolean")
    if not re.fullmatch(r"[1-9][0-9]*[KMGTP]?", str(execution["memory"])):
        raise ValueError("Invalid Slurm memory request")
    if not re.fullmatch(r"[0-9]{1,3}:[0-5][0-9]:[0-5][0-9]", str(execution["time_limit"])):
        raise ValueError("time_limit must be HH:MM:SS")
    if not isinstance(execution["dependencies"], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in execution["dependencies"].items()):
        raise ValueError("dependencies must map distribution names to exact installed versions")
    for name,version in execution["dependencies"].items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
            raise ValueError("Dependencies require package names and exact versions, not URLs or markers")
    if adapter["kind"] in {"mimo_code", "mimo_cyber", "mimo_webdev", "mimo_music"} and "pyarrow" not in execution["dependencies"]:
        raise ValueError(f"{adapter['kind']} requires an explicit execution.dependencies.pyarrow version pin")
    probes = config.get("probes", [])
    if not isinstance(probes, list):
        raise ValueError("probes must be a list")
    if not checks and not probes:
        raise ValueError("An audit requires at least one check or probe")
    if "schema" not in checks:
        checks = ["schema"] + checks
    probe_ids = set()
    for probe in probes:
        object_keys(probe, {"id", "task_ids", "command", "cases", "relation", "executor", "image", "scope"}, "probe")
        pid = identifier(probe.get("id"), "probe.id")
        if pid in probe_ids:
            raise ValueError(f"Duplicate probe ID: {pid}")
        probe_ids.add(pid)
        if not isinstance(probe.get("task_ids"), list) or not probe["task_ids"] or not all(isinstance(x, str) for x in probe["task_ids"]):
            raise ValueError("probe.task_ids must be a nonempty list")
        if len(set(probe["task_ids"])) != len(probe["task_ids"]):
            raise ValueError("Duplicate probe task IDs")
        if not isinstance(probe.get("command"), list) or not probe["command"] or not all(isinstance(x, str) and x for x in probe["command"]):
            raise ValueError("probe.command must be a nonempty argv list; shell strings are unsupported")
        if probe.get("executor", "docker") not in {"trusted_process", "docker"}:
            raise ValueError("Unknown probe executor")
        if probe.get("executor", "docker") == "trusted_process" and not execution["allow_trusted_process"]:
            raise ValueError("trusted_process requires execution.allow_trusted_process=true")
        if probe.get("executor", "docker") == "docker" and not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", str(probe.get("image", ""))):
            raise ValueError("Docker probes require a digest-pinned image")
        if probe.get("executor", "docker") == "docker" and execution["gpus"]:
            raise ValueError("Docker GPU passthrough is not configured; use an explicitly reviewed host driver")
        if probe.get("scope", "component") not in {"component", "environment"}:
            raise ValueError("Probe scope must be component or environment")
        cases = probe.get("cases")
        if not isinstance(cases, list) or len(cases) < 2:
            raise ValueError("Paired probes require at least two cases")
        case_ids = set()
        for case in cases:
            object_keys(case, {"id", "input"}, "case")
            if "input" not in case:
                raise ValueError("Each probe case must declare input")
            cid = identifier(case.get("id"), "case.id")
            if cid in case_ids:
                raise ValueError("Duplicate probe case ID")
            case_ids.add(cid)
        relation = probe.get("relation")
        object_keys(relation, {"kind", "justification", "tolerance", "values"}, "relation")
        if relation.get("kind") not in {"invariant", "nondecreasing", "expected"}:
            raise ValueError("Unsupported relation")
        if not isinstance(relation.get("justification"), str) or not relation["justification"].strip():
            raise ValueError("A relation needs an explicit semantic justification")
        number(relation.get("tolerance", 1e-9), "relation.tolerance")
        if relation["kind"] == "expected":
            values = relation.get("values")
            if not isinstance(values, list) or len(values) != len(cases):
                raise ValueError("Expected relation needs one value per case")
            for value in values:
                number(value, "expected reward", minimum=-float("inf"))
    result = json.loads(json.dumps(config, allow_nan=False))
    result.update({"checks": checks, "probes": json.loads(json.dumps(probes)), "execution": execution})
    for probe in result["probes"]:
        probe.setdefault("executor", "docker")
        probe.setdefault("scope", "component")
        probe["relation"].setdefault("tolerance", 1e-9)
    return result


def load(path):
    path = Path(path).resolve()
    return validate(json.loads(path.read_text(encoding="utf-8")))
