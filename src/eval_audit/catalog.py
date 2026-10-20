"""Validate collaborative YAML records and build a deterministic discovery index.

validate_catalog(root) returns errors shaped {path, location, message}; an empty
list means the catalog passes these structural checks. Locations are JSON
pointers where available. build_index(root) raises ValueError for an invalid
catalog. Neither API adjudicates evidence or runs a reproducer or corpus code.

Evidence/task paths are portable relative source paths; their targets need not
be cached locally. The index groups identical supplied task references at the
same source revision and keeps all review statuses explicit.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
import yaml


_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
_TASK_FIELDS = ("id", "config", "split", "row_index", "path")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader with duplicate mapping keys rejected, including merge clashes."""

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.nodes.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "expected a YAML mapping node", node.start_mark,
            )
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while reading a mapping", node.start_mark,
                    "mapping keys must be scalar strings", key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while reading a mapping", node.start_mark,
                    f"duplicate YAML key {key!r}", key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _pointer(parts) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _json_issue(value, path=(), ancestors=frozenset()):
    """Reject YAML-only types, nonfinite numbers, and cyclic aliases before JSON export."""
    if value is None or isinstance(value, (str, bool, int)):
        return None
    if isinstance(value, float):
        return None if math.isfinite(value) else (path, "Nonfinite numbers are not JSON-compatible.")
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            return path, "Recursive YAML aliases are not supported."
        ancestors = ancestors | {id(value)}
        entries = value.items() if isinstance(value, dict) else enumerate(value)
        for key, item in entries:
            if isinstance(value, dict) and not isinstance(key, str):
                return path, "YAML mapping keys must be strings."
            issue = _json_issue(item, (*path, key), ancestors)
            if issue:
                return issue
        return None
    return path, f"YAML value of type {type(value).__name__} is not JSON-compatible; quote text scalars."


def _safe_source_path(value: str) -> bool:
    return bool(value.strip()) and value != "." and not (
        PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
        or ".." in value.split("/") or "\\" in value or "\0" in value or "://" in value
    )


def _load_catalog(root: Path):
    root = Path(root).resolve()
    errors, datasets, findings = [], [], []

    def error(path, message, location=""):
        relative = path.relative_to(root).as_posix() if isinstance(path, Path) else path
        errors.append({"path": relative, "location": location, "message": message})

    if not root.is_dir():
        error(".", "Catalog root is not an existing directory.")
        return datasets, findings, errors

    validators = {}
    for kind in ("dataset", "finding"):
        schema = json.loads((_SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema, format_checker=FormatChecker())

    def read_record(path, kind):
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                error(path, "Catalog records must be regular files inside the repository.")
                return None
            # The custom loader inherits only SafeLoader constructors; no object execution.
            record = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
            issue = _json_issue(record)
            if issue:
                error(path, issue[1], _pointer(issue[0]))
                return None
        except (OSError, UnicodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
            error(path, f"Cannot read safe YAML: {exc}")
            return None
        schema_errors = sorted(validators[kind].iter_errors(record), key=lambda exc: (_pointer(exc.path), exc.message))
        for exc in schema_errors:
            error(path, exc.message, _pointer(exc.path))
        return None if schema_errors else record

    env_root = root / "env"
    manifest_paths = sorted(env_root.glob("*/*/dataset.yaml"))
    finding_paths = sorted({*env_root.glob("*/*/findings/*.yaml"), *env_root.glob("*/*/findings/*.yml")})
    directories = sorted({path.parent for path in manifest_paths} | {path.parent.parent for path in finding_paths})
    dataset_ids, finding_ids = {}, {}
    for directory in directories:
        manifest_path = directory / "dataset.yaml"
        if not manifest_path.is_file():
            error(manifest_path, "A finding directory requires its dataset.yaml manifest.")
            dataset = None
        else:
            dataset = read_record(manifest_path, "dataset")
        if dataset is not None:
            expected_id = f"hf:{directory.parent.name}/{directory.name}"
            if dataset["id"] != expected_id:
                error(manifest_path, f"Dataset identity must match its directory: expected {expected_id!r}.", "/id")
            if dataset["id"] in dataset_ids:
                error(manifest_path, f"Duplicate dataset id {dataset['id']!r}; first declared in {dataset_ids[dataset['id']]}.", "/id")
            dataset_ids.setdefault(dataset["id"], manifest_path.relative_to(root).as_posix())
            url = urlsplit(dataset["source"]["url"])
            expected_path = "/datasets/" + dataset["id"][3:]
            if (url.scheme != "https" or url.netloc != "huggingface.co" or url.path.rstrip("/") != expected_path
                    or url.query or url.fragment):
                error(manifest_path, "Source URL must identify the same Hugging Face dataset as id.", "/source/url")
            datasets.append((manifest_path.relative_to(root).as_posix(), dataset))
        for finding_path in (path for path in finding_paths if path.parent.parent == directory):
            if finding_path.suffix != ".yaml":
                error(finding_path, "Finding records must use the .yaml extension.")
            finding = read_record(finding_path, "finding")
            if finding is None:
                continue
            if finding_path.stem != finding["id"]:
                error(finding_path, "Finding filename must match its id.", "/id")
            if finding["id"] in finding_ids:
                error(finding_path, f"Duplicate finding id {finding['id']!r}; first declared in {finding_ids[finding['id']]}.", "/id")
            finding_ids.setdefault(finding["id"], finding_path.relative_to(root).as_posix())
            if dataset is not None and finding["dataset"] != dataset["id"]:
                error(finding_path, "Finding dataset reference does not match its dataset manifest.", "/dataset")
            task_ids = set()
            for index, task in enumerate(finding["tasks"]):
                if task["id"] in task_ids:
                    error(finding_path, f"Duplicate task id {task['id']!r} within finding.", f"/tasks/{index}/id")
                task_ids.add(task["id"])
                if "path" in task and not _safe_source_path(task["path"]):
                    error(finding_path, "Task path must be a safe relative source path.", f"/tasks/{index}/path")
            for index, evidence in enumerate(finding["evidence"]):
                if not _safe_source_path(evidence["source"]):
                    error(finding_path, "Evidence source must be a safe relative source path.", f"/evidence/{index}/source")
                if "line_end" in evidence and evidence["line_end"] < evidence["line_start"]:
                    error(finding_path, "line_end must be greater than or equal to line_start.", f"/evidence/{index}/line_end")
            findings.append((finding_path.relative_to(root).as_posix(), finding))
    errors.sort(key=lambda item: (item["path"], item["location"], item["message"]))
    return datasets, findings, errors


def validate_catalog(root: Path) -> list[dict]:
    """Return structural validation errors; an empty list means structurally valid."""
    return _load_catalog(root)[2]


def _format_errors(errors: list[dict]) -> str:
    return "\n".join(f"{error['path']} {error['location'] or '/'}: {error['message']}" for error in errors)


def build_index(root: Path) -> dict:
    """Index every review status; raise ValueError without writing if records are invalid."""
    datasets, findings, errors = _load_catalog(root)
    if errors:
        raise ValueError(_format_errors(errors))
    index = {"schema_version": "1", "datasets": [], "findings": [], "tasks": []}
    for path, dataset in sorted(datasets, key=lambda row: row[1]["id"]):
        index["datasets"].append({"id": dataset["id"], "review_status": dataset["review_status"],
                                  "source": dataset["source"], "task_identity": dataset["task_identity"], "path": path})
    tasks = {}
    for path, finding in sorted(findings, key=lambda row: (row[1]["dataset"], row[1]["id"])):
        summary = {key: finding[key] for key in ("id", "dataset", "title", "status", "category")}
        summary.update(tasks=sorted(finding["tasks"], key=lambda task: task["id"]),
                       source_revision=finding["revision"], path=path)
        index["findings"].append(summary)
        for task in finding["tasks"]:
            key = (finding["dataset"], finding["revision"], *(task.get(field) for field in _TASK_FIELDS))
            entry = tasks.setdefault(key, {"dataset": finding["dataset"], "source_revision": finding["revision"],
                                           **task, "findings": []})
            entry["findings"].append({"id": finding["id"], "status": finding["status"],
                                      "category": finding["category"], "source_revision": finding["revision"]})
    index["tasks"] = sorted(tasks.values(), key=lambda task: (
        task["dataset"], task["id"], task["source_revision"], task.get("config", ""), task.get("split", ""),
        task.get("row_index", -1), task.get("path", ""),
    ))
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "index"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=Path("."))
        if name == "index":
            command.add_argument("--output", type=Path, default=Path("reports/index.json"))
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_catalog(args.root)
            if errors:
                raise ValueError(_format_errors(errors))
            print("Catalog is structurally valid.")
        else:
            index = build_index(args.root)
            output = args.output if args.output.is_absolute() else args.root / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            print(f"Wrote {output}.")
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
