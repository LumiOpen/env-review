#!/usr/bin/env python3
#SBATCH --job-name=mimo-code-static-scan
#SBATCH --partition=amd-tw-verification
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --output=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_scan/logs/static-scan-%j.out
#SBATCH --error=/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26/research/mimo/code_scan/logs/static-scan-%j.err
"""Inspect pinned MiMo Code rows as data. Never imports, extracts, or runs task code.

Output records distinguish row/patch structural errors from regex-based audit
candidates. Archive content is decoded only in memory, with size limits.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
import datetime as dt
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile

import pyarrow
import pyarrow.parquet as pq


# Slurm copies this script into /var/spool/slurmd before execution, so derive
# paths from the shared workspace rather than __file__ on compute nodes.
ROOT = Path("/shared_silo/scratch/rahul.aralikatte@amd.com/random/hackathon26")
DEFAULT_INPUT = ROOT / "research/mimo/inventory/raw/code.parquet"
DEFAULT_OUT = ROOT / "research/mimo/code_scan"
EXPECTED_SHA256 = "3a5310751054dad1ac58cbf407c9234c1bf7775af5f3cc9be57474b39bd2a93b"
REVISION = "e8e81e4945270b6212204bad99de1e598f7fb077"
MAX_PATCH_BYTES = 4 * 1024 * 1024
MAX_B64_CHARS = 2 * 1024 * 1024
MAX_COMPRESSED_BYTES = 1536 * 1024
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_MEMBERS = 100
REVIEWED = {
    "format-code-task-002471", "format-code-task-002908", "format-code-task-002654",
    "format-code-task-002069", "format-code-task-000942", "format-code-task-000048",
}
REQUIRED = ("cwd", "docker_image", "instance_id", "problem_statement", "test_command", "test_patch", "verifier_timeout_sec")
TEST_PATH = re.compile(r"(^|/)(?:test[^/]*|[^/]*_test\.[^/]+|[^/]*\.test\.[^/]+|spec[^/]*)$", re.I)
TEST_INVOKE = re.compile(
    r"\b(?:pytest|py\.test|unittest|nose2|tox|ava|jest|vitest|mocha|r2r|ctest|"
    r"go\s+test|cargo\s+test|mvn\s+test|gradle\s+test|npm\s+(?:test|run\s+test)|"
    r"yarn\s+test|pnpm\s+test|make\s+(?:test|check)|rspec|phpunit|"
    r"dotnet\s+test|swift\s+test|mix\s+test|bundle\s+exec\s+rake\s+test|"
    r"manage\.py\s+test|grunt\s+test|rake\s+test|"
    r"ruby\b[^\n]*\btest/[^\s]+\.rb|python(?:[0-9.]*)?\b[^\n]*\btests?/[^\s]+\.py)\b",
    re.I,
)
FLAG_PATTERNS = {
    "explicit_success_suppression": re.compile(r"(?:\|\|\s*(?:true|:|exit\s+0)\b|\bexit\s+0\b|\bset\s+\+e\b|;\s*true\s*$)", re.I),
    "collection_only": re.compile(r"(?:--collect-only|--listTests\b|--list-tests\b|--dry-run\b|\bgo\s+test\b[^\n]*\s-list\b|\bcargo\s+test\b[^\n]*\s--list\b)", re.I),
    "empty_test_filter": re.compile(r"(?:\bgo\s+test\b[^\n]*\s-run\s+['\"]?\^\$|\bpytest\b[^\n]*\s-k\s+['\"]?\^\$)", re.I),
}
BUILD_REF = re.compile(r"(?:/testbed/)?\.build_env/[A-Za-z0-9._/+-]+")
DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_instance(row: dict) -> tuple[dict | None, list[str]]:
    issues = []
    extra = row.get("extra_info")
    value = extra.get("instance_json") if isinstance(extra, dict) else row.get("instance_json")
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None, ["instance_json_invalid_utf8"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None, ["instance_json_invalid_json"]
    if not isinstance(value, dict):
        return None, ["instance_json_not_object"]
    for key in REQUIRED:
        if not value.get(key):
            issues.append(f"missing_required_{key}")
    return value, issues


def parse_patch(patch: str) -> tuple[list[dict], list[str]]:
    """Read diff headers and added lines; does not apply the patch."""
    issues = []
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        return [], ["inspection_limit_patch_bytes"]
    entries = []
    current = None
    in_hunk = False
    for lineno, line in enumerate(patch.splitlines(), 1):
        match = DIFF_HEADER.fullmatch(line)
        if match:
            current = {"old_path": match.group(1), "new_path": match.group(2),
                       "header_line": lineno, "new_file": False, "added_lines": []}
            entries.append(current)
            in_hunk = False
            continue
        if current is None:
            continue
        if line.startswith("new file mode "):
            current["new_file"] = True
        elif line.startswith("@@ "):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            current["added_lines"].append(line[1:])
    if patch.strip() and not entries:
        issues.append("patch_no_diff_headers")
    for entry in entries:
        if not entry["old_path"] or not entry["new_path"]:
            issues.append("patch_empty_diff_path")
    return entries, issues


def decode_archive(encoded: str) -> tuple[list[dict], dict[str, str], list[str], list[str]]:
    """Bounded base64/gzip/tar read in memory. Never calls extract/extractall."""
    issues, limits, members, text_files = [], [], [], {}
    if len(encoded) > MAX_B64_CHARS:
        return members, text_files, issues, ["archive_base64_cap"]
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return members, text_files, ["archive_invalid_base64"], limits
    if len(compressed) > MAX_COMPRESSED_BYTES:
        return members, text_files, issues, ["archive_compressed_cap"]
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as gz:
            payload = gz.read(MAX_UNCOMPRESSED_BYTES + 1)
            if len(payload) > MAX_UNCOMPRESSED_BYTES:
                return members, text_files, issues, ["archive_uncompressed_cap"]
            if gz.read(1):
                return members, text_files, issues, ["archive_uncompressed_cap"]
    except (OSError, EOFError, gzip.BadGzipFile):
        return members, text_files, ["archive_invalid_gzip"], limits
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tar:
            items = tar.getmembers()
            if len(items) > MAX_MEMBERS:
                return members, text_files, issues, ["archive_member_count_cap"]
            for item in items:
                entry = {"name": item.name, "size": item.size, "type":
                         "file" if item.isfile() else "dir" if item.isdir() else "link" if item.issym() or item.islnk() else "other"}
                members.append(entry)
                if not item.isfile():
                    continue
                if item.size > MAX_MEMBER_BYTES:
                    limits.append(f"archive_member_size_cap:{item.name}")
                    continue
                fileobj = tar.extractfile(item)
                if fileobj is None:
                    issues.append(f"archive_unreadable_member:{item.name}")
                    continue
                data = fileobj.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES:
                    limits.append(f"archive_member_size_cap:{item.name}")
                    continue
                text_files[item.name] = data.decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError, EOFError):
        issues.append("archive_invalid_tar")
    return members, text_files, issues, limits


def flag_context(command: str, invocation: str = "") -> list[dict]:
    """Regex cues are hypotheses, not verdicts about actual command behavior."""
    flags = []
    lines = command.splitlines()
    test_lines = [n for n, line in enumerate(lines, 1) if TEST_INVOKE.search(line)]
    first_test_line = min(test_lines) if test_lines else None
    both_branches = bool(re.search(r"mimo_test_command\.sh\s+base\b", invocation)
                         and re.search(r"mimo_test_command\.sh\s+new\b", invocation))
    branch = None
    branches = {}
    for lineno, line in enumerate(lines, 1):
        hit = re.match(r"^\s*(base|new)\)\s*$", line)
        if hit:
            branch = hit.group(1)
        elif re.match(r"^\s*;;\s*$", line):
            branch = None
        branches[lineno] = branch
    new_branch_has_test = any(TEST_INVOKE.search(line) and branches[n] == "new"
                              for n, line in enumerate(lines, 1))
    for name, pattern in FLAG_PATTERNS.items():
        for lineno, line in enumerate(lines, 1):
            if pattern.search(line):
                if name == "empty_test_filter" and re.search(r"(?:\s-bench(?:=|\s)|--bench\b)", line):
                    # go test -run '^$' deliberately suppresses unit tests when
                    # selecting benchmarks; preserve the fact in command text.
                    continue
                stage = ("base_preflight" if both_branches and new_branch_has_test and branches[lineno] == "base"
                         else "setup_or_cleanup" if name == "explicit_success_suppression"
                         and first_test_line is not None and lineno < first_test_line
                         and re.search(r"(?:dev-switch|pg_ctlcluster|redis-server|createdb|createuser|pip|npm\s+install|apt-get|gem\s+install|bundle\s+install|collectstatic|mkdir|ln\s+-s)", line)
                         else "test_or_unknown")
                flags.append({"flag": name, "line": lineno, "context": line[:500],
                              "context_truncated": len(line) > 500, "stage": stage})
    if command.strip() and not TEST_INVOKE.search(command):
        flags.append({"flag": "no_recognized_test_invocation", "line": None,
                      "context": command[:300]})
    if not command.strip():
        flags.append({"flag": "no_bundled_command", "line": None, "context": ""})
    return flags


def scan_row(row_index: int, row: dict) -> dict:
    instance, schema = parse_instance(row)
    record = {"row_index": row_index, "task_id": None, "structural_errors": schema,
              "inspection_limits": [], "partial_sources": [], "coverage_flags": []}
    if instance is None:
        return record
    record["task_id"] = instance.get("instance_id")
    record["test_command"] = instance.get("test_command")
    patch = instance.get("test_patch")
    if not isinstance(patch, str):
        record["structural_errors"].append("test_patch_not_text")
        return record
    record["patch_sha256"] = hashlib.sha256(patch.encode()).hexdigest()
    entries, patch_issues = parse_patch(patch)
    record["structural_errors"].extend(x for x in patch_issues if not x.startswith("inspection_limit"))
    record["inspection_limits"].extend(x for x in patch_issues if x.startswith("inspection_limit"))
    record["touched_paths"] = list(dict.fromkeys(p for e in entries for p in (e["old_path"], e["new_path"])))
    record["behavioral_test_paths"] = sorted({e["new_path"] for e in entries if TEST_PATH.search(e["new_path"])})
    wrappers = [e for e in entries if e["new_path"].endswith("mimo_test_command.sh")]
    archives = [e for e in entries if e["new_path"].endswith("mimo_build_env.tar.gz.b64")]
    record["wrapper_paths"] = [e["new_path"] for e in wrappers]
    record["archive_paths"] = [e["new_path"] for e in archives]
    record["wrapper_sources"] = [{"path": w["new_path"], "complete_new_file": w["new_file"],
                                   "added_text": "\n".join(w["added_lines"])} for w in wrappers]
    record["wrapper_text"] = "\n".join(w["added_text"] for w in record["wrapper_sources"]) if wrappers else None
    record["partial_sources"].extend(f"modified_wrapper:{w['new_path']}" for w in wrappers if not w["new_file"])
    if len(wrappers) > 1:
        record["structural_errors"].append("duplicate_wrapper_patch")
    if len(archives) > 1:
        record["structural_errors"].append("duplicate_build_archive_patch")
    record["archive_members"] = []
    commands = []
    for archive in archives:
        if not archive["new_file"]:
            record["partial_sources"].append(f"modified_archive:{archive['new_path']}")
            continue
        encoded = "".join(line.strip() for line in archive["added_lines"])
        members, text_files, issues, limits = decode_archive(encoded)
        record["archive_members"].extend(members)
        record["structural_errors"].extend(issues)
        record["inspection_limits"].extend(limits)
        for name, content in text_files.items():
            if name.endswith("test_command.sh"):
                commands.append({"path": name, "text": content})
    record["bundled_commands"] = commands
    if archives and not commands and not record["inspection_limits"] and not record["partial_sources"] and not record["structural_errors"]:
        record["structural_errors"].append("archive_missing_bundled_test_command")
    record["build_env_references"] = sorted(set(BUILD_REF.findall((record["wrapper_text"] or "") +
        "\n" + "\n".join(c["text"] for c in commands))))
    for command in commands:
        for flag in flag_context(command["text"], str(instance.get("test_command", ""))):
            record["coverage_flags"].append({"source": command["path"], **flag})
    if not archives:
        # Most rows use a direct wrapper and no archive. That is expected
        # packaging; the wrapper itself is the command to inspect.
        for wrapper in record["wrapper_sources"]:
            if wrapper["complete_new_file"]:
                for flag in flag_context(wrapper["added_text"], str(instance.get("test_command", ""))):
                    record["coverage_flags"].append({"source": wrapper["path"], **flag})
    record["patch_file_count"] = len(entries)
    return record


def choose_candidates(records: list[dict]) -> list[dict]:
    priority = {"collection_only": 0, "empty_test_filter": 1,
                "explicit_success_suppression": 2, "no_recognized_test_invocation": 3,
                "no_bundled_command": 4, "no_embedded_command_archive": 5}
    ranked = []
    for record in records:
        if record["task_id"] in REVIEWED:
            continue
        labels = {f["flag"] for f in record["coverage_flags"]
                  if f.get("stage") not in ("setup_or_cleanup", "base_preflight")}
        if record["structural_errors"]:
            rank = -1
        elif labels:
            rank = min(priority.get(label, 9) for label in labels)
        else:
            continue
        ranked.append((rank, len(record["structural_errors"]), record["row_index"], record))
    ranked.sort(key=lambda x: (x[0], -x[1], x[2]))
    selected, seen = [], set()
    for _, _, _, record in ranked:
        signature = tuple(sorted(f["flag"] for f in record["coverage_flags"])) or tuple(record["structural_errors"])
        if signature in seen:
            continue
        seen.add(signature)
        selected.append({k: record.get(k) for k in ("task_id", "row_index", "test_command", "touched_paths",
            "behavioral_test_paths", "bundled_commands", "archive_members", "structural_errors", "coverage_flags",
            "inspection_limits")})
        if len(selected) == 6:
            break
    return selected


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--expected-sha256", default=EXPECTED_SHA256)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    actual = sha256_file(args.input)
    if args.expected_sha256 and actual != args.expected_sha256:
        raise SystemExit(f"Input SHA-256 mismatch: {actual}")
    records = []
    parquet = pq.ParquetFile(args.input)
    index = 0
    for batch in parquet.iter_batches(batch_size=128):
        for row in batch.to_pylist():
            try:
                records.append(scan_row(index, row))
            except Exception as exc:
                records.append({"row_index": index, "task_id": str(row.get("instance_id") or ""),
                                "structural_errors": [], "inspection_limits": [], "coverage_flags": [],
                                "scanner_errors": [f"{type(exc).__name__}: {str(exc)[:300]}"]})
            index += 1
    error_counts = Counter(e for r in records for e in r["structural_errors"])
    limit_counts = Counter(e for r in records for e in r["inspection_limits"])
    flag_counts = Counter(f["flag"] for r in records for f in r["coverage_flags"])
    active_flag_counts = Counter(f["flag"] for r in records for f in r["coverage_flags"]
                                 if f.get("stage") not in ("setup_or_cleanup", "base_preflight"))
    scanner_errors = Counter(e for r in records for e in r.get("scanner_errors", []))
    summary = {"schema_version": "mimo-code-static-scan/1", "dataset_revision": REVISION,
        "input": str(args.input), "input_sha256": actual, "scan_time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
        "slurm_resources": {"partition": __import__("os").environ.get("SLURM_JOB_PARTITION"),
            "cpus": __import__("os").environ.get("SLURM_CPUS_PER_TASK"),
            "memory_per_node": __import__("os").environ.get("SLURM_MEM_PER_NODE")},
        "software": {"python": sys.version.split()[0], "pyarrow": pyarrow.__version__},
        "source_only": True, "task_code_executed": False, "rows": len(records),
        "expected_rows": 2602, "row_count_matches_expected": len(records) == 2602,
        "rows_with_scanner_errors": sum(bool(r.get("scanner_errors")) for r in records),
        "scanner_error_counts": dict(scanner_errors),
        "rows_with_structural_errors": sum(bool(r["structural_errors"]) for r in records),
        "structural_error_counts": dict(error_counts),
        "rows_with_inspection_limits": sum(bool(r["inspection_limits"]) for r in records),
        "inspection_limit_counts": dict(limit_counts),
        "rows_with_coverage_flags": sum(bool(r["coverage_flags"]) for r in records),
        "coverage_flag_counts": dict(flag_counts),
        "active_candidate_flag_counts": dict(active_flag_counts),
        "rows_with_wrapper": sum(bool(r.get("wrapper_paths")) for r in records),
        "rows_with_archive": sum(bool(r.get("archive_paths")) for r in records),
        "rows_with_bundled_command": sum(bool(r.get("bundled_commands")) for r in records),
        "rows_with_behavioral_test_path": sum(bool(r.get("behavioral_test_paths")) for r in records),
        "candidate_count": 0,
        "interpretation": "Regex flags are triage cues only. Direct inline wrappers and encoded archives are packaging facts, not defects. Base preflight and setup suppression flags are excluded from candidate ranking. Size caps are scanner limits, not dataset errors."}
    candidates = choose_candidates(records)
    summary["candidate_count"] = len(candidates)
    with (args.out / "rows.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (args.out / "row_failures.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            if record["structural_errors"] or record["inspection_limits"] or record.get("scanner_errors"):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (args.out / "candidates.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
