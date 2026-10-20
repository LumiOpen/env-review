"""Strict, declarative contracts for small reviewed Verifiers environments.

Contracts describe trusted source execution; they do not sandbox source code.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "rlaudit.environment/v1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
_REFERENCE_KEYS = frozenset({"task", "source", "case"})


class ContractError(ValueError):
    """An environment contract or a declared reference is invalid."""


def _object(value: Any, name: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{name} keys must be strings")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise ContractError(f"{name} missing keys: {', '.join(sorted(missing))}")
    if extra:
        raise ContractError(f"{name} unknown keys: {', '.join(sorted(extra))}")
    return value


def _string(value: Any, name: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be a nonempty string")
    if identifier and not _IDENTIFIER.fullmatch(value):
        raise ContractError(f"{name} must be a public identifier")
    return value


def _path(value: Any, name: str) -> str:
    path = _string(value, name)
    if any(not _IDENTIFIER.fullmatch(part) for part in path.split(".")):
        raise ContractError(f"{name} must contain only public dotted identifiers")
    return path


def _nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ContractError(f"{name} must be a nonnegative integer")
    return value


def _literal_or_ref(value: Any, name: str, *, case_allowed: bool = False) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float:
        import math

        if not math.isfinite(value):
            raise ContractError(f"{name} must be finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _literal_or_ref(item, f"{name}[{index}]", case_allowed=case_allowed)
        return
    if isinstance(value, dict):
        keys = set(value)
        if keys & _REFERENCE_KEYS:
            if len(keys) != 1:
                raise ContractError(f"{name} reference must have exactly one key")
            kind = next(iter(keys))
            if kind == "case" and not case_allowed:
                raise ContractError(f"{name} cannot refer to a probe case")
            if kind == "source":
                source_id = _string(value[kind], f"{name}.source")
                if not _SOURCE_ID.fullmatch(source_id):
                    raise ContractError(f"{name}.source must be a source ID")
            else:
                _path(value[kind], f"{name}.{kind}")
            return
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{name} keys must be strings")
            _literal_or_ref(item, f"{name}.{key}", case_allowed=case_allowed)
        return
    raise ContractError(f"{name} must be JSON data or a reference")


def _oracle(value: Any) -> None:
    if not isinstance(value, dict):
        raise ContractError("oracle must be an object")
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise ContractError("oracle.kind must be a string")
    if kind == "arithmetic":
        spec = _object(value, "oracle", {"kind", "expression", "numbers", "target", "rules"}, {"tag"})
        rules = _object(spec["rules"], "oracle.rules", {"operators", "positive_literals", "positive_intermediates", "integer_intermediates", "use_each_at_most_once"})
        operators = rules["operators"]
        if not isinstance(operators, list) or not operators or any(not isinstance(op, str) for op in operators) or len(set(operators)) != len(operators) or any(op not in {"add", "sub", "mul", "div"} for op in operators):
            raise ContractError("oracle.rules.operators must list unique supported arithmetic operators")
        for flag in ("positive_literals", "positive_intermediates", "integer_intermediates", "use_each_at_most_once"):
            if type(rules[flag]) is not bool:
                raise ContractError(f"oracle.rules.{flag} must be Boolean")
    elif kind in {"exact_text", "lcs"}:
        spec = _object(value, "oracle", {"kind", "candidate", "expected"}, {"tag"})
    else:
        raise ContractError(f"unsupported oracle kind: {kind!r}")
    kind = spec["kind"]
    fields = ("expression", "numbers", "target") if kind == "arithmetic" else ("candidate", "expected")
    for field in fields:
        _literal_or_ref(spec[field], f"oracle.{field}", case_allowed=True)
    if "tag" in spec:
        _string(spec["tag"], "oracle.tag", identifier=True)


def validate_environment_contract(value: Any) -> dict:
    """Return a validated JSON copy; reject unknown fields at every schema level."""
    contract = _object(value, "contract", {"schema_version", "id", "framework", "loader", "task", "interaction", "score", "capture"}, {"oracle"})
    if contract["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
    _string(contract["id"], "id")
    if contract["framework"] != "verifiers_v0":
        raise ContractError("framework must be verifiers_v0")

    loader = _object(contract["loader"], "loader", {"source", "module", "factory", "kwargs"})
    if not _SOURCE_ID.fullmatch(_string(loader["source"], "loader.source")):
        raise ContractError("loader.source must be a source ID")
    _path(loader["module"], "loader.module")
    _string(loader["factory"], "loader.factory", identifier=True)
    if not isinstance(loader["kwargs"], dict):
        raise ContractError("loader.kwargs must be an object")
    for key, item in loader["kwargs"].items():
        _string(key, "loader.kwargs key", identifier=True)
        _literal_or_ref(item, f"loader.kwargs.{key}")

    task = _object(contract["task"], "task", {"dataset", "index", "expect"})
    if task["dataset"] not in ("dataset", "eval_dataset"):
        raise ContractError("task.dataset must be dataset or eval_dataset")
    _literal_or_ref(task["index"], "task.index")
    if type(task["index"]) is not int and not (isinstance(task["index"], dict) and set(task["index"]) == {"task"}):
        raise ContractError("task.index must be an integer or task reference")
    if type(task["index"]) is int:
        _nonnegative_int(task["index"], "task.index")
    if not isinstance(task["expect"], dict) or not task["expect"]:
        raise ContractError("task.expect must be a nonempty object")
    for field, expected in task["expect"].items():
        _path(field, "task.expect field")
        _literal_or_ref(expected, f"task.expect.{field}")

    interaction = _object(contract["interaction"], "interaction", {"kind"}, {"tools", "stop", "max_calls", "state_keys"})
    kind = interaction["kind"]
    if kind == "completion":
        if set(interaction) != {"kind"}:
            raise ContractError("completion interaction accepts only kind")
    elif kind == "tool_sequence":
        _object(interaction, "interaction", {"kind", "tools", "stop", "max_calls", "state_keys"})
        tools = interaction["tools"]
        if not isinstance(tools, list) or not tools or len(set(map(str, tools))) != len(tools):
            raise ContractError("interaction.tools must be a nonempty unique list")
        for tool in tools:
            _string(tool, "interaction.tools item", identifier=True)
        _string(interaction["stop"], "interaction.stop", identifier=True)
        if type(interaction["max_calls"]) is not int or not 1 <= interaction["max_calls"] <= 100:
            raise ContractError("interaction.max_calls must be between 1 and 100")
        keys = interaction["state_keys"]
        if not isinstance(keys, list) or len(set(map(str, keys))) != len(keys):
            raise ContractError("interaction.state_keys must be a unique list")
        for key in keys:
            _string(key, "interaction.state_keys item", identifier=True)
    else:
        raise ContractError("interaction.kind must be completion or tool_sequence")

    score = _object(contract["score"], "score", {"metric", "required_metrics"})
    _string(score["metric"], "score.metric", identifier=True)
    metrics = score["required_metrics"]
    if not isinstance(metrics, list) or len(set(map(str, metrics))) != len(metrics):
        raise ContractError("score.required_metrics must be a unique list")
    for metric in metrics:
        _string(metric, "score.required_metrics item", identifier=True)
    capture = _object(contract["capture"], "capture", {"parsed_answer"})
    if type(capture["parsed_answer"]) is not bool:
        raise ContractError("capture.parsed_answer must be Boolean")
    if "oracle" in contract:
        _oracle(contract["oracle"])

    try:
        return json.loads(json.dumps(contract, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ContractError("contract must contain only finite JSON data") from error


def load_environment_contract(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read environment contract: {error}") from error
    return validate_environment_contract(value)


def _lookup(root: Any, path: str, name: str) -> Any:
    _path(path, name)
    current = root
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ContractError(f"{name} missing field: {path}")
        current = current[part]
    return current


def resolve_ref(value: Any, task: Mapping[str, Any], sources: Mapping[str, str | Path], case: Mapping[str, Any] | None = None) -> Any:
    """Resolve only declared task, case, and pinned source references recursively."""
    _literal_or_ref(value, "value", case_allowed=case is not None)
    if isinstance(value, list):
        return [resolve_ref(item, task, sources, case) for item in value]
    if isinstance(value, dict):
        if set(value) == {"task"}:
            return _lookup(task, value["task"], "task reference")
        if set(value) == {"case"}:
            if case is None:
                raise ContractError("case reference requires a probe case")
            return _lookup(case, value["case"], "case reference")
        if set(value) == {"source"}:
            source_id = value["source"]
            if source_id not in sources:
                raise ContractError(f"undeclared source ID: {source_id}")
            source_path = sources[source_id]
            if not isinstance(source_path, (str, Path)):
                raise ContractError(f"source {source_id} has no filesystem path")
            return str(source_path)
        return {key: resolve_ref(item, task, sources, case) for key, item in value.items()}
    return value


def validate_source_ids(contract: Mapping[str, Any], sources: Mapping[str, Any] | set[str]) -> None:
    """Reject references to IDs absent from the pipeline's declared source set."""
    source_ids = set(sources)
    required: set[str] = {contract["loader"]["source"]}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) == {"source"}:
                required.add(value["source"])
            else:
                for item in value.values():
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(contract)
    missing = required - source_ids
    if missing:
        raise ContractError(f"undeclared source IDs: {', '.join(sorted(missing))}")


# Short aliases for callers embedding contracts in pipeline configurations.
load = load_environment_contract
validate = validate_environment_contract
resolve = resolve_ref
