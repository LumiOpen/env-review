#!/usr/bin/env python3
"""Select and source-inspect a small, pinned General sample; never execute tasks."""
from __future__ import annotations
import hashlib, json, re
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow.parquet as pq
import requests

REV = "e8e81e4945270b6212204bad99de1e598f7fb077"
REPO = "XiaomiMiMo/MiMo-V2.6-RL-oss"
BASE = Path(__file__).resolve().parents[1]
PARQUET = BASE / "research/mimo/inventory/raw/general_train.parquet"
OUT = BASE / "research/mimo/general_sample"
EXCLUDED = {
    "s3k_0000_accounting_audit_tax_en_t1_rl_008",
    "s3k_0001_accounting_audit_tax_en_t1_rl_002",
    "s3k_0001_accounting_audit_tax_en_t1_rl_003",
}
FILES = ("instruction.md", "verifier_meta.json", "manifest.json")
ID_RE = re.compile(r"^s3k_(?P<number>\d+)_(?P<domain>.+)_(?P<language>en|zh)_t(?P<tier>[1-5])_rl_(?P<replicate>\d+)$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_same(path: Path, data: bytes):
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"Refusing to replace different artifact: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def get_file(iid: str, name: str) -> bytes:
    path = OUT / "snapshots" / iid / name
    if path.exists():
        return path.read_bytes()
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/general/envs/{iid}/{name}"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    data = r.content
    write_same(path, data)
    return data


def prompt_text(row):
    value = row.get("prompt")
    if isinstance(value, list):
        return "\n".join(str(m.get("content", "")) for m in value if isinstance(m, dict) and m.get("role") == "user")
    return value if isinstance(value, str) else ""


def identify(iid):
    m = ID_RE.match(iid)
    if not m:
        return {"parse_status": "unparsed", "domain": None, "language": None, "tier": None, "replicate": None}
    g = m.groupdict()
    return {"parse_status": "parsed", "domain": g["domain"], "language": g["language"], "tier": int(g["tier"]), "replicate": int(g["replicate"])}


def prompt_mode(prompt: str):
    low = prompt.lower()
    readonly = [x for x in ("read-only", "read only", "do not modify", "without modifying", "don't change", "no changes") if x in low]
    modify = [x for x in ("write", "create", "edit", "update", "modify", "save", "produce a file", "deliverable") if x in low]
    if readonly and not modify:
        result = "read_only_indication"
    elif modify and not readonly:
        result = "modify_or_create_indication"
    else:
        result = "mixed_or_unclear"
    return {"classification": result, "read_only_terms": readonly, "modify_terms": modify, "heuristic_only": True}


def verifier_summary(meta):
    items = meta.get("items", []) if isinstance(meta, dict) else []
    if not isinstance(items, list): items = []
    methods = Counter(str(x.get("method", "unspecified")) for x in items if isinstance(x, dict))
    explicit_weights = sum(isinstance(x, dict) and "weight" in x for x in items)
    explicit_gate = sum(isinstance(x, dict) and (x.get("gate") is True or str(x.get("tier", "")).lower() == "gate") for x in items)
    critical = sum(isinstance(x, dict) and str(x.get("tier", "")).lower() == "critical" for x in items)
    llm_items = sum(isinstance(x, dict) and str(x.get("method", "")).lower() in {"llm", "judge", "llm_judge"} for x in items)
    return {
        "item_count": len(items), "item_method_counts": dict(sorted(methods.items())),
        "gate_count_explicit": explicit_gate, "critical_tier_item_count": critical,
        "explicit_weight_count": explicit_weights, "weight_missing_count": len(items) - explicit_weights,
        "weight_interpretation": "Missing per-item weights are recorded as absent; no numeric default is inferred from metadata alone.",
        "external_judge_item_count": llm_items, "external_judge_needed_from_item_methods": llm_items > 0,
        "non_llm_methods_count": sum(n for method, n in methods.items() if method.lower() not in {"llm", "judge", "llm_judge"}),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    parse_failures = []
    for row_index, row in enumerate(pq.read_table(PARQUET).to_pylist()):
        info = row.get("extra_info") or {}
        try: instance = json.loads(info.get("instance_json", "{}"))
        except (ValueError, TypeError): instance = {}
        if instance.get("dataset_type") != "general_agent":
            continue
        iid = str(instance.get("instance_id", ""))
        strata = identify(iid)
        if strata["parse_status"] != "parsed":
            parse_failures.append(iid)
        prompt = prompt_text(row)
        entry = {"row_index": row_index, "task_id": iid, "instance": instance, "prompt": prompt, "prompt_chars": len(prompt), **strata}
        groups[strata["domain"] or "unparsed"].append(entry)

    # Select 12 domains evenly across frequency ranks, rather than taking the first
    # alphabetical domains. Within the selected domains, alternate en/zh and take
    # the shortest prompt in that domain-language slice; task ID breaks ties.
    ranked = sorted(groups, key=lambda d: (-len(groups[d]), d))
    if len(ranked) <= 12:
        selected_domains = ranked
    else:
        indices = [round(i * (len(ranked) - 1) / 11) for i in range(12)]
        selected_domains = [ranked[i] for i in indices]
    selected = []
    for n, domain in enumerate(selected_domains):
        language = ("en", "zh")[n % 2]
        candidates = [x for x in groups[domain] if x["task_id"] not in EXCLUDED and x["language"] == language]
        if not candidates:
            other = "zh" if language == "en" else "en"
            candidates = [x for x in groups[domain] if x["task_id"] not in EXCLUDED and x["language"] == other]
            language = other
        if not candidates:
            # Preserve the domain with an explicit unparsed-language fallback.
            candidates = [x for x in groups[domain] if x["task_id"] not in EXCLUDED]
        if not candidates:
            continue
        chosen = min(candidates, key=lambda x: (x["prompt_chars"], x["task_id"]))
        selected.append(chosen)

    if len(selected) > 12 or len({x["domain"] for x in selected}) != len(selected):
        raise RuntimeError("Selection invariant failed")
    all_domain_counts = {}
    for domain, entries in sorted(groups.items()):
        all_domain_counts[domain] = {"row_count": len(entries), "language_counts": dict(sorted(Counter(x["language"] or "unparsed" for x in entries).items())), "tier_counts": {str(k): v for k,v in sorted(Counter(x["tier"] if x["tier"] is not None else "unparsed" for x in entries).items(), key=lambda z:str(z[0]))}}

    tasks = []
    total_downloaded = 0
    for rank, entry in enumerate(selected, 1):
        iid = entry["task_id"]
        downloaded = {}
        for name in FILES:
            data = get_file(iid, name)
            total_downloaded += len(data)
            downloaded[name] = {"bytes": len(data), "sha256": sha(data), "path": str(OUT / "snapshots" / iid / name)}
        inst_dir = OUT / "snapshots" / iid
        instruction = (inst_dir / "instruction.md").read_text(encoding="utf-8", errors="replace")
        manifest = json.loads((inst_dir / "manifest.json").read_text(encoding="utf-8"))
        verifier = json.loads((inst_dir / "verifier_meta.json").read_text(encoding="utf-8"))
        vs = verifier_summary(verifier)
        item_methods = vs["item_method_counts"]
        tasks.append({"rank": rank, "task_id": iid, "domain": entry["domain"], "domain_parse_status": entry["parse_status"], "language": entry["language"], "tier": entry["tier"], "replicate": entry["replicate"], "prompt_chars": entry["prompt_chars"], "selection": "shortest prompt in assigned domain-language slice; stable task_id tie-break", "prompt_mode_indication": prompt_mode(instruction), "manifest_method_fields": {k: manifest.get(k) for k in ("version", "task_type", "environment_type", "verifier_type", "grader_type", "scoring") if k in manifest}, "verifier": vs, "downloaded": downloaded})
    summary = {
        "schema_version": "mimo-general-sample/1", "revision": REV, "source": REPO,
        "source_parquet": str(PARQUET), "source_parquet_sha256": sha(PARQUET.read_bytes()),
        "selection_method": {"maximum_tasks": 12, "domain_parse": "Anchored s3k_<number>_<domain>_(en|zh)_t(1..5)_rl_<replicate>; observed language boundary is en/zh and observed tier boundary is 1..5; unmatched IDs are preserved as unparsed rather than guessed.", "domain_subset": "Sort domain groups by row count descending then domain; choose 12 evenly spaced frequency-rank positions. This avoids alphabetic-prefix selection but is not representative.", "within_domain": "Alternate en/zh by selected-domain rank; choose minimum prompt character count within that domain-language slice, then stable task ID. Exclude the three already-reviewed accounting IDs.", "sample_bias": "Twelve of sixteen General domains; frequency-rank and language-balancing rules are deliberate selection filters. Prompt lengths across Chinese and English are not directly comparable. This is an audit triage sample, not a representative sample."},
        "row_counts_by_domain_language_tier": all_domain_counts,
        "parse_failures": parse_failures,
        "already_reviewed_excluded": sorted(EXCLUDED), "selected_tasks": tasks,
        "downloaded_total_bytes": total_downloaded,
        "download_scope": "Only instruction.md, verifier_meta.json, and manifest.json for selected tasks; no documents, images, runtime code, or verifier source were fetched.",
        "cost_triage": {"all_selected_external_judge_free_by_item_metadata": all(not t["verifier"]["external_judge_needed_from_item_methods"] for t in tasks), "rule_or_non_llm_item_counts": {t["task_id"]: t["verifier"]["non_llm_methods_count"] for t in tasks}},
    }
    write_same(OUT / "summary.json", (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"selected": [{k:t[k] for k in ("task_id", "domain", "language", "tier", "prompt_chars", "verifier")} for t in tasks], "downloaded_total_bytes": total_downloaded, "summary": str(OUT / "summary.json")}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
