"""Source-backed, model-free replay for reviewed Verifiers v0 environments.

The contract chooses a pinned source module, one dataset row, and a narrow
interaction. This module supplies no task-specific reward or semantic oracle.
Each pipeline case starts this module in a fresh process.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import logging
import math
from pathlib import Path
import sys
import types
from typing import Any

from .contracts import (load_environment_contract, resolve_ref,
                        validate_environment_contract, validate_source_ids)


def _require_runtime() -> None:
    for package, expected in (("verifiers", "0.3.0"), ("datasets", "4.3.0")):
        installed = importlib.metadata.version(package)
        if installed != expected:
            raise RuntimeError(f"{package}=={expected} required; found {installed}")


def _source_module(source: Path, module_name: str) -> Any:
    """Import a reviewed source under a private namespace, including packages."""
    root = source if source.is_dir() else source.parent
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"loader source is not a directory or module: {source}")
    namespace = "_rlaudit_pinned_source_" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    package = types.ModuleType(namespace)
    package.__package__ = namespace
    package.__path__ = [str(root)]
    sys.modules[namespace] = package
    try:
        module = importlib.import_module(f"{namespace}.{module_name}")
    except Exception:
        sys.modules.pop(namespace, None)
        raise
    origin = Path(module.__file__).resolve(strict=True)
    if not origin.is_relative_to(root) or (source.is_file() and origin != source.resolve()):
        raise ValueError(f"loaded module is outside declared source: {origin}")
    return module


def _field(record: Any, dotted: str) -> Any:
    current = record
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"selected dataset row lacks {dotted!r}")
        current = current[part]
    return current


def _selected_row(env: Any, contract: dict, task: dict, sources: dict) -> tuple[int, dict]:
    selection = contract["task"]
    index = resolve_ref(selection["index"], task, sources)
    if type(index) is not int or index < 0:
        raise ValueError("task.index must resolve to a nonnegative integer")
    dataset = getattr(env, selection["dataset"], None)
    if dataset is None or not hasattr(dataset, "__getitem__") or not hasattr(dataset, "__len__"):
        raise ValueError(f"environment has no usable {selection['dataset']} dataset")
    if index >= len(dataset):
        raise ValueError(f"task.index {index} is outside source dataset of length {len(dataset)}")
    row = dataset[index]
    if not isinstance(row, dict):
        raise ValueError("source dataset row must be an object")
    for name, expectation in selection["expect"].items():
        actual = _field(row, name)
        expected = resolve_ref(expectation, task, sources)
        if actual != expected or isinstance(actual, bool) != isinstance(expected, bool):
            raise ValueError(f"selected source dataset row differs at {name!r}")
    return index, row


def _initial_state(env: Any, row: dict) -> dict:
    prompt: list[dict[str, str]] = []
    system = getattr(env, "system_prompt", None)
    if isinstance(system, str) and system:
        prompt.append({"role": "system", "content": system})
    question = row.get("question")
    if not isinstance(question, str):
        raise ValueError("source dataset row.question must be text")
    prompt.append({"role": "user", "content": question})
    return {
        "input": row,
        "prompt": prompt,
        "completion": [],
        "answer": row.get("answer"),
        "info": row.get("info", {}),
        "trajectory": [],
    }


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _replay_tools(env: Any, state: dict, interaction: dict, case_input: dict) -> tuple[list[dict], bool]:
    calls = case_input.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("tool_sequence requires a nonempty input.calls list")
    if len(calls) > interaction["max_calls"]:
        raise ValueError("tool sequence exceeds declared max_calls")
    source_max_turns = getattr(env, "max_turns", None)
    if type(source_max_turns) is int and source_max_turns > 0 and len(calls) > source_max_turns:
        raise ValueError("tool sequence exceeds source max_turns")
    setup = getattr(env, "setup_state", None)
    update = getattr(env, "update_tool_args", None)
    stop = getattr(env, interaction["stop"], None)
    if not all(callable(method) for method in (setup, update, stop)):
        raise ValueError("source environment lacks declared setup, argument injection, or stop method")
    await _maybe_await(setup(state))
    responses = []
    for position, call in enumerate(calls):
        if not isinstance(call, dict) or set(call) != {"tool", "args"}:
            raise ValueError(f"input.calls[{position}] must contain tool and args")
        tool_name, arguments = call["tool"], call["args"]
        if tool_name not in interaction["tools"] or not isinstance(arguments, dict):
            raise ValueError(f"input.calls[{position}] uses undeclared tool or invalid args")
        if await _maybe_await(stop(state)):
            raise ValueError("tool call supplied after source stop condition")
        tool = getattr(env, tool_name, None)
        if not callable(tool):
            raise ValueError(f"source environment lacks declared tool {tool_name!r}")
        injected = await _maybe_await(update(tool_name, dict(arguments), [], state))
        if not isinstance(injected, dict):
            raise ValueError("source update_tool_args must return an object")
        response = await _maybe_await(tool(**injected))
        responses.append({"tool": tool_name, "args": arguments, "response": response})
    return responses, bool(await _maybe_await(stop(state)))


async def _score_checked(rubric: Any, state: dict) -> None:
    errors: list[str] = []

    class GradingErrors(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.ERROR:
                errors.append(record.getMessage())

    logger = logging.getLogger("verifiers.rubrics.rubric")
    handler = GradingErrors()
    logger.addHandler(handler)
    try:
        await _maybe_await(rubric.score_rollout(state))
    finally:
        logger.removeHandler(handler)
    if errors:
        raise RuntimeError("source rubric logged a grading error: " + "; ".join(errors))


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite number")
    return converted


async def run_case(payload: dict, contract: dict) -> dict:
    """Execute one contract against the source paths in a pipeline payload."""
    contract = validate_environment_contract(contract)
    if contract["framework"] != "verifiers_v0":
        raise ValueError(f"unsupported environment framework: {contract['framework']!r}")
    _require_runtime()
    if not isinstance(payload, dict):
        raise ValueError("probe payload must be an object")
    task, case, sources = payload.get("task"), payload.get("case"), payload.get("sources")
    if not isinstance(task, dict) or not isinstance(case, dict) or not isinstance(sources, dict):
        raise ValueError("probe payload requires task, case, and sources objects")
    case_input = case.get("input")
    if not isinstance(case_input, dict):
        raise ValueError("case.input must be an object")
    validate_source_ids(contract, sources)
    loader = contract["loader"]
    source = Path(sources[loader["source"]])
    module = _source_module(source, loader["module"])
    factory = getattr(module, loader["factory"], None)
    if not callable(factory):
        raise ValueError(f"source module lacks declared factory {loader['factory']!r}")
    kwargs = resolve_ref(loader["kwargs"], task, sources, case=case)
    if not isinstance(kwargs, dict):
        raise ValueError("loader kwargs must resolve to an object")
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        env = await _maybe_await(factory(**kwargs))
    loader_stdout = captured.getvalue()
    if loader_stdout:
        print(loader_stdout, file=sys.stderr, end="" if loader_stdout.endswith("\n") else "\n")
    row_index, row = _selected_row(env, contract, task, sources)
    state = _initial_state(env, row)
    interaction = contract["interaction"]
    details: dict[str, Any] = {
        "environment": contract["id"],
        "scope": "source_rubric_component" if interaction["kind"] == "completion" else "source_state_tool_rubric_component",
        "row_index": row_index,
        "selected_row": row,
    }
    if interaction["kind"] == "completion":
        completion = case_input.get("completion")
        if not isinstance(completion, str):
            raise ValueError("completion must be text")
        state["completion"] = [{"role": "assistant", "content": completion}]
    elif interaction["kind"] == "tool_sequence":
        responses, stopped = await _replay_tools(env, state, interaction, case_input)
        details.update(tool_calls=responses, stopped=stopped,
                       framework_trajectory_metrics_scope="empty scaffold; inspect replayed tool calls")
    else:
        raise ValueError(f"unsupported interaction kind: {interaction['kind']!r}")
    rubric = getattr(env, "rubric", None)
    if rubric is None or not callable(getattr(rubric, "score_rollout", None)):
        raise ValueError("source environment has no rubric.score_rollout")
    await _score_checked(rubric, state)
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("source rubric did not return metrics")
    for name in contract["score"]["required_metrics"]:
        if name not in metrics:
            raise ValueError(f"source rubric did not return required metric {name!r}")
        _finite(metrics[name], f"metric {name}")
    metric = contract["score"]["metric"]
    reward = _finite(state.get("reward") if metric == "reward" else metrics.get(metric), metric)
    details.update(rubric_reward=_finite(state.get("reward"), "rubric reward"),
                   rubric_metrics=metrics, metric_returned=metric)
    for key in interaction.get("state_keys", []):
        if key not in state:
            raise ValueError(f"source state lacks declared capture key {key!r}")
    if interaction.get("state_keys"):
        details["state"] = {key: state[key] for key in interaction["state_keys"]}
    if contract["capture"]["parsed_answer"]:
        parser = getattr(env, "parser", None)
        if parser is None or not callable(getattr(parser, "parse_answer", None)):
            raise ValueError("source environment has no parser.parse_answer")
        details["parsed_answer"] = await _maybe_await(parser.parse_answer(state["completion"]))
    if "oracle" in contract:
        from .oracles import evaluate

        details["oracle"] = evaluate(contract["oracle"], task, case)
    # Fail before emitting a superficially valid reward if source data or metric
    # objects cannot be represented by the runner's JSON protocol.
    result = {"reward": reward, "details": details}
    json.dumps(result, allow_nan=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    contract = load_environment_contract(args.contract)
    payload = json.load(sys.stdin)
    # Source imports, tools, or graders may print. Keep stdout a single JSON
    # object so the pipeline never mistakes source chatter for a result.
    with contextlib.redirect_stdout(sys.stderr):
        result = asyncio.run(run_case(payload, contract))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
