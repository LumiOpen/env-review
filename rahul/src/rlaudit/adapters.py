"""Normalize immutable task snapshots and run source-only audit checks.

Inputs are data. Dataset patches, archives, verifier code, and commands are
never imported, extracted, or executed by this module.
"""

from __future__ import annotations

import base64
import binascii
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any
import zlib


_REQUIRED_TASK = ("task_id", "domain", "prompt", "metadata", "files")
_MAX_PATCH = 4 * 1024 * 1024
_MAX_ENCODED = 2 * 1024 * 1024
_MAX_COMPRESSED = 1536 * 1024
_MAX_UNCOMPRESSED = 8 * 1024 * 1024
_MAX_MEMBER = 2 * 1024 * 1024
_MAX_MEMBERS = 100
_DIFF = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_TEST_PATH = re.compile(r"(^|/)(?:test[^/]*|[^/]*_test\.[^/]+|[^/]*\.test\.[^/]+|spec[^/]*)$", re.I)
_RUNNER = re.compile(
    r"\b(?:pytest|py\.test|unittest|ava|jest|vitest|mocha|r2r|ctest|"
    r"go\s+test|cargo\s+test|mvn\s+test|gradle\s+test|npm\s+(?:test|run\s+test)|"
    r"yarn\s+test|pnpm\s+test|make\s+(?:test|check)|rspec|phpunit|dotnet\s+test|"
    r"manage\.py\s+test|grunt\s+test|rake\s+test|odoo\b[^\n]*--test-enable|"
    r"ruby\b[^\n]*\btest/[^\s]+\.rb)\b", re.I,
)


def _jsonsafe(value: Any) -> Any:
    """Return JSON primitives only; reject values that cannot be snapshotted."""
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata must be JSON-safe: {exc}") from exc


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path(source_id: str, relative: str, sources: dict[str, Path]) -> tuple[Path, str]:
    if source_id not in sources:
        raise ValueError(f"unknown source ID: {source_id}")
    root = Path(sources[source_id]).resolve(strict=True)
    if not isinstance(relative, str):
        raise ValueError("file path must be a string")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"file path escapes source {source_id}: {relative}")
    if root.is_file():
        if relative not in ("", ".", root.name):
            raise ValueError(f"file source {source_id} has no child path: {relative}")
        return root, root.name
    target = (root / str(rel)).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"file path escapes or is not a file: {source_id}:{relative}")
    return target, target.relative_to(root).as_posix()


def _file_ref(source_id: str, relative: str, sources: dict[str, Path], cache: dict[Path, str]) -> dict:
    target, path = _source_path(source_id, relative, sources)
    if target not in cache:
        cache[target] = _hash(target)
    return {"source": source_id, "path": path, "sha256": cache[target]}


def _observation(task_id: str, summary: str, *, detail: dict | None = None) -> dict:
    return {"task_id": task_id, "summary": summary, "detail": detail or {}}


def _parse_instance(row: dict) -> tuple[dict | None, str | None]:
    extra = row.get("extra_info")
    value = extra.get("instance_json") if isinstance(extra, dict) else row.get("instance_json")
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None, "instance_json is not UTF-8"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            return None, f"instance_json is invalid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return None, "instance_json is not an object"
    return _jsonsafe(value), None


def _archive_members(encoded: str) -> tuple[list[dict], list[dict], list[str]]:
    """Decode bounded gzip/tar bytes in memory, never extracting members."""
    members: list[dict] = []
    commands: list[dict] = []
    issues: list[str] = []
    if len(encoded) > _MAX_ENCODED:
        return members, commands, ["archive encoded-size cap exceeded"]
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return members, commands, ["archive invalid base64"]
    if len(compressed) > _MAX_COMPRESSED:
        return members, commands, ["archive compressed-size cap exceeded"]
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            payload = stream.read(_MAX_UNCOMPRESSED + 1)
            if len(payload) > _MAX_UNCOMPRESSED or stream.read(1):
                return members, commands, ["archive uncompressed-size cap exceeded"]
    except (OSError, EOFError, zlib.error):
        return members, commands, ["archive invalid gzip"]
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            items = archive.getmembers()
            if len(items) > _MAX_MEMBERS:
                return members, commands, ["archive member-count cap exceeded"]
            for member in items:
                kind = "file" if member.isfile() else "dir" if member.isdir() else "link" if member.issym() or member.islnk() else "other"
                members.append({"name": member.name, "size": member.size, "type": kind})
                if not member.isfile() or not member.name.endswith("test_command.sh"):
                    continue
                if member.size > _MAX_MEMBER:
                    issues.append(f"archive member-size cap exceeded: {member.name}")
                    continue
                stream = archive.extractfile(member)  # file object only; no filesystem extraction
                if stream is None:
                    issues.append(f"archive member unreadable: {member.name}")
                    continue
                data = stream.read(_MAX_MEMBER + 1)
                if len(data) > _MAX_MEMBER:
                    issues.append(f"archive member-size cap exceeded: {member.name}")
                else:
                    commands.append({"path": member.name, "text": data.decode("utf-8", "replace")})
    except (tarfile.TarError, OSError, EOFError):
        issues.append("archive invalid tar")
    return members, commands, issues


def _patch_analysis(patch: Any) -> dict:
    result = {"touched_paths": [], "behavioral_test_paths": [], "wrappers": [],
              "archive_members": [], "commands": [], "issues": [], "partial_sources": []}
    if not isinstance(patch, str):
        result["issues"].append("test_patch is not text")
        return result
    if len(patch.encode("utf-8", "replace")) > _MAX_PATCH:
        result["issues"].append("patch-size cap exceeded")
        return result
    entries = []
    current = None
    in_hunk = False
    for lineno, line in enumerate(patch.splitlines(), 1):
        match = _DIFF.fullmatch(line)
        if match:
            current = {"old": match.group(1), "new": match.group(2), "new_file": False,
                       "added": [], "line": lineno}
            entries.append(current)
            in_hunk = False
        elif current is not None:
            if line.startswith("new file mode "):
                current["new_file"] = True
            elif line.startswith("@@ "):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                current["added"].append(line[1:])
    if patch.strip() and not entries:
        result["issues"].append("patch has no diff headers")
    result["touched_paths"] = list(dict.fromkeys(p for e in entries for p in (e["old"], e["new"])))
    result["behavioral_test_paths"] = sorted({e["new"] for e in entries if _TEST_PATH.search(e["new"])})
    for entry in entries:
        path = entry["new"]
        if path.endswith("mimo_test_command.sh"):
            wrapper = {"path": path, "complete": entry["new_file"], "text": "\n".join(entry["added"])}
            result["wrappers"].append(wrapper)
            if not entry["new_file"]:
                result["partial_sources"].append(path)
        if path.endswith("mimo_build_env.tar.gz.b64"):
            if not entry["new_file"]:
                result["partial_sources"].append(path)
                continue
            encoded = "".join(line.strip() for line in entry["added"])
            members, commands, issues = _archive_members(encoded)
            result["archive_members"].extend(members)
            result["commands"].extend(commands)
            result["issues"].extend(issues)
    has_archive = any(e["new"].endswith("mimo_build_env.tar.gz.b64") for e in entries)
    if not result["commands"] and not has_archive:
        result["commands"].extend({"path": w["path"], "text": w["text"]}
                                  for w in result["wrappers"] if w["complete"])
    return result


def _select(tasks: list[dict], adapter: dict) -> tuple[list[dict], dict]:
    requested = adapter.get("ids")
    if requested is not None:
        if not isinstance(requested, list) or any(not isinstance(x, str) for x in requested):
            raise ValueError("adapter.ids must be a list of task IDs")
        if len(set(requested)) != len(requested):
            raise ValueError("adapter.ids contains duplicates")
        unknown = sorted(set(requested) - {t["task_id"] for t in tasks if isinstance(t.get("task_id"), str)})
        if unknown:
            raise ValueError(f"unknown task IDs: {unknown}")
    limit = adapter.get("limit")
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("adapter.limit must be a nonnegative integer")
    ordered = sorted(enumerate(tasks), key=lambda item: (str(item[1].get("task_id")), item[0]))
    chosen = [task for _, task in ordered if requested is None or task["task_id"] in requested]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen, {"total": len(tasks), "selected": len(chosen), "skipped": len(tasks) - len(chosen)}


def _mimo_subset_rows(root: Path, source_id: str, sources: dict[str, Path],
                      cache: dict[Path, str], domain: str) -> tuple[list[dict], list[dict]]:
    """Read bounded parquet batches as inert data, retaining source-row evidence."""
    if not root.is_file():
        raise ValueError(f"mimo_{domain} source must be a parquet file")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(f"mimo_{domain} requires pyarrow") from exc
    ref = _file_ref(source_id, root.name, sources, cache)
    expected_data_source = {"cyber": "arvo", "webdev": "blackbox/webdev", "music": "music"}[domain]
    tasks: list[dict] = []
    observations: list[dict] = []
    native_ids: dict[str, list[int]] = {}
    row_index = 0
    for batch in pq.ParquetFile(root).iter_batches(batch_size=128):
        for raw in batch.to_pylist():
            task_id = f"mimo-{domain}-{row_index:06d}"
            if not isinstance(raw, dict):
                observations.append({**_observation(task_id, "parquet row is not an object",
                                                    detail={"row_index": row_index}), "status": "error"})
                raw = {}
            try:
                row = _jsonsafe(raw)
            except ValueError as exc:
                observations.append({**_observation(task_id, "parquet row contains non-JSON values",
                                                    detail={"row_index": row_index, "error": str(exc)[:200]}),
                                     "status": "error"})
                row = {}
                for key, value in raw.items():
                    try:
                        row[str(key)] = _jsonsafe(value)
                    except ValueError:
                        row[str(key)] = None
            if row.get("data_source") != expected_data_source:
                observations.append({**_observation(task_id, "data_source disagrees with adapter kind",
                                                    detail={"row_index": row_index,
                                                            "actual": row.get("data_source"),
                                                            "expected": expected_data_source}),
                                     "status": "error"})
            extra = row.get("extra_info")
            if not isinstance(extra, dict):
                observations.append({**_observation(task_id, "extra_info is not an object",
                                                    detail={"row_index": row_index}), "status": "error"})
                extra = {}
            source_key = "src_id" if domain == "music" else "instance_id"
            source_id_value = extra.get(source_key)
            if not isinstance(source_id_value, str) or not source_id_value:
                observations.append({**_observation(task_id, f"extra_info.{source_key} is missing or invalid",
                                                    detail={"row_index": row_index}), "status": "error"})
                source_id_value = None
            else:
                native_ids.setdefault(source_id_value, []).append(row_index)
            messages = row.get("prompt")
            prompt_parts: list[str] = []
            if isinstance(messages, list):
                prompt_parts = [item["content"] for item in messages
                                if isinstance(item, dict) and isinstance(item.get("content"), str)]
            if not isinstance(messages, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("role"), str)
                or not isinstance(item.get("content"), str) for item in messages
            ):
                observations.append({**_observation(task_id, "prompt messages have invalid structure",
                                                    detail={"row_index": row_index}), "status": "error"})
            prompt = "\n\n".join(prompt_parts)
            if not prompt.strip():
                observations.append({**_observation(task_id, "prompt messages contain no text",
                                                    detail={"row_index": row_index}), "status": "error"})
            if domain == "music":
                instance = {}
            else:
                try:
                    instance, issue = _parse_instance(row)
                except ValueError as exc:
                    instance, issue = None, f"instance_json contains non-JSON values: {exc}"
                if issue:
                    observations.append({**_observation(task_id, issue,
                                                        detail={"row_index": row_index}), "status": "error"})
                instance = instance or {}
            tasks.append({"task_id": task_id, "domain": domain, "prompt": prompt,
                          "metadata": {"row_index": row_index, "row": row,
                                       "extra_info": extra, "instance": instance,
                                       "source_id": source_id_value},
                          "files": {"row_source": ref}})
            row_index += 1
    for native_id, indices in native_ids.items():
        if len(indices) < 2:
            continue
        detail = {"source_id": native_id, "count": len(indices),
                  "row_indices": indices[:32], "row_indices_truncated": len(indices) > 32}
        for index in indices:
            observations.append(_observation(f"mimo-{domain}-{index:06d}",
                                             "repeated native source ID", detail=detail))
    return tasks, observations


def normalize(adapter: dict, sources: dict[str, Path]) -> dict:
    """Normalize local JSONL or supported MiMo source snapshots."""
    if not isinstance(adapter, dict) or not isinstance(sources, dict):
        raise ValueError("adapter and sources must be mappings")
    kind, source_id = adapter.get("kind"), adapter.get("source")
    if kind not in {"local_jsonl", "mimo_code", "mimo_general", "mimo_cyber", "mimo_webdev", "mimo_music"}:
        raise ValueError(f"unsupported adapter kind: {kind}")
    if not isinstance(source_id, str) or source_id not in sources:
        raise ValueError(f"unknown adapter source ID: {source_id}")
    root = Path(sources[source_id]).resolve(strict=True)
    tasks: list[dict] = []
    observations: list[dict] = []
    cache: dict[Path, str] = {}
    if kind == "local_jsonl":
        if not root.is_file():
            raise ValueError("local_jsonl source must be a file")
        with root.open(encoding="utf-8") as stream:
            for lineno, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL line {lineno}: {exc.msg}") from exc
                if not isinstance(task, dict):
                    raise ValueError(f"JSONL line {lineno} is not an object")
                if not isinstance(task.get("task_id"), str) or not task["task_id"]:
                    raise ValueError(f"JSONL line {lineno} task_id must be a nonempty string")
                files = task.get("files", {})
                if not isinstance(files, dict):
                    raise ValueError(f"JSONL line {lineno} files must be a mapping")
                mapped = {}
                for role, ref in files.items():
                    if not isinstance(ref, dict) or not isinstance(ref.get("source"), str):
                        raise ValueError(f"JSONL line {lineno} invalid file reference: {role}")
                    actual = _file_ref(ref["source"], ref.get("path", ""), sources, cache)
                    if ref.get("sha256") and ref["sha256"] != actual["sha256"]:
                        raise ValueError(f"JSONL line {lineno} hash mismatch: {role}")
                    mapped[str(role)] = actual
                tasks.append({"task_id": task.get("task_id"), "domain": task.get("domain"),
                              "prompt": task.get("prompt"), "metadata": _jsonsafe(task.get("metadata", {})),
                              "files": mapped})
    elif kind == "mimo_code":
        if not root.is_file():
            raise ValueError("mimo_code source must be a parquet file")
        try:
            import pyarrow.parquet as pq  # optional; only Code adapter needs it
        except ImportError as exc:
            raise RuntimeError("mimo_code requires pyarrow") from exc
        ref = _file_ref(source_id, root.name, sources, cache)
        row_index = 0
        for batch in pq.ParquetFile(root).iter_batches(batch_size=128):
            for row in batch.to_pylist():
                instance, issue = _parse_instance(row)
                task_id = str((instance or {}).get("instance_id") or row.get("instance_id") or f"row-{row_index:06d}")
                if issue:
                    observations.append(_observation(task_id, issue, detail={"row_index": row_index}))
                instance = instance or {}
                analysis = _patch_analysis(instance.get("test_patch"))
                for problem in analysis["issues"]:
                    observations.append(_observation(task_id, problem, detail={"row_index": row_index}))
                tasks.append({"task_id": task_id, "domain": "code",
                              "prompt": str(instance.get("problem_statement") or ""),
                              "metadata": {"row_index": row_index, "instance": instance,
                                           "patch_analysis": analysis},
                              "files": {"row_source": ref}})
                row_index += 1
    elif kind in {"mimo_cyber", "mimo_webdev", "mimo_music"}:
        tasks, observations = _mimo_subset_rows(root, source_id, sources, cache, kind.removeprefix("mimo_"))
    else:
        if not root.is_dir():
            raise ValueError("mimo_general source must be a directory")
        known = ("instruction.md", "verifier_meta.json", "manifest.json")
        bundles = [root] if any((root / name).exists() for name in known) else sorted(p for p in root.iterdir() if p.is_dir())
        for bundle in bundles:
            task_id = bundle.name
            files = {}
            metadata = {}
            prompt = ""
            for role, filename in (("instruction", "instruction.md"),
                                   ("verifier_meta", "verifier_meta.json"),
                                   ("manifest", "manifest.json")):
                path = bundle / filename
                if not path.is_file():
                    observations.append(_observation(task_id, f"missing {filename}", detail={"role": role}))
                    continue
                files[role] = _file_ref(source_id, path.relative_to(root).as_posix(), sources, cache)
                if role == "instruction":
                    prompt = path.read_text(encoding="utf-8")
                else:
                    try:
                        metadata[role] = _jsonsafe(json.loads(path.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        observations.append(_observation(task_id, f"invalid {filename}", detail={"error": str(exc)[:200]}))
            tasks.append({"task_id": task_id, "domain": "general", "prompt": prompt,
                          "metadata": metadata, "files": files})
    selected, coverage = _select(tasks, adapter)
    selected_ids = {t["task_id"] for t in selected}
    return {"tasks": selected,
            "observations": [o for o in observations if o["task_id"] in selected_ids],
            "coverage": {"kind": kind, **coverage}}


def _finding(check: str, task_id: str, status: str, summary: str,
             evidence: list[dict], limitations: list[str] | None = None) -> dict:
    return {"check_id": check, "task_id": task_id, "status": status,
            "evidence_level": "static", "summary": summary,
            "evidence": evidence, "limitations": limitations or []}


def _schema(tasks: list[dict]) -> list[dict]:
    findings = []
    ids = Counter(t.get("task_id") for t in tasks if isinstance(t, dict) and isinstance(t.get("task_id"), str))
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            findings.append(_finding("schema", f"row-{index}", "error", "Task is not an object",
                                     [{"index": index}]))
            continue
        task_id = task.get("task_id") if isinstance(task.get("task_id"), str) else f"row-{index}"
        missing = [key for key in _REQUIRED_TASK if key not in task]
        bad = [key for key in ("task_id", "domain", "prompt") if key in task and not isinstance(task[key], str)]
        bad += [key for key in ("metadata", "files") if key in task and not isinstance(task[key], dict)]
        if missing or bad:
            findings.append(_finding("schema", task_id, "error", "Invalid normalized task fields",
                                     [{"missing": missing, "invalid_types": bad, "index": index}]))
        if isinstance(task.get("task_id"), str) and ids[task["task_id"]] > 1:
            findings.append(_finding("schema", task_id, "error", "Duplicate task ID",
                                     [{"task_id": task.get("task_id"), "count": ids[task.get("task_id")]}]))
            ids[task.get("task_id")] = 0
        for role, ref in (task.get("files") or {}).items() if isinstance(task.get("files"), dict) else []:
            if not isinstance(ref, dict) or any(not isinstance(ref.get(k), str) or not ref[k]
                                                    for k in ("source", "path", "sha256")):
                findings.append(_finding("schema", task_id, "error", "Invalid normalized file reference",
                                         [{"role": role}]))
    return findings


def _valid_task_schema(task: Any) -> bool:
    """Guard domain checks from malformed normalized records."""
    return (isinstance(task, dict)
            and all(key in task for key in _REQUIRED_TASK)
            and all(isinstance(task[key], str) for key in ("task_id", "domain", "prompt"))
            and isinstance(task["metadata"], dict)
            and isinstance(task["files"], dict)
            and all(isinstance(ref, dict) and all(isinstance(ref.get(key), str) and ref[key]
                                                        for key in ("source", "path", "sha256"))
                    for ref in task["files"].values()))


def _code_static(task: dict) -> list[dict]:
    metadata = task.get("metadata") or {}
    instance = metadata.get("instance") or {}
    if not isinstance(instance, dict):
        return [_finding("code_static", task["task_id"], "error", "Instance metadata is not an object",
                         [{"source": "metadata.instance"}])]
    analysis = metadata.get("patch_analysis") or _patch_analysis(instance.get("test_patch"))
    if not isinstance(analysis, dict):
        return [_finding("code_static", task["task_id"], "error", "Patch analysis is not an object",
                         [{"source": "metadata.patch_analysis"}])]
    if not isinstance(analysis.get("issues", []), list) or not isinstance(analysis.get("commands", []), list):
        return [_finding("code_static", task["task_id"], "error", "Patch analysis has invalid lists",
                         [{"source": "metadata.patch_analysis"}])]
    evidence = [{"source": "metadata.instance.test_patch", "touched_paths": analysis.get("touched_paths", [])}]
    findings = []
    for issue in analysis.get("issues", []):
        findings.append(_finding("code_static", task["task_id"], "observation",
                                 f"Patch/archive inspection issue: {issue}", evidence,
                                 ["Inspection limits or malformed data require source review; no verifier was run."]))
    commands = analysis.get("commands", [])
    if any(not isinstance(command, dict) or not isinstance(command.get("text"), str)
           for command in commands):
        return findings + [_finding("code_static", task["task_id"], "error", "Patch commands are malformed",
                                    [{"source": "metadata.patch_analysis.commands"}])]
    if not commands:
        return findings
    text = "\n".join(c.get("text", "") for c in commands)
    lines = text.splitlines()
    test_lines = [line for line in lines if _RUNNER.search(line)]
    if not test_lines:
        findings.append(_finding("code_static", task["task_id"], "observation",
                                 "No recognized test runner in inspected command text",
                                 [{"source": "patch command", "excerpt": text[:500]}],
                                 ["Custom runners and shell branches may still execute tests."]))
    elif test_lines and all(re.search(r"--collect-only|--listTests|--dry-run|(?:^|\s)-run\s+['\"]\^\$['\"]", line)
                            for line in test_lines):
        findings.append(_finding("code_static", task["task_id"], "candidate",
                                 "Recognized test commands appear collection-only or select no unit tests",
                                 [{"source": "patch command", "lines": test_lines[:8]}],
                                 ["Other shell branches or benchmark flags may change effective execution."]))
    suppressed = [line.strip() for line in test_lines if re.search(r"\|\|\s*(?:true|:|exit\s+0)\b", line)]
    if suppressed:
        findings.append(_finding("code_static", task["task_id"], "candidate",
                                 "A recognized test command masks nonzero exit status",
                                 [{"source": "patch command", "lines": suppressed[:8]}],
                                 ["Static shell matching does not prove this branch is reached."]))
    return findings


def _general_contract(task: dict) -> list[dict]:
    meta = (task.get("metadata") or {}).get("verifier_meta") or {}
    if not isinstance(meta, dict):
        return [_finding("general_contract", task["task_id"], "error", "Verifier metadata is not an object",
                         [{"source": "verifier_meta.json"}])]
    items = meta.get("items")
    if not isinstance(items, list):
        return [_finding("general_contract", task["task_id"], "observation", "No rubric item list in verifier metadata",
                         [{"source": "verifier_meta.json", "field": "items"}],
                         ["This may be a non-rubric General task."])]
    findings = []
    counts = Counter(item.get("id") for item in items if isinstance(item, dict) and isinstance(item.get("id"), str))
    for rubric_id, count in counts.items():
        if count > 1:
            findings.append(_finding("general_contract", task["task_id"], "error", "Duplicate rubric ID",
                                     [{"source": "verifier_meta.json", "rubric_id": rubric_id, "count": count}]))
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            findings.append(_finding("general_contract", task["task_id"], "error", "Rubric item lacks an ID",
                                     [{"source": "verifier_meta.json", "item_index": index}]))
            continue
        if item.get("method") == "rule" and not item.get("fn"):
            findings.append(_finding("general_contract", task["task_id"], "candidate", "Rule rubric lacks function name",
                                     [{"source": "verifier_meta.json", "rubric_id": item["id"], "field": "fn"}],
                                     ["Runtime behavior depends on the deployed grader branch."]))
        weight = item.get("weight", 1)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
            findings.append(_finding("general_contract", task["task_id"], "candidate", "Rubric has invalid weight",
                                     [{"source": "verifier_meta.json", "rubric_id": item["id"], "weight": weight}],
                                     ["The effective grader may validate or override weights."]))
    return findings


def run_checks(tasks: list[dict], checks: list[str]) -> dict:
    """Run static checks; unsupported domains are counted as skipped."""
    available = {"schema", "code_static", "general_contract", "mimo_contract"}
    unknown = sorted(set(checks) - available)
    if unknown:
        raise ValueError(f"unknown checks: {unknown}")
    findings = []
    coverage = {}
    for check in checks:
        eligible = skipped = 0
        reasons = Counter()
        eligible_domains: set[str] = set()
        for task in tasks:
            if check == "schema":
                eligible += 1
                continue
            if not _valid_task_schema(task):
                skipped += 1
                reasons["invalid_task_schema"] += 1
                continue
            supported = ({"code"} if check == "code_static" else
                         {"general"} if check == "general_contract" else
                         {"cyber", "webdev", "music"})
            if task["domain"] not in supported:
                skipped += 1
                reasons["unsupported_domain"] += 1
                continue
            eligible += 1
            eligible_domains.add(task["domain"])
            if check == "code_static":
                findings.extend(_code_static(task))
            elif check == "general_contract":
                findings.extend(_general_contract(task))
            else:
                from .mimo_contracts import check_task
                findings.extend(check_task(task))
        if check == "schema":
            findings.extend(_schema(tasks))
        coverage[check] = {"eligible": eligible, "evaluated": eligible, "skipped": skipped,
                           "skip_reasons": dict(reasons)}
        if check == "mimo_contract":
            from .mimo_contracts import coverage_limits
            coverage[check]["limitations"] = coverage_limits(eligible_domains)
    return {"findings": findings, "coverage": coverage}
