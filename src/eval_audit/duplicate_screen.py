"""Duplicate-prompt and reference-answer screen for row-based RLVR datasets.

Corpus rows are parsed as data; nothing from the dataset is imported or executed.
Rows that share a byte-identical prompt are independent re-measurements of one task,
so disagreement between copies is observable without running a model or a grader:
a conflicting reference answer, or a recorded pass rate the copies do not reproduce.

Every output is a review candidate. Rows that raise no signal are unlabeled, not
known good, and the screen says nothing about tasks whose prompt appears once.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator


DETECTOR_VERSION = "duplicate-screen-1"

# Placeholder reference answers that indicate a failed extraction rather than a value.
SENTINEL_REFERENCES = ("-1", "", "none", "null", "n/a", "nan")

# Pass rates are recorded as total_correct_rollouts / total_rollouts. One rollout moves
# the estimate by 1/total_rollouts, so copies are compared against that granularity.
DEFAULT_ROLLOUTS = 8


class InspectionError(Exception):
    """The local corpus does not support the requested inspection."""


_STRIP_MARKUP = (
    re.compile(r"\\(?:left|right|displaystyle|limits|!|,|;|:|\s)"),
    re.compile(r"\\(?:text|mathrm|textbf|textit|mbox|mathbf)\s*\{[^{}]*\}"),
    re.compile(r"\^\s*\{?\s*\\?circ\s*\}?"),
    re.compile(r"\\[a-z]*space"),
)
_FRAC_BRACED = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_FRAC_BARE = re.compile(r"\\[dt]?frac\s*(\d)\s*(\d)")
_ASSIGNMENT = re.compile(r"^[a-z](?:_\{?\w+\}?)?\s*=\s*(?=\S)")


def normalize_reference(value: str | None) -> str:
    """Collapse the cosmetic LaTeX differences an answer comparison should ignore.

    Deliberately lenient: it is the conservative direction for claiming that two
    references genuinely conflict, and the permissive direction for claiming that two
    references are mere notation variants. Both outputs are review candidates.
    """
    if value is None:
        return ""
    text = value.strip().replace("$", "")
    text = _FRAC_BRACED.sub(r"\1/\2", text)
    text = _FRAC_BARE.sub(r"\1/\2", text)
    for pattern in _STRIP_MARKUP:
        text = pattern.sub("", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("{", "").replace("}", "").lower()
    text = _ASSIGNMENT.sub("", text)
    try:  # "0" and "000" are the same reference; "-1" stays "-1".
        return repr(float(text))
    except ValueError:
        return text


def is_sentinel_reference(value: str | None) -> bool:
    """Report whether a reference answer looks like a placeholder, not a value."""
    return (value or "").strip().lower() in SENTINEL_REFERENCES


def prompt_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()


def group_by_prompt(rows: Iterable[dict]) -> dict[str, list[dict]]:
    """Group rows by byte-identical prompt, preserving split order within a group."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[prompt_key(row["prompt"])].append(row)
    return dict(groups)


def _locator(row: dict) -> dict:
    locator = {"task_id": row["task_id"], "row_index": row["row_index"]}
    for key in ("shard", "subset"):
        if row.get(key) is not None:
            locator[key] = row[key]
    return locator


def _passrate_granularity(rows: list[dict]) -> float:
    counts = [r["total_rollouts"] for r in rows if r.get("total_rollouts")]
    return 1.0 / max(counts) if counts else 1.0 / DEFAULT_ROLLOUTS


def screen_rows(rows: Iterable[dict]) -> list[dict]:
    """Return review candidates for one dataset subset.

    Each row needs `task_id`, `row_index`, `prompt` and `reference`; `passrate`,
    `total_rollouts`, `total_correct_rollouts`, `shard` and `subset` are optional.
    """
    materialized = list(rows)
    candidates: list[dict] = []

    for row in materialized:
        if is_sentinel_reference(row.get("reference")):
            candidates.append({
                "detector_id": "sentinel_reference",
                "tasks": [_locator(row)],
                "observation": f"reference answer is the placeholder {(row.get('reference') or '').strip()!r}",
                "reference_values": [row.get("reference")],
                "passrate_values": [row.get("passrate")],
            })

    for key, group in sorted(group_by_prompt(materialized).items()):
        if len(group) < 2:
            continue
        locators = [_locator(r) for r in group]
        references = [r.get("reference") for r in group]
        normalized = {normalize_reference(r) for r in references}
        rates = [r.get("passrate") for r in group if r.get("passrate") is not None]

        candidates.append({
            "detector_id": "duplicate_prompt",
            "tasks": locators,
            "observation": f"{len(group)} rows share a byte-identical prompt",
            "prompt_sha1": key,
            "reference_values": references,
            "passrate_values": [r.get("passrate") for r in group],
        })

        if len(normalized) > 1:
            candidates.append({
                "detector_id": "conflicting_reference",
                "tasks": locators,
                "observation": "copies of one prompt carry references that differ after normalization",
                "prompt_sha1": key,
                "reference_values": references,
                "passrate_values": [r.get("passrate") for r in group],
            })
        elif len(set(references)) > 1:
            candidates.append({
                "detector_id": "notation_variant_reference",
                "tasks": locators,
                "observation": "copies of one prompt carry the same value written differently",
                "prompt_sha1": key,
                "reference_values": references,
                "passrate_values": [r.get("passrate") for r in group],
            })

        # Only compare pass rates when the copies agree on what the answer is.
        if len(normalized) == 1 and len(rates) > 1 and max(rates) - min(rates) > _passrate_granularity(group):
            candidates.append({
                "detector_id": "unstable_passrate",
                "tasks": locators,
                "observation": (f"identically-referenced copies record pass rates spanning "
                                f"{min(rates):.3f}..{max(rates):.3f}"),
                "prompt_sha1": key,
                "reference_values": references,
                "passrate_values": [r.get("passrate") for r in group],
                "passrate_spread": max(rates) - min(rates),
                "rollout_counts": [r.get("total_rollouts") for r in group],
            })

    return candidates


def iter_parquet_rows(root: Path, subset: str | None = None, pattern: str = "data/train-*.parquet",
                      id_field: str = "custom_id", reference_field: str = "ground_truth",
                      subset_field: str = "dataset") -> Iterator[dict]:
    """Yield normalized rows from a local parquet snapshot, in split order.

    `row_index` is the zero-based position within the split, counting shards in
    filename order; it is meaningful only at the pinned source revision.
    """
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise InspectionError("reading parquet requires the 'parquet' extra (pyarrow)") from error

    shards = sorted(root.glob(pattern))
    if not shards:
        raise InspectionError(f"no parquet shards matched {pattern!r} under {root}")

    wanted = ["prompt", id_field, reference_field, subset_field,
              "passrate", "total_rollouts", "total_correct_rollouts"]
    row_index = 0
    for shard in shards:
        table = pq.read_table(shard, columns=[c for c in wanted if c in pq.read_schema(shard).names])
        columns = {name: table.column(name).to_pylist() for name in table.column_names}
        for position in range(table.num_rows):
            def value(name):
                column = columns.get(name)
                return column[position] if column is not None else None

            raw_subset = value(subset_field)
            name = raw_subset[0] if isinstance(raw_subset, list) and raw_subset else raw_subset
            reference = value(reference_field)
            if isinstance(reference, list):
                reference = reference[0] if reference else None
            if subset is None or name == subset:
                yield {"task_id": value(id_field), "row_index": row_index,
                       "shard": shard.name, "subset": name,
                       "prompt": value("prompt") or "", "reference": reference,
                       "passrate": value("passrate"), "total_rollouts": value("total_rollouts"),
                       "total_correct_rollouts": value("total_correct_rollouts")}
            row_index += 1


def build_report(rows: Iterable[dict], root: Path, subset: str | None) -> dict:
    materialized = list(rows)
    candidates = screen_rows(materialized)
    affected = {(t["task_id"], t["row_index"]) for c in candidates for t in c["tasks"]}
    return {
        "detector_version": DETECTOR_VERSION,
        "review_status": "candidates_only",
        "root": str(root),
        "subset": subset,
        "rows_inspected": len(materialized),
        "distinct_prompts": len(group_by_prompt(materialized)),
        "candidate_count": len(candidates),
        "signals_by_detector": dict(sorted(Counter(c["detector_id"] for c in candidates).items())),
        "rows_with_any_signal": len(affected),
        "candidates": candidates,
        "limitations": [
            "Candidates are review candidates; rows without a signal are unlabeled, not known good.",
            "Only byte-identical prompts are compared; paraphrases and near-duplicates are not screened.",
            "Reference normalization is lenient, so 'conflicting_reference' is conservative and "
            "'notation_variant_reference' is permissive. Both require adjudication.",
            "Recorded pass rates are read as published data. No grader was executed and no rollout "
            "was generated, so the mechanism behind an unstable pass rate is not established here.",
            "Row indices and the prompt hash are valid only at the pinned source revision.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Local snapshot directory.")
    parser.add_argument("--subset", help="Restrict to one value of the subset field.")
    parser.add_argument("--subset-field", default="dataset")
    parser.add_argument("--id-field", default="custom_id")
    parser.add_argument("--reference-field", default="ground_truth")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error("--root must be a directory")

    rows = iter_parquet_rows(args.root, subset=args.subset, id_field=args.id_field,
                             reference_field=args.reference_field, subset_field=args.subset_field)
    report = build_report(rows, args.root, args.subset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("detector_version", "rows_inspected", "distinct_prompts",
                       "candidate_count", "signals_by_detector")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
