"""Conservative static candidate screen; corpus code is only parsed, never run.

Evidence paths are relative to the candidate's environment. Missing inventory
assets are distinct from uncached assets. No SQL is evaluated or inferred, and
an empty candidate list says nothing about task validity.
"""

from __future__ import annotations

import argparse
import ast
import builtins
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import posixpath
import sys


DETECTOR_VERSION = "structural-1"
CORE_FILES = ("manifest.json", "verifier_meta.json", "verify.py")


class InspectionError(Exception):
    """The local cache does not support the requested inspection."""


def _evidence(path: str, text: str, start: int = 0, end: int | None = None) -> dict:
    """Return complete, exact source lines around character offsets."""
    start_line = text.count("\n", 0, start) + 1
    end_line = text.count("\n", 0, max(start, (end or start + 1) - 1)) + 1
    lines = text.splitlines()
    start_line = min(start_line, max(1, len(lines)))
    end_line = min(end_line, max(1, len(lines)))
    return {"path": path, "line_start": start_line, "line_end": end_line,
            "quote": "\n".join(lines[start_line - 1:end_line])}


def _line_evidence(path: str, text: str, line: int) -> dict:
    offset = sum(len(part) for part in text.splitlines(keepends=True)[:max(0, line - 1)])
    return _evidence(path, text, offset)


def _json_spans(text: str, start: int = 0) -> dict | list:
    """Locate members with stdlib JSON decoding, including minified documents."""
    decoder = json.JSONDecoder()
    while start < len(text) and text[start].isspace():
        start += 1
    is_object = text[start] == "{"
    result = {} if is_object else []
    pos = start + 1
    while True:
        while pos < len(text) and (text[pos].isspace() or text[pos] == ","):
            pos += 1
        if text[pos] in "}]":
            return result
        if is_object:
            key, pos = decoder.raw_decode(text, pos)
            while text[pos].isspace() or text[pos] == ":":
                pos += 1
        value_start = pos
        _, pos = decoder.raw_decode(text, pos)
        if is_object:
            result[key] = (value_start, pos)
        else:
            result.append((value_start, pos))


def _constant_evidence(path: str, text: str, start: int = 0) -> list[dict]:
    """Locate nonstandard constant values without matching text inside strings."""
    while text[start].isspace():
        start += 1
    if text[start] in "[{":
        spans = _json_spans(text, start)
        values = spans.values() if isinstance(spans, dict) else spans
        return [evidence for first, _ in values for evidence in _constant_evidence(path, text, first)]
    if any(text.startswith(token, start) for token in ("NaN", "Infinity", "-Infinity")):
        return [_evidence(path, text, start)]
    return []


def _namespace(tree: ast.Module) -> tuple[set[str], bool]:
    """Potential module bindings and whether dynamic creation stays unresolved."""
    names = set(dir(builtins)) | {"Path"}  # the self-contained runner supplies Path
    dynamic = False

    def visit(node):
        nonlocal dynamic
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            # Decorators/default expressions/classes may perform arbitrary work.
            expressions = list(node.decorator_list)
            if isinstance(node, ast.ClassDef):
                dynamic = True
            else:
                expressions += list(node.args.defaults) + [v for v in node.args.kw_defaults if v]
            if any(isinstance(child, ast.Call) for expr in expressions for child in ast.walk(expr)):
                dynamic = True
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    dynamic = True
                else:
                    names.add(alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name))
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        if isinstance(node, ast.Call):
            dynamic = True
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in tree.body:
        visit(statement)
    return names, dynamic


def _number(value):
    try:
        return float(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _inventory_source(env: Path, source: str) -> str | None:
    if not source or source.startswith("/") or "\\" in source:
        return None
    path = posixpath.normpath(f"general/envs/{env.name}/{source}")
    return None if path.startswith("../") else path


def screen_environment(env_dir: Path, inventory_paths: set[str] | None = None) -> list[dict]:
    """Screen a cached MiMo general environment and return unadjudicated candidates.

    Requires readable core files, not the complete uploaded workspace. Inventory
    paths, when supplied, must be the full pinned dataset's repository-relative
    paths. Without that inventory, absent local uploads/helpers remain unknown.
    """
    env_dir = Path(env_dir)
    missing = [name for name in CORE_FILES if not (env_dir / name).is_file() or (env_dir / name).is_symlink()]
    if missing:
        raise InspectionError("Missing regular local core files: " + ", ".join(missing))
    candidates = []
    texts, documents, trees = {}, {}, {}

    def add(detector, claim, evidence, assumptions, category="defect_candidate", severity="medium"):
        candidates.append({"detector_id": detector, "task_id": env_dir.name,
                           "category": category, "claim": claim, "evidence": evidence,
                           "assumptions": assumptions, "severity": severity})

    files = sorted(p for p in env_dir.rglob("*") if p.is_file() and not p.is_symlink()
                   and p.suffix in {".json", ".py"})
    for path in files:
        relative = path.relative_to(env_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise InspectionError(f"Cannot read {relative}: {error}") from error
        texts[relative] = text
        if path.suffix == ".json":
            constants = []

            def nonstandard(token):
                constants.append(token)
                return float(token)

            try:
                documents[relative] = json.loads(text, parse_constant=nonstandard)
            except json.JSONDecodeError as error:
                line = getattr(error, "lineno", 1)
                add("invalid_json", f"{relative} is not parseable JSON: {error}",
                    [_line_evidence(relative, text, line)], ["The cached source matches the pinned source."], severity="high")
                continue
            except (ValueError, RecursionError) as error:
                raise InspectionError(f"Local JSON parser could not inspect {relative}: {error}") from error
            if constants:
                add("invalid_json", f"{relative} contains nonstandard JSON constants: {', '.join(sorted(set(constants)))}.",
                    _constant_evidence(relative, text), ["Strict JSON readers reject NaN and Infinity; Python's default reader accepts them."])
        else:
            try:
                trees[relative] = ast.parse(text, filename=relative)
            except SyntaxError as error:
                add("invalid_python", f"{relative} cannot be parsed as Python: {error}",
                    [_line_evidence(relative, text, getattr(error, "lineno", 1) or 1)],
                    [f"The target interpreter uses syntax compatible with Python {sys.version_info.major}.{sys.version_info.minor}."], severity="high")
            except (ValueError, RecursionError) as error:
                raise InspectionError(f"Local Python parser could not inspect {relative}: {error}") from error

    meta = documents.get("verifier_meta.json")
    meta_text = texts["verifier_meta.json"]
    if "verifier_meta.json" in documents:
        if not isinstance(meta, dict):
            add("malformed_metadata", "verifier_meta.json must contain an object.",
                [_evidence("verifier_meta.json", meta_text)], ["The verifier reads metadata with mapping.get()."])
        else:
            members = _json_spans(meta_text)
            items = meta.get("items", [])
            if not isinstance(items, list):
                add("malformed_metadata", "Metadata items is not an array.",
                    [_evidence("verifier_meta.json", meta_text, *members["items"])],
                    ["Each rubric item is expected to be a mapping in an array."])
                items = []
            spans = _json_spans(meta_text, members["items"][0]) if items else []
            item_evidence = [_evidence("verifier_meta.json", meta_text, *span) for span in spans]
            valid = []
            ids = defaultdict(list)
            for index, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                    add("malformed_metadata", f"Rubric item {index} is not an object with a nonempty string id.",
                        [item_evidence[index]], ["The verifier indexes rubric results by item id."])
                    continue
                valid.append((item, item_evidence[index]))
                ids[item["id"]].append(item_evidence[index])
            for item_id, evidence in ids.items():
                if len(evidence) > 1:
                    add("duplicate_item_id", f"Item id {item_id!r} occurs {len(evidence)} times.", evidence,
                        ["The verifier stores results in a dictionary keyed by id, so these items share a result slot."])

            code = meta.get("check_code", "")
            code_evidence = _evidence("verifier_meta.json", meta_text, *members.get("check_code", (0, 1)))
            code_tree = None
            if not isinstance(code, str):
                add("malformed_metadata", "Metadata check_code is not a string.", [code_evidence],
                    ["The self-contained verifier concatenates check_code with helper source."])
            else:
                try:
                    code_tree = ast.parse(code, filename="verifier_meta.json:check_code")
                except SyntaxError as error:
                    add("invalid_check_code", f"check_code has invalid Python at decoded line {getattr(error, 'lineno', 1) or 1}: {error}",
                        [code_evidence], ["Embedded check_code is interpreted as Python source."], severity="high")
                except (ValueError, RecursionError) as error:
                    raise InspectionError(f"Local Python parser could not inspect check_code: {error}") from error
            helper_cached = "_helpers.py" in texts
            helper_known_absent = inventory_paths is not None and f"general/envs/{env_dir.name}/_helpers.py" not in inventory_paths
            namespace_known = code_tree is not None and ("_helpers.py" in trees or (not helper_cached and helper_known_absent))
            bindings, dynamic = _namespace(code_tree) if code_tree else (set(), True)
            if "_helpers.py" in trees:
                helper_names, helper_dynamic = _namespace(trees["_helpers.py"])
                bindings |= helper_names
                dynamic |= helper_dynamic
            for item, evidence in valid:
                if item.get("method") != "rule" and not item.get("gate"):
                    continue
                fn = item.get("fn")
                if not isinstance(fn, str) or not fn.strip():
                    add("rule_function_missing", f"Rule/gate item {item['id']!r} has no usable fn field.", [evidence],
                        ["The verifier invokes the callable named by fn."])
                elif fn.isidentifier() and namespace_known and not dynamic and fn not in bindings:
                    add("rule_function_missing", f"Rule item {item['id']!r} names {fn!r}, absent from the static check/helper namespace.",
                        [evidence, code_evidence], ["No external runtime injection adds this name to the rule namespace."])

            atoms = [(item, ev) for item, ev in valid if not item.get("gate")]
            numbers = []
            for item, evidence in atoms:
                value = item.get("weight", 1)
                number = _number(value)
                numbers.append(number)
                if number is None:
                    detector, claim = "weight_malformed", "cannot be converted to a numeric weight"
                elif not math.isfinite(number):
                    detector, claim = "weight_nonfinite", "has a nonfinite weight"
                elif number < 0:
                    detector, claim = "weight_negative", "has a negative weight"
                else:
                    continue
                add(detector, f"Item {item['id']!r} {claim} ({value!r}).", [evidence],
                    ["This non-gate item participates in a weighted mean using float(weight)."])
            if atoms and all(number == 0 for number in numbers):
                add("weights_all_zero", "All non-gate rubric weights are zero.", [ev for _, ev in atoms],
                    ["The verifier uses these non-gate weights as its scoring denominator."])
            fractional = [(item, ev) for item, ev in atoms if item.get("tier") != "sanity" and "weight" in item
                          and (number := _number(item["weight"])) is not None and 0 < number < 1]
            for item, evidence in atoms:
                if item.get("tier") == "sanity" and "weight" not in item and fractional:
                    add("implicit_sanity_weight", f"Non-gate sanity item {item['id']!r} omits weight while substantive items have fractional weights.",
                        [evidence, *[ev for _, ev in fractional]],
                        ["If this item is scored with the verifier's default weight of 1, it can outweigh individual substantive items.",
                         "Author intent and impact require review; this is not automatically invalid."], category="review_signal", severity="low")

    manifest = documents.get("manifest.json")
    if isinstance(manifest, dict) and inventory_paths is not None:
        upload_groups = [manifest.get("uploads", [])]
        verifier = manifest.get("verifier")
        if isinstance(verifier, dict):
            upload_groups.append(verifier.get("uploads", []))
        for uploads in upload_groups:
            if not isinstance(uploads, list):
                continue
            for upload in uploads:
                source = upload.get("source") if isinstance(upload, dict) else None
                if not isinstance(source, str):
                    continue
                expected = _inventory_source(env_dir, source)
                if expected is None or (env_dir / source).exists():
                    continue
                if expected in inventory_paths or any(p.startswith(expected.rstrip("/") + "/") for p in inventory_paths):
                    continue
                text = texts["manifest.json"]
                needle = json.dumps(source, ensure_ascii=False)
                start = text.find(needle)
                if start < 0:
                    start = text.find(json.dumps(source))
                add("upload_source_absent", f"Manifest upload source {source!r} is absent locally and from the pinned repository inventory ({expected}).",
                    [_evidence("manifest.json", text, max(0, start))],
                    ["The supplied inventory is complete for the pinned source revision.",
                     "The upload source is expected to exist before setup rather than be generated externally."])
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inventory = None
    if args.inventory:
        raw = json.loads(args.inventory.read_text(encoding="utf-8"))
        inventory = {item["rfilename"] for item in raw["siblings"]}
    if not args.root.is_dir():
        parser.error("--root must be a directory")
    envs = sorted(path for path in args.root.iterdir() if path.is_dir() and not path.is_symlink())
    candidates, errors, inspected = [], [], []
    for env in envs:
        try:
            candidates.extend(screen_environment(env, inventory))
            inspected.append(env.name)
        except InspectionError as error:
            errors.append({"task_id": env.name, "error": str(error)})
    by_detector = dict(sorted(Counter(c["detector_id"] for c in candidates).items()))
    by_task = dict(sorted(Counter(c["task_id"] for c in candidates).items()))
    report = {"detector_version": DETECTOR_VERSION, "review_status": "candidates_only",
              "root": str(args.root), "inventory": str(args.inventory) if args.inventory else None,
              "environments_discovered": len(envs), "environments_inspected": len(inspected),
              "environments_uninspectable": len(errors), "inspected_task_ids": inspected,
              "candidate_count": len(candidates), "signals_by_detector": by_detector,
              "signals_by_task": by_task, "errors": errors, "candidates": candidates,
              "limitations": ["Selected local cache; no population prevalence estimate or negative labels.",
                              "Corpus code and SQL are never executed; SQL/schema relationships are not screened.",
                              "Dynamic names, external imports, and unavailable helpers prevent missing-name conclusions.",
                              "Weight effects depend on the runtime scoring path; agent/vision suppression is not inferred.",
                              "Python syntax is checked against the local interpreter grammar.",
                              "Without a complete inventory, local upload absence is not a defect signal."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("detector_version", "environments_inspected", "environments_uninspectable",
                                                  "candidate_count", "signals_by_detector")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
