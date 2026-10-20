"""Curate the Wordle answer pool down to common words.

Real Wordle draws its hidden answers from a small pool of *common* five-letter
words (~2,300), while accepting a much larger set of legal guesses. Training on
the full dictionary makes most games effectively unsolvable (targets like
``aahed`` or ``aalii``), which flattens the reward signal to zero.

This script ranks every legal guess by its English word frequency (Zipf scale
via the ``wordfreq`` package) and keeps the most common ``--size`` words as the
answer pool. Every selected answer is, by construction, already a legal guess.

Usage:
    python scripts/curate_answers.py [--size 2300]

Requires: ``uv pip install wordfreq``
"""

from __future__ import annotations

import argparse
from pathlib import Path

from wordfreq import zipf_frequency

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "wordle" / "data"


def curate(size: int) -> list[str]:
    candidates = {
        line.strip().lower()
        for line in (_DATA / "valid_guesses.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    ranked = sorted(candidates, key=lambda w: zipf_frequency(w, "en"), reverse=True)
    return sorted(ranked[:size])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=2300)
    args = parser.parse_args()

    answers = curate(args.size)
    out = _DATA / "answers.txt"
    out.write_text("\n".join(answers) + "\n", encoding="utf-8")
    least_common = min(answers, key=lambda w: zipf_frequency(w, "en"))
    print(f"Wrote {len(answers)} common answers to {out}")
    print(f"Least common kept: {least_common!r} (zipf {zipf_frequency(least_common, 'en'):.2f})")


if __name__ == "__main__":
    main()
