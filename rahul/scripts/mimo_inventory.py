#!/usr/bin/env python3
"""Source-only inventory of pinned MiMo Code and General rows.

Downloads only code.parquet, general/train.parquet, image-mapping.jsonl and the
non-recursive General env directory listing at the pinned dataset revision.
Parquet JSON fields are parsed as data; nothing from the dataset is imported or run.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pyarrow.parquet as pq
import requests

REVISION = "e8e81e4945270b6212204bad99de1e598f7fb077"
REPO = "XiaomiMiMo/MiMo-V2.6-RL-oss"
BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "research/mimo/inventory"
RAW = OUT / "raw"
CANDIDATES = OUT / "candidates"
HF = "https://huggingface.co"
EXPECTED_SHA256 = {
    "code.parquet": "3a5310751054dad1ac58cbf407c9234c1bf7775af5f3cc9be57474b39bd2a93b",
    "general_train.parquet": "9bfdc8b05d2bf2cb9e89815443d35507e4be30368aebf70928421795c10259b9",
    "image-mapping.jsonl": "661c3c51b02682b6ef77e9f3b27fa1b813f799bf345b6621a8a56d5581f45440",
}
FILES = {
    "code.parquet": f"{HF}/datasets/{REPO}/resolve/{REVISION}/code.parquet",
    "general_train.parquet": f"{HF}/datasets/{REPO}/resolve/{REVISION}/general/train.parquet",
    "image-mapping.jsonl": f"{HF}/datasets/{REPO}/resolve/{REVISION}/image-mapping.jsonl",
}
LISTING_URL = f"{HF}/api/datasets/{REPO}/tree/{REVISION}/general/envs"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_idempotent(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"Refusing to overwrite differing artifact: {path}")
        return
    path.write_bytes(data)


def fetch(url: str, path: Path, *, params=None, expected_sha256=None) -> bytes:
    if path.exists():
        data = path.read_bytes()
    else:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        data = response.content
    actual = digest(data)
    if expected_sha256 and actual != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {actual}")
    write_idempotent(path, data)
    return data


def fetch_directory_listing(path: Path) -> bytes:
    if path.exists():
        data = path.read_bytes()
        json.loads(data)
        return data
    entries, url, params = [], LISTING_URL, {"recursive": "false", "expand": "false"}
    seen = set()
    while url:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise RuntimeError("Unexpected HF tree response; expected a list")
        entries.extend(page)
        next_url = response.links.get("next", {}).get("url")
        if not next_url:
            break
        if next_url in seen:
            raise RuntimeError("HF tree pagination loop detected")
        seen.add(next_url)
        url, params = next_url, None
    data = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    write_idempotent(path, data)
    return data


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def flatten_strings(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten_strings(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten_strings(v, f"{prefix}[{i}]")
    elif isinstance(obj, str):
        yield prefix, obj


def json_value(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def parse_instance(row):
    extra = row.get("extra_info")
    val = json_value(extra.get("instance_json")) if isinstance(extra, dict) else json_value(row.get("instance_json"))
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {"_decoded_value": parsed}
        except (ValueError, TypeError):
            return None
    return None


def prompt_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item.get("content", "")) for item in value if isinstance(item, dict))
    return ""


def first_text(row, instance, keys):
    for source in (row, instance or {}):
        for key in keys:
            val = source.get(key)
            text = prompt_text(val)
            if text:
                return text
    return ""


def stable_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def image_fields(obj, prefix=""):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if str(key).lower() in {"docker_image", "image", "image_name", "container_image"} and isinstance(value, str):
                found.append({"field": path, "value": value})
            else:
                found.extend(image_fields(value, path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(image_fields(value, f"{prefix}[{index}]"))
    return found


def get_id(row, inst):
    for src in (row, row.get("extra_info") if isinstance(row.get("extra_info"), dict) else {}, inst or {}):
        for k in ("task_id", "id", "instance_id", "uid"):
            if src.get(k) is not None:
                return str(src[k])
    return None


def decode_row(row):
    return {str(k): json_value(v) for k, v in row.items()}


def language_framework_hints(row, inst):
    strings = " ".join(v.lower() for _, v in flatten_strings(inst or {}))
    strings += " " + " ".join(str(v).lower() for k, v in row.items() if isinstance(v, str))
    langs = [("python", r"\bpython\b|\.py\b"), ("javascript", r"javascript|\bnode(?:\.js)?\b|\.js\b"),
             ("typescript", r"typescript|\.tsx?\b"), ("go", r"\bgolang\b|\.go\b"),
             ("rust", r"\bcargo\b|\.rs\b"), ("java", r"\bmaven\b|\bgradle\b|\.java\b"),
             ("c/c++", r"\bcmake\b|\bmakefile\b|\.c\b|\.cpp\b")]
    lang = next((name for name, pat in langs if re.search(pat, strings)), "unknown")
    frameworks = [(n, p) for n, p in [("django", r"django"), ("flask", r"flask"), ("fastapi", r"fastapi"),
                  ("react", r"react"), ("vue", r"vue"), ("express", r"express"), ("spring", r"spring"),
                  ("pytest", r"pytest"), ("nextjs", r"next\.js|nextjs")]]
    fw = next((n for n, p in frameworks if re.search(p, strings)), "unknown")
    return lang, fw


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    blobs = {}
    for name, url in FILES.items():
        blobs[name] = fetch(url, RAW / name, expected_sha256=EXPECTED_SHA256[name])
    listing = fetch_directory_listing(RAW / "general-env-directories.json")
    listing_rows = json.loads(listing)
    dirs = sorted({Path(x["path"]).name for x in listing_rows if x.get("type") == "directory" and x.get("path", "").startswith("general/envs/")})
    mapping_rows = [json.loads(line) for line in blobs["image-mapping.jsonl"].decode("utf-8").splitlines() if line.strip()]
    mapping_lookup = {}
    mapping_keys = set()
    for m in mapping_rows:
        keys = [str(v) for k, v in m.items() if isinstance(v, (str, int)) and any(t in k.lower() for t in ("image", "id", "path", "file"))]
        for k in keys:
            mapping_lookup[k] = m
            mapping_keys.add(k)

    inv_path = OUT / "rows.jsonl"
    code_table = pq.read_table(RAW / "code.parquet")
    gen_table = pq.read_table(RAW / "general_train.parquet")
    inventory = []
    code_candidates = []
    dup_tracker = {}
    prompt_tracker = {}
    domain_stats = {}
    gen_refs = {}
    for domain, table in (("code", code_table), ("general", gen_table)):
        for idx, arrowrow in enumerate(table.to_pylist()):
            row = decode_row(arrowrow)
            inst = parse_instance(row)
            fields = sorted(k for k, v in row.items() if v is not None)
            task_id = get_id(row, inst)
            prompt = first_text(row, inst, ("prompt", "question", "instruction", "query", "input"))
            prompt_hash = digest(prompt.encode("utf-8")) if prompt else None
            image_refs = image_fields(row) + image_fields(inst or {})
            images = sorted({ref["value"] for ref in image_refs})
            mapped = {im: mapping_lookup.get(im) for im in images}
            code_meta = {}
            if domain == "code":
                patch = (inst or {}).get("test_patch")
                command = (inst or {}).get("test_command")
                code_meta = {"test_patch_present": bool(patch), "test_patch_size_bytes": len(patch.encode("utf-8")) if isinstance(patch, str) else (len(patch) if isinstance(patch, bytes) else 0),
                             "test_command_present": bool(command), "test_command_size_bytes": len(command.encode("utf-8")) if isinstance(command, str) else (len(command) if isinstance(command, bytes) else 0)}
                if isinstance(patch, str) and patch.strip():
                    lang, framework = language_framework_hints(row, inst)
                    code_candidates.append((code_meta["test_patch_size_bytes"], lang, framework, idx, row, inst))
            else:
                refs = sorted({directory_id for _, value in flatten_strings(inst or {}) for directory_id in dirs if directory_id in value})
                gen_refs[str(task_id or idx)] = refs
            ids = dup_tracker.setdefault(domain, {})
            if task_id is not None:
                ids[task_id] = ids.get(task_id, 0) + 1
            if prompt_hash:
                pids = prompt_tracker.setdefault(domain, {})
                pids[prompt_hash] = pids.get(prompt_hash, 0) + 1
            record = {"domain": domain, "row_index": idx, "row_id": task_id, "row": row, "prompt_length_chars": len(prompt),
                      "prompt_sha256": prompt_hash, "fields_present": fields, "instance_json_decoded": inst,
                      "image_references": image_refs, "image_mapping": mapped, **code_meta}
            if domain == "general":
                record["environment_references"] = refs
                record["environment_reference_status"] = "matched_directory" if refs else ("terminal_bench_row_without_general_env_directory" if (inst or {}).get("dataset_type") == "terminal_bench" else "non_terminal_row_without_directory_unresolved")
            inventory.append(record)
        domain_stats[domain] = {"rows": table.num_rows, "columns": table.column_names}
    write_idempotent(inv_path, "".join(stable_json(rec) + "\n" for rec in inventory).encode("utf-8"))

    # Greedy deterministic diversity under smallest nonempty test patches.
    selected = []
    selected_groups = set()
    remaining = sorted(code_candidates, key=lambda x: (x[0], x[3]))
    while remaining and len(selected) < 6:
        choice_i = next((i for i, x in enumerate(remaining) if (x[1], x[2]) not in selected_groups), 0)
        x = remaining.pop(choice_i)
        selected.append(x)
        selected_groups.add((x[1], x[2]))
    for rank, (size, lang, fw, idx, row, inst) in enumerate(selected, 1):
        path = CANDIDATES / f"candidate_{rank:02d}.json"
        candidate_data = json.dumps({"selection_rank": rank, "selection_reason": "greedy smallest nonempty test_patch with heuristic language/framework hints used to prefer diversity; deterministic row-index tie-break", "selection_bias": "Concentrates on unusually small explicit test patches and heuristic language/framework keyword cues (unverified, may reflect generic prose); excludes empty patches and may underrepresent larger or less explicit task families. This is a triage sample, not representative and not a vulnerability claim.", "row_index": idx, "language_hint": lang, "framework_hint": fw, "hints_unverified": True, "row": row, "instance_json_decoded": inst}, ensure_ascii=False, indent=2, default=str) + "\n"
        write_idempotent(path, candidate_data.encode("utf-8"))

    mapping_all_ids = set(mapping_keys)
    code_ids = {ref["value"] for r in inventory if r["domain"] == "code" for ref in r["image_references"]}
    gen_ids = {ref["value"] for r in inventory if r["domain"] == "general" for ref in r["image_references"]}
    def size_summary(values):
        ordered = sorted(values)
        return {"count": len(ordered), "min_bytes": ordered[0] if ordered else 0,
                "median_bytes": ordered[len(ordered)//2] if ordered else 0,
                "max_bytes": ordered[-1] if ordered else 0}
    def character_summary(values):
        ordered = sorted(values)
        return {"count": len(ordered), "min_chars": ordered[0] if ordered else 0,
                "median_chars": ordered[len(ordered)//2] if ordered else 0,
                "max_chars": ordered[-1] if ordered else 0}
    code_rows = [r for r in inventory if r["domain"] == "code"]
    general_rows = [r for r in inventory if r["domain"] == "general"]
    rows_sha256 = digest(inv_path.read_bytes())
    candidate_files = sorted(CANDIDATES.glob("candidate_*.json"))
    summary = {"schema_version": "mimo-source-inventory/1", "revision": REVISION, "source_only": True, "upstream_code_executed": False,
               "downloaded": {name: {"bytes": len(data), "sha256": digest(data), "path": str(RAW / name)} for name, data in blobs.items()},
               "directory_listing": {"bytes": len(listing), "sha256": digest(listing), "path": str(RAW / "general-env-directories.json")},
               "domains": domain_stats,
               "code_test_fields": {"test_patch_present_rows": sum(r.get("test_patch_present", False) for r in code_rows), "test_patch_nonempty_rows": sum(r.get("test_patch_size_bytes", 0) > 0 for r in code_rows), "test_patch_size_bytes": size_summary([r.get("test_patch_size_bytes", 0) for r in code_rows]), "test_command_present_rows": sum(r.get("test_command_present", False) for r in code_rows), "test_command_nonempty_rows": sum(r.get("test_command_size_bytes", 0) > 0 for r in code_rows), "test_command_size_bytes": size_summary([r.get("test_command_size_bytes", 0) for r in code_rows])},
               "prompt_length_chars": {d: character_summary([r["prompt_length_chars"] for r in inventory if r["domain"] == d]) for d in ("code", "general")},
               "general_directory_count": len(dirs), "general_rows_minus_directories": domain_stats["general"]["rows"] - len(dirs),
               "general_reconciliation": {"rows_matching_directory_id": sum(bool(r.get("environment_references")) for r in inventory if r["domain"] == "general"), "rows_with_no_directory_id_by_known_type": {status: sum(r.get("environment_reference_status") == status for r in inventory if r["domain"] == "general") for status in sorted({r.get("environment_reference_status") for r in inventory if r["domain"] == "general"})}, "directory_ids_without_row_match": sorted(set(dirs) - {ref for vals in gen_refs.values() for ref in vals}), "matched_directory_reference_count": sum(len(v) for v in gen_refs.values()), "rows_by_dataset_type": {kind: sum((r.get("instance_json_decoded") or {}).get("dataset_type") == kind for r in inventory if r["domain"] == "general") for kind in sorted({(r.get("instance_json_decoded") or {}).get("dataset_type", "unknown") for r in inventory if r["domain"] == "general"})}},
               "image_mapping_rows": len(mapping_rows), "image_mapping_keys_count": len(mapping_all_ids),
               "image_mapping_coverage": {"code_references": len(code_ids), "code_mapped": len(code_ids & mapping_all_ids), "code_unmapped": sorted(code_ids - mapping_all_ids), "general_references": len(gen_ids), "general_mapped": len(gen_ids & mapping_all_ids), "general_unmapped": sorted(gen_ids - mapping_all_ids)},
               "duplicates": {d: {"duplicate_ids": {k:v for k,v in dup_tracker[d].items() if v>1}, "duplicate_id_count": sum(v>1 for v in dup_tracker[d].values()), "duplicate_prompt_hashes": {k:v for k,v in prompt_tracker.get(d,{}).items() if v>1}, "duplicate_prompt_hash_count": sum(v>1 for v in prompt_tracker.get(d,{}).values())} for d in dup_tracker},
               "candidate_selection": [{"rank": i+1, "row_index": x[3], "test_patch_size_bytes": x[0], "language_hint": x[1], "framework_hint": x[2], "hints_unverified": True} for i,x in enumerate(selected)],
               "outputs": {"rows_jsonl": str(inv_path), "rows_sha256": rows_sha256, "candidates": [{"path": str(p), "sha256": digest(p.read_bytes())} for p in candidate_files], "candidate_dir": str(CANDIDATES)},
               "reconciliation_note": "Of 989 General rows, 925 general_agent rows match s3k directory IDs and all 925 listed directories are matched. The remaining 64 rows are terminal_bench rows without a general/envs directory; this is explained by packaging/data-source type, not treated as a defect."}
    sum_path = OUT / "summary.json"
    write_idempotent(sum_path, (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"code_rows": domain_stats["code"]["rows"], "general_rows": domain_stats["general"]["rows"], "general_directories": len(dirs), "image_mapping_rows": len(mapping_rows), "candidates": summary["candidate_selection"], "outputs": summary["outputs"]}, indent=2))

if __name__ == "__main__":
    main()
