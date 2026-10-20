"""Immutable, relocatable input snapshots and tamper-evident run artifacts."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    os.replace(temporary, path)


def engine_fingerprint():
    base = Path(__file__).resolve().parent
    files = [{"path": p.name, "sha256": sha256(p)} for p in sorted(base.glob("*.py"))]
    return hashlib.sha256(canonical(files)).hexdigest(), files


def walk(path):
    """Yield paths incrementally so entry limits apply before a full-tree sort."""
    stack = [os.scandir(path)]
    try:
        while stack:
            try:
                entry = next(stack[-1])
            except StopIteration:
                stack.pop().close()
                continue
            yield Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                stack.append(os.scandir(entry.path))
    finally:
        for iterator in stack:
            iterator.close()


def entries(path, budget):
    """Refuse symlinks and special files, including ones inside directories."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Symlink inputs are unsupported: {path}")
    if not path.exists():
        raise ValueError(f"Missing source: {path}")
    kind = "directory" if path.is_dir() else "file"
    candidates = walk(path) if kind == "directory" else [path]
    result = []
    for item in candidates:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Symlink inputs are unsupported: {item}")
        if stat.S_ISDIR(info.st_mode):
            budget["files"] += 1
            if budget["files"] > budget["max_files"]:
                raise ValueError("Source snapshot exceeds configured file/byte budget")
            result.append({"path":item.relative_to(path).as_posix(), "kind":"directory", "bytes":0})
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Special-file inputs are unsupported: {item}")
        budget["files"] += 1
        budget["bytes"] += info.st_size
        if budget["files"] > budget["max_files"] or budget["bytes"] > budget["max_bytes"]:
            raise ValueError("Source snapshot exceeds configured file/byte budget")
        result.append({"path": item.relative_to(path).as_posix() if kind == "directory" else item.name,
                       "kind":"file", "executable":bool(info.st_mode & 0o111),
                       "bytes": info.st_size, "sha256": sha256(item)})
    result.sort(key=lambda item:item["path"])
    fingerprint = hashlib.sha256(canonical(result)).hexdigest() if kind == "directory" else result[0]["sha256"]
    return kind, result, fingerprint


def runtime_versions(dependencies):
    versions = {"python": platform.python_version()}
    for name, expected in sorted(dependencies.items()):
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"Required dependency {name}=={expected} is not installed") from exc
        if actual != expected:
            raise ValueError(f"Dependency mismatch for {name}: expected {expected}, got {actual}")
        versions[name] = actual
    # Record installed transitive requirements of declared distributions. Replay
    # promotes these observed versions into explicit pins in pipeline.lock.json.
    pending = list(dependencies)
    visited = set()
    while pending:
        name = pending.pop()
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in visited:
            continue
        visited.add(normalized)
        for requirement in importlib.metadata.requires(name) or []:
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9_.-]*", requirement)
            if not match:
                continue
            dependency = match.group()
            try:
                actual = importlib.metadata.version(dependency)
            except importlib.metadata.PackageNotFoundError:
                continue  # Uninstalled extras/platform-specific dependencies.
            versions.setdefault(dependency, actual)
            pending.append(dependency)
    return versions


def freeze(config, config_path, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Output already exists; choose a new run directory: {output}")
    versions = runtime_versions(config["execution"]["dependencies"])
    config_root = Path(config_path).resolve().parent
    budget = {"files": 0, "bytes": 0,
              "max_files": config["execution"]["max_source_files"],
              "max_bytes": config["execution"]["max_source_bytes"]}
    scanned = []
    for source in config["sources"]:
        original = config_root / source["path"]
        if original.is_symlink():
            raise ValueError(f"Symlink source is unsupported: {original}")
        original = original.resolve()
        if original.is_dir() and output.is_relative_to(original):
            raise ValueError("Run output must not be nested inside a directory source")
        kind, files, digest = entries(original, budget)
        if source.get("sha256") and source["sha256"] != digest:
            raise ValueError(f"SHA-256 mismatch for source {source['id']}")
        scanned.append((source, original, kind, files, digest))
    output.mkdir(parents=True)
    locked = json.loads(json.dumps(config))
    locked["execution"]["dependencies"] = {name:version for name,version in versions.items() if name != "python"}
    source_records = []
    for index, (source, original, kind, files, digest) in enumerate(scanned):
        destination = output / "inputs" / source["id"]
        if kind == "directory":
            destination = destination / (original.name or "source")
        destination.mkdir(parents=True)
        for item in files:
            source_file = original / item["path"] if kind == "directory" else original
            target = destination / item["path"]
            if item["kind"] == "directory":
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target)
            target.chmod(0o755 if item["executable"] else 0o644)
            if sha256(target) != item["sha256"]:
                raise ValueError(f"Source changed during snapshot: {source_file}")
        snap = destination if kind == "directory" else destination / files[0]["path"]
        locked["sources"][index] = {"id": source["id"], "path": snap.relative_to(output).as_posix(), "sha256": digest}
        source_records.append({"id": source["id"], "kind": kind, "sha256": digest,
                               "snapshot": snap.relative_to(output).as_posix(),
                               "files": files, "origin": str(original)})
    engine_hash, engine_files = engine_fingerprint()
    engine_directory = output / "engine" / "rlaudit"
    engine_directory.mkdir(parents=True)
    for item in engine_files:
        target = engine_directory / item["path"]
        shutil.copyfile(Path(__file__).resolve().parent / item["path"], target)
        if sha256(target) != item["sha256"]:
            raise ValueError("Audit engine changed during snapshot")
    helper = output / "replay.sh"
    helper.write_text('#!/bin/sh\nset -eu\n'
                      'RLAUDIT_RUN=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                      'export PYTHONDONTWRITEBYTECODE=1\n'
                      'export PYTHONPATH="$RLAUDIT_RUN/engine"\n'
                      'exec python -B -m rlaudit replay "$RLAUDIT_RUN" "$@"\n')
    helper.chmod(0o755)
    fingerprint_config = json.loads(json.dumps(locked))
    for source in fingerprint_config["sources"]:
        source.pop("path")
    descriptors = [{k:s[k] for k in ["id", "kind", "files"]} for s in source_records]
    fingerprint = hashlib.sha256(canonical({"config": fingerprint_config, "engine": engine_hash, "versions": versions, "source_entries":descriptors})).hexdigest()
    lock = {"schema_version": "rlaudit.lock/v1", "fingerprint": fingerprint,
            "engine_sha256": engine_hash, "engine_files": engine_files, "engine_snapshot":"engine",
            "runtime_versions": versions, "sources": source_records,
            "snapshot_bytes": budget["bytes"], "snapshot_files": budget["files"]}
    write_json(output / "pipeline.lock.json", locked)
    write_json(output / "inputs.lock.json", lock)
    return locked, lock, {source["id"]: output / source["path"] for source in locked["sources"]}


def verify_inputs(run):
    run = Path(run).resolve()
    lock = json.loads((run / "inputs.lock.json").read_text())
    config = json.loads((run / "pipeline.lock.json").read_text())
    fingerprint_config = json.loads(json.dumps(config))
    for source in fingerprint_config["sources"]:
        source.pop("path")
    descriptors = [{k:s[k] for k in ["id", "kind", "files"]} for s in lock["sources"]]
    fingerprint = hashlib.sha256(canonical({"config": fingerprint_config,
        "engine": lock["engine_sha256"], "versions": lock["runtime_versions"], "source_entries":descriptors})).hexdigest()
    if fingerprint != lock["fingerprint"]:
        raise ValueError("Locked configuration fingerprint mismatch")
    configured = {s["id"]: s for s in config["sources"]}
    for source in lock["sources"]:
        item = configured.get(source["id"])
        if not item or item["path"] != source["snapshot"] or item["sha256"] != source["sha256"]:
            raise ValueError("Source lock does not match configuration")
        path = run / source["snapshot"]
        if not path.resolve().is_relative_to(run / "inputs"):
            raise ValueError("Source snapshot escapes the run")
        _, files, digest = entries(path, {"files":0,"bytes":0,"max_files":config["execution"]["max_source_files"],"max_bytes":config["execution"]["max_source_bytes"]})
        if files != source["files"] or digest != source["sha256"]:
            raise ValueError(f"Source snapshot changed: {source['id']}")
    return lock, config


def seal(run):
    run = Path(run)
    artifacts = []
    for path in sorted(run.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink artifact is unsupported: {path}")
        if path.is_file() and path != run / "artifacts.json":
            artifacts.append({"path": path.relative_to(run).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size})
    write_json(run / "artifacts.json", {"schema_version":"rlaudit.artifacts/v1", "files":artifacts})


def verify(run):
    run = Path(run).resolve()
    lock, _ = verify_inputs(run)
    manifest = json.loads((run / "artifacts.json").read_text())
    if any(path.is_symlink() for path in run.rglob("*")):
        raise ValueError("Run contains a symlink artifact")
    known = set()
    for item in manifest["files"]:
        path = run / item["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(run) or not path.is_file() or sha256(path) != item["sha256"]:
            raise ValueError(f"Artifact missing or changed: {item['path']}")
        known.add(item["path"])
    actual = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file() and p != run / "artifacts.json"}
    if actual != known:
        raise ValueError("Run contains added or missing artifacts")
    return {"status":"verified", "fingerprint":lock["fingerprint"], "artifacts":len(known)}
