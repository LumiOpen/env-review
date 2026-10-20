"""Build the allowed-guess dictionary for the Wordle environment.

Real Wordle only accepts guesses that are real words. We approximate the
allowed-guess list from an offline, public-domain system dictionary (Webster's
derived, e.g. ``/usr/share/dict/words``), filtered to exactly-five lowercase
ASCII letters, and unioned with the answer pool so every possible answer is
always a legal guess.

Usage:
    python scripts/build_valid_guesses.py [--dict /usr/share/dict/words]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_WORD_RE = re.compile(r"^[a-z]{5}$")
_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "wordle" / "data"


def build(dict_path: Path) -> list[str]:
    words = {
        line.strip()
        for line in dict_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if _WORD_RE.match(line.strip())
    }
    answers = {
        line.strip().lower()
        for line in (_DATA / "answers.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return sorted(words | answers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dict", type=Path, default=Path("/usr/share/dict/words"))
    args = parser.parse_args()

    words = build(args.dict)
    out = _DATA / "valid_guesses.txt"
    out.write_text("\n".join(words) + "\n", encoding="utf-8")
    print(f"Wrote {len(words)} allowed guesses to {out}")


if __name__ == "__main__":
    main()
