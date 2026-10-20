"""Hash-gated static screen for read-only tasks with exposed SQL writes.

This scanner parses cached task files as data. It never imports or executes
grader, dispatcher, or tool code. A signal means "review this task", not that
the tool write is permitted or that the task is defective.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


DETECTOR_NAME = "readonly-tool-write-001"
KNOWN_HASHES = {
    "verify.py": "caa22a4c64bea979f2b3bef85d77cab5a78880a4dd9e304b4b4ee2317f48ac13",
    # SHA256 of the cached finance task's mcp_http.py. Its pinned source
    # registers each module-local public function (see dispatcher lines 191-200).
    "mcp_http.py": "e2107557b5b930365fd6aa4a42e1449ea535d620605959ff6cf66ca9293d7cda",
}
DATASET_REVISION = "e8e81e4945270b6212204bad99de1e598f7fb077"
READ_ONLY_PHRASES = (
    "read-only", "read only", "do not modify", "do not change", "do not write",
    "without modifying", "without changing", "只读", "不得修改", "不要修改", "不修改",
)
_WRITE_PATTERNS = (
    ("INSERT INTO", re.compile(r"^INSERT\s+INTO\b", re.IGNORECASE)),
    ("UPDATE..SET", re.compile(r"^UPDATE\b[\s\S]*?\bSET\b", re.IGNORECASE)),
    ("DELETE FROM", re.compile(r"^DELETE\s+FROM\b", re.IGNORECASE)),
)


class InspectionError(Exception):
    """A local task could not be inspected without guessing."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise InspectionError(f"cannot read {path}: {error}") from error


def _file_hash(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file() or path.is_symlink():
        return None, "missing_or_nonregular"
    try:
        return _sha256(path), None
    except OSError as error:
        return None, f"unreadable:{error}"


def _leading_sql_comments(sql: str) -> str:
    """Remove leading SQL comments so a static write after them is recognized."""
    text = sql.lstrip()
    while True:
        if text.startswith("--"):
            newline = text.find("\n")
            if newline < 0:
                return ""
            text = text[newline + 1:].lstrip()
        elif text.startswith("/*"):
            end = text.find("*/", 2)
            if end < 0:
                return ""
            text = text[end + 2:].lstrip()
        else:
            return text


def _write_kind(sql: str) -> str | None:
    statement = _leading_sql_comments(sql)
    for label, pattern in _WRITE_PATTERNS:
        if pattern.search(statement):
            return label
    return None


def _static_string(expr: ast.AST, values: dict[str, tuple[str, ast.Constant] | None]
                   ) -> tuple[str, ast.Constant] | None:
    """Resolve only literal string expressions; dynamic expressions stay unknown."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value, expr
    if isinstance(expr, ast.Name):
        return values.get(expr.id)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _static_string(expr.left, values)
        right = _static_string(expr.right, values)
        if left is not None and right is not None:
            return left[0] + right[0], left[1]
    return None


def _assigned_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _assigned_names(item)]
    return []


def _query_arg(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in {"sql", "query", "statement", "operation"}:
            return keyword.value
    return None


def _calls_in(expr: ast.AST):
    """Yield calls in an expression, excluding nested executable scopes."""
    stack = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _merge_values(left: dict[str, tuple[str, ast.Constant] | None],
                  right: dict[str, tuple[str, ast.Constant] | None]
                  ) -> dict[str, tuple[str, ast.Constant] | None]:
    merged = {}
    for name in left.keys() | right.keys():
        a, b = left.get(name), right.get(name)
        merged[name] = a if a is not None and b is not None and a[0] == b[0] else None
    return merged


def _scan_tool_function(function: ast.FunctionDef | ast.AsyncFunctionDef,
                        source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    writes: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    values: dict[str, tuple[str, ast.Constant] | None] = {}

    def scan_expr(expr: ast.AST | None, current: dict[str, tuple[str, ast.Constant] | None]):
        if expr is None:
            return
        for call in _calls_in(expr):
            if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"execute", "executemany"}:
                continue
            query_expr = _query_arg(call)
            resolved = _static_string(query_expr, current) if query_expr is not None else None
            if resolved is None:
                unknown.append({
                    "tool_function": function.name,
                    "execute_method": call.func.attr,
                    "execute_line": getattr(call, "lineno", None),
                    "query_expression": ast.get_source_segment(source, query_expr) if query_expr else None,
                    "reason": "query is dynamic or not a supported static string expression",
                })
                continue
            sql, literal_node = resolved
            operation = _write_kind(sql)
            if operation:
                writes.append({
                    "tool_function": function.name,
                    "execute_method": call.func.attr,
                    "operation": operation,
                    "sql_literal": sql,
                    "literal_line": getattr(literal_node, "lineno", None),
                    "execute_line": getattr(call, "lineno", None),
                })

    def scan_block(statements: list[ast.stmt], current: dict[str, tuple[str, ast.Constant] | None]
                   ) -> dict[str, tuple[str, ast.Constant] | None]:
        current = dict(current)
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Nested functions are separate scopes, not MCP-registered functions.
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                scan_expr(statement.value, current)
                resolved = _static_string(statement.value, current)
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    for name in _assigned_names(target):
                        current[name] = resolved
                continue
            if isinstance(statement, ast.AugAssign):
                scan_expr(statement.value, current)
                if isinstance(statement.target, ast.Name) and isinstance(statement.op, ast.Add):
                    left = current.get(statement.target.id)
                    right = _static_string(statement.value, current)
                    current[statement.target.id] = ((left[0] + right[0], left[1])
                                                     if left is not None and right is not None else None)
                else:
                    for name in _assigned_names(statement.target):
                        current[name] = None
                continue
            if isinstance(statement, ast.If):
                scan_expr(statement.test, current)
                left = scan_block(statement.body, dict(current))
                right = scan_block(statement.orelse, dict(current)) if statement.orelse else dict(current)
                current = _merge_values(left, right)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                scan_expr(statement.iter if isinstance(statement, (ast.For, ast.AsyncFor)) else statement.test, current)
                body_start = dict(current)
                if isinstance(statement, (ast.For, ast.AsyncFor)):
                    for name in _assigned_names(statement.target):
                        body_start[name] = None
                after = scan_block(statement.body, body_start)
                after = _merge_values(current, after)
                current = scan_block(statement.orelse, after) if statement.orelse else after
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    scan_expr(item.context_expr, current)
                    for name in (_assigned_names(item.optional_vars) if item.optional_vars else []):
                        current[name] = None
                current = scan_block(statement.body, current)
                continue
            if isinstance(statement, ast.Try):
                paths = [scan_block(statement.body, dict(current))]
                paths.extend(scan_block(handler.body, dict(current)) for handler in statement.handlers)
                if statement.orelse:
                    paths.append(scan_block(statement.orelse, dict(current)))
                current = paths[0]
                for path in paths[1:]:
                    current = _merge_values(current, path)
                if statement.finalbody:
                    current = scan_block(statement.finalbody, current)
                continue
            scan_expr(statement, current)
        return current

    scan_block(function.body, values)
    return writes, unknown


def _instruction_evidence(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.is_file() or path.is_symlink():
        return [], True
    text = _read_text(path)
    evidence = []
    for line_number, line in enumerate(text.splitlines(), 1):
        lowered = line.casefold()
        for phrase in READ_ONLY_PHRASES:
            if phrase.casefold() in lowered:
                evidence.append({"line": line_number, "phrase": phrase, "quote": line})
                break
    return evidence, not evidence


def _stable_candidate_id(task_id: str) -> str:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"readonly-{digest}"


def _task_result(env_dir: Path, known_hashes: dict[str, str]) -> dict[str, Any]:
    task_id = env_dir.name
    paths = {name: env_dir / name for name in ("verify.py", "mcp_http.py", "verifier_meta.json", "manifest.json")}
    observed: dict[str, str | None] = {}
    missing = []
    for name in ("verify.py", "mcp_http.py", "verifier_meta.json", "manifest.json"):
        digest, error = _file_hash(paths[name])
        observed[name] = digest
        if error:
            missing.append({"path": name, "reason": error})
    base = {"task_id": task_id, "observed_hashes": observed}
    if missing:
        return {**base, "status": "skipped", "reason": "required files unavailable", "details": missing}
    mismatches = [name for name in ("verify.py", "mcp_http.py")
                  if observed[name] != known_hashes.get(name)]
    if mismatches:
        return {**base, "status": "skipped_unknown_hash",
                "reason": "verifier or dispatcher hash is outside this screen's pinned semantics",
                "hash_mismatches": mismatches,
                "expected_hashes": {name: known_hashes.get(name) for name in mismatches}}

    try:
        meta = json.loads(_read_text(paths["verifier_meta.json"]))
        manifest = json.loads(_read_text(paths["manifest.json"]))
    except (json.JSONDecodeError, InspectionError) as error:
        return {**base, "status": "skipped_invalid_metadata", "reason": str(error)}
    if not isinstance(meta, dict) or not isinstance(manifest, dict):
        return {**base, "status": "not_applicable", "reason": "metadata roots are not objects"}

    items = meta.get("items")
    reasons = []
    if meta.get("act") != "none":
        reasons.append("act is not exactly 'none'")
    if not isinstance(items, list) or not items:
        reasons.append("items is not a nonempty list")
    elif any(not isinstance(item, dict) or item.get("method") != "llm"
             or item.get("files") != ["answer.md"] for item in items):
        reasons.append("not all items are LLM-only answer.md items")
    if isinstance(items, list) and any(isinstance(item, dict) and item.get("gate") for item in items):
        reasons.append("metadata contains a gate item")
    if "src_protect" in meta:
        reasons.append("metadata contains src_protect")
    if reasons:
        return {**base, "status": "not_applicable", "reason": "; ".join(reasons)}

    servers = manifest.get("mcp_servers")
    if not isinstance(servers, list):
        return {**base, "status": "unknown_tool_registration", "reason": "manifest mcp_servers is not a list"}
    server_names = {server.get("name") for server in servers if isinstance(server, dict)
                    and isinstance(server.get("name"), str)}
    tools_dir = env_dir / "tools"
    if not tools_dir.is_dir() or tools_dir.is_symlink():
        return {**base, "status": "no_write_found", "reason": "no regular tools directory"}

    writes: list[dict[str, Any]] = []
    unknown_calls: list[dict[str, Any]] = []
    parse_unknown: list[dict[str, str]] = []
    tool_files = sorted(path for path in tools_dir.rglob("*.py")
                        if path.is_file() and not path.is_symlink()
                        and not any(part.startswith("_") for part in path.relative_to(tools_dir).parts))
    modules_considered = []
    for tool_path in tool_files:
        module_name = tool_path.stem
        if module_name not in server_names:
            continue
        relative = tool_path.relative_to(env_dir).as_posix()
        modules_considered.append(relative)
        try:
            source = _read_text(tool_path)
            tree = ast.parse(source, filename=relative)
        except (SyntaxError, InspectionError) as error:
            parse_unknown.append({"tool_file": relative, "reason": str(error)})
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                found, dynamic = _scan_tool_function(node, source)
                for finding in found:
                    writes.append({"tool_file": relative, **finding})
                for finding in dynamic:
                    unknown_calls.append({"tool_file": relative, **finding})

    if not writes:
        status = "unknown_dynamic_sql" if unknown_calls or parse_unknown else "no_write_found"
        return {**base, "status": status,
                "reason": "no confirmed static SQL write literal" if status == "no_write_found"
                          else "dynamic SQL or parse uncertainty prevents a clean conclusion",
                "modules_considered": modules_considered,
                "unknown_dynamic_sql": unknown_calls,
                "parse_unknown": parse_unknown}

    intent_evidence, manual_review = _instruction_evidence(env_dir / "instruction.md")
    metadata_paths = ["verifier_meta.json", "verify.py", "mcp_http.py", "manifest.json", "instruction.md"]
    metadata_paths.extend(sorted({write["tool_file"] for write in writes}))
    candidate = {
        "candidate_id": _stable_candidate_id(task_id),
        "review_signal": True,
        "task_id": task_id,
        "claim": "Metadata marks the task act='none' and scores only answer.md text, while a manifest-exposed public tool function contains a literal SQL write passed to execute/executemany.",
        "metadata_paths": metadata_paths,
        "instruction_evidence": intent_evidence,
        "manual_intent_review_required": manual_review,
        "tool_writes": writes,
        "unknown_dynamic_sql": unknown_calls,
        "parse_unknown": parse_unknown,
        "assumptions": [
            "The pinned mcp_http.py hash has the inspected registration behavior: module-local public functions are exposed; unknown dispatcher semantics are skipped.",
            "The manifest server name maps to tools/<name>.py and the registered function is callable in the deployed environment.",
            "A static SQL write passed to execute/executemany establishes a potential persistent-write path; runtime authorization, guards, and task-tool policy need review.",
            "The shared verifier hash establishes the inspected sidecar scoring path; metadata has no gate and no src_protect field.",
        ],
        "review_notes": "Discovery signal only. It does not establish that the write is reachable for this task, will succeed, or violates policy; manually compare instruction evidence, tool preconditions, and runtime protections.",
    }
    return {**base, "status": "review_signal", "modules_considered": modules_considered,
            "candidate": candidate}


def screen_environment(env_dir: Path, known_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    """Screen one environment; tests may explicitly supply fixture file hashes."""
    return _task_result(Path(env_dir), dict(KNOWN_HASHES if known_hashes is None else known_hashes))


def _repo_revision() -> str | None:
    lock_path = Path(__file__).resolve().parents[2] / "experiments" / "dataset-lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        return lock.get("revision") if isinstance(lock, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def build_report(root: Path, known_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    root = Path(root)
    expected = dict(KNOWN_HASHES if known_hashes is None else known_hashes)
    if not root.is_dir() or root.is_symlink():
        raise InspectionError(f"root is not a regular directory: {root}")
    env_dirs = sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink())
    results = [screen_environment(path, expected) for path in env_dirs]
    candidates = [item["candidate"] for item in results if item.get("status") == "review_signal"]
    inspected = [item for item in results if item.get("status") not in {"skipped", "skipped_unknown_hash", "skipped_invalid_metadata"}]
    skipped = [item for item in results if item not in inspected]
    return {
        "detector_name": DETECTOR_NAME,
        "review_status": "candidates_only",
        "screen_scope": "fully cached immediate child environments under the supplied root",
        "source_revision": _repo_revision() or DATASET_REVISION,
        "root": str(root),
        "known_hashes": expected,
        "dispatcher_registration_evidence": {
            "path": "data/mimo/general/envs/s3k_0988_finance_insurance_zh_t1_rl_005/mcp_http.py",
            "sha256": KNOWN_HASHES["mcp_http.py"],
            "line_start": 191,
            "line_end": 200,
            "quote": "def _public_functions(module) -> list[tuple[str, Any]]:\n    out: list[tuple[str, Any]] = []\n    for name, obj in inspect.getmembers(module, inspect.isfunction):\n        if name.startswith(\"_\"):\n            continue\n        if getattr(obj, \"__module__\", None) != module.__name__:\n            continue\n        out.append((name, obj))\n    out.sort(key=lambda kv: kv[0])\n    return out",
        },
        "environments_discovered": len(env_dirs),
        "environments_inspected": len(inspected),
        "environments_skipped": len(skipped),
        "candidate_count": len(candidates),
        "candidate_ids": [candidate["candidate_id"] for candidate in candidates],
        "inspected_hashes_and_status": inspected,
        "skipped_hashes_and_reasons": skipped,
        "candidates": candidates,
        "limitations": [
            "This is a discovery screen on the supplied local cache, not a held-out effectiveness score or prevalence estimate.",
            "Only the exact pinned verifier and dispatcher hashes are interpreted; any other hash is skipped as unknown.",
            "The SQL recognizer only confirms static INSERT INTO, UPDATE...SET, or DELETE FROM literals passed to execute/executemany; dynamic query expressions are reported as unknown.",
            "No task grader, tool module, server, or endpoint is imported, executed, or invoked.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path,
                        help="root containing cached task environment directories")
    parser.add_argument("--output", required=True, type=Path,
                        help="JSON report destination")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (InspectionError, OSError) as error:
        print(f"readonly screen: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"candidate_count": report["candidate_count"],
                      "candidate_ids": report["candidate_ids"],
                      "environments_discovered": report["environments_discovered"],
                      "environments_inspected": report["environments_inspected"],
                      "environments_skipped": report["environments_skipped"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
