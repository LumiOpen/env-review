"""Test whether duplicate-prompt pass rates differ by more than sampling noise allows.

Run after the duplicate screen. Parses the pinned parquet snapshot as data; nothing
from the corpus is imported or executed.

Two rows carrying a byte-identical prompt and the same reference answer are two
measurements of one quantity. If both were produced by rolling out one policy
`n` times, their correct counts are independent Binomial(n, p) draws. Conditioning
on the pooled total removes the unknown `p` entirely: the split is Hypergeometric,
which gives an exact null distribution for the gap between the copies.

A gap larger than that null permits means the copies were not measured under the
same conditions, so `passrate` is not comparable across rows.
"""

import argparse
import json
from math import comb, sqrt
from pathlib import Path
import sys

from eval_audit.duplicate_screen import group_by_prompt, iter_parquet_rows, normalize_reference


def gap_moments(successes, left_rollouts, right_rollouts):
    """Return the exact mean and variance of |left - right| under the shared-policy null.

    Conditional on `successes` total, the count landing in the left copy is
    Hypergeometric(left + right, successes, left_rollouts); the unknown pass rate
    cancels, so this needs no estimate of it.
    """
    total = left_rollouts + right_rollouts
    denominator = comb(total, successes)
    first = second = 0.0
    low = max(0, successes - right_rollouts)
    for left in range(low, min(successes, left_rollouts) + 1):
        weight = comb(left_rollouts, left) * comb(right_rollouts, successes - left) / denominator
        gap = abs(left - (successes - left))
        first += weight * gap
        second += weight * gap * gap
    return first, max(second - first * first, 0.0)


def paired_groups(rows, rollouts):
    """Yield (group, left, right) for prompts measured exactly twice, same reference."""
    for group in group_by_prompt(rows).values():
        if len(group) != 2:
            continue
        if len({normalize_reference(r["reference"]) for r in group}) != 1:
            continue
        if any(r["total_rollouts"] != rollouts or r["total_correct_rollouts"] is None for r in group):
            continue
        # The published pass rate must match the counts, or the counts are not what we think.
        for r in group:
            assert abs(r["passrate"] - r["total_correct_rollouts"] / rollouts) < 1e-6, r["task_id"]
        left, right = (int(r["total_correct_rollouts"]) for r in group)
        if max(left, right) > rollouts:
            continue
        yield group, left, right


def gap_distribution(successes, rollouts):
    """Return the exact null probability of each |left - right| gap."""
    denominator = comb(2 * rollouts, successes)
    probabilities = {}
    for left in range(max(0, successes - rollouts), min(successes, rollouts) + 1):
        weight = comb(rollouts, left) * comb(rollouts, successes - left) / denominator
        probabilities[abs(2 * left - successes)] = probabilities.get(abs(2 * left - successes), 0.0) + weight
    return probabilities


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--subset", default="math")
    parser.add_argument("--rollouts", type=int, default=8,
                        help="Compare only copies measured with exactly this many rollouts.")
    parser.add_argument("--output", type=Path, help="Also write the result as JSON.")
    args = parser.parse_args(argv)

    rows = list(iter_parquet_rows(args.root, subset=args.subset))
    observed = expected = variance = 0.0
    pairs = 0
    seen = [0] * (args.rollouts + 1)
    predicted = [0.0] * (args.rollouts + 1)
    for _group, left, right in paired_groups(rows, args.rollouts):
        mean, var = gap_moments(left + right, args.rollouts, args.rollouts)
        observed += abs(left - right)
        expected += mean
        variance += var
        pairs += 1
        seen[abs(left - right)] += 1
        for gap, probability in gap_distribution(left + right, args.rollouts).items():
            predicted[gap] += probability

    if not pairs:
        print("no comparable pairs found", file=sys.stderr)
        return 1

    z = (observed - expected) / sqrt(variance) if variance else float("nan")
    print(f"pairs compared                 {pairs}")
    print(f"mean gap observed              {observed / pairs:.4f} rollouts")
    print(f"mean gap under shared policy   {expected / pairs:.4f} rollouts")
    print(f"dispersion ratio               {observed / expected:.3f}x")
    print(f"z                              {z:+.1f}")
    print("\ngap  observed            expected")
    for gap in range(args.rollouts + 1):
        print(f"{gap:>3}  {seen[gap]:>5} ({100 * seen[gap] / pairs:>5.1f}%)"
              f"   {predicted[gap]:>7.1f} ({100 * predicted[gap] / pairs:>5.1f}%)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "test": "duplicate pass-rate dispersion against an exact shared-policy null",
            "null_hypothesis": "both copies are independent binomial draws from one policy; "
                               "conditioning on the pooled correct count makes the split hypergeometric",
            "root": str(args.root), "subset": args.subset, "rollouts": args.rollouts,
            "pairs": pairs, "mean_gap_observed": observed / pairs,
            "mean_gap_expected": expected / pairs, "dispersion_ratio": observed / expected, "z": z,
            "gap_counts_observed": seen, "gap_counts_expected": predicted,
            "interpretation": "A ratio below 1 means the copies agree more closely than independent "
                              "sampling allows, so they are not independent measurements. The "
                              "mechanism is not identifiable from the published columns.",
        }, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
