"""Recheck the Dolci reference answers that duplicate copies contradict each other on.

Each problem below appears more than once in the math subset with mutually exclusive
reference answers, so at most one label per group can be right. Both are small enough
to settle by exhaustive computation rather than by trusting either label.

The problem statements are quoted from the pinned snapshot; the solutions here are our
own, and no dataset code is imported or executed.
"""

import argparse
from pathlib import Path
import sys

from eval_audit.duplicate_screen import iter_parquet_rows


def ordered_pairs_mod_81():
    """'Ordered pairs (a, b) with a, b <= 3^3 and 3^4 | a^3 + b^3. Find N mod 1000.'

    729 candidate pairs, enumerated in full.
    """
    return sum(1 for a in range(1, 28) for b in range(1, 28) if (a**3 + b**3) % 81 == 0) % 1000


def occupied_rooms(rooms=1000, people=1000, minutes=60):
    """'Each minute, every room holding more than one person sends one person onward.'

    Deterministic and simultaneous, so a direct simulation is exact.
    """
    counts = [0] * (rooms + 2)
    counts[1] = people
    for _ in range(minutes):
        moving = [1 if counts[i] > 1 else 0 for i in range(rooms + 2)]
        for i in range(rooms + 1, 0, -1):
            counts[i] += moving[i - 1] - moving[i]
    assert sum(counts) == people, "simulation lost people"
    return sum(1 for c in counts if c > 0)


# row_index -> published reference, at revision 0fb6466d31ef3a9dd16985ef635e6429e05a6491.
PUBLISHED = {
    "ordered_pairs_mod_81": {13518: "27", 16820: "27", 20373: "27", 26061: "27",
                             14616: "45", 21065: "45", 24879: "45", 25012: "45"},
    "occupied_rooms": {1979: "61", 28128: " 61 ", 7801: "31", 8093: "31"},
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = {r["row_index"]: r for r in iter_parquet_rows(args.root, subset="math")}
    failures = 0
    for name, answer in [("ordered_pairs_mod_81", ordered_pairs_mod_81()),
                         ("occupied_rooms", occupied_rooms())]:
        print(f"{name}: computed answer {answer}")
        for row_index, published in sorted(PUBLISHED[name].items()):
            row = rows[row_index]
            if row["reference"] != published:
                print(f"  row {row_index}: published reference moved, expected {published!r}, "
                      f"found {row['reference']!r}", file=sys.stderr)
                failures += 1
                continue
            correct = published.strip() == str(answer)
            print(f"  row {row_index:>5} {row['task_id']:<52} reference {published!r:>8} "
                  f"{'ok     ' if correct else 'WRONG  '} passrate {row['passrate']:.3f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
