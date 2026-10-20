"""Word list loading and Wordle guess scoring.

Kept separate from the environment entrypoint so the game logic has a single,
well-named home that both the environment and the dataset builder can reuse.
"""

from __future__ import annotations

from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"

# Feedback marks for each letter position.
CORRECT = "correct"  # right letter, right spot (green)
PRESENT = "present"  # right letter, wrong spot (yellow)
ABSENT = "absent"  # letter not in the target (gray)

_MARK_EMOJI = {CORRECT: "🟩", PRESENT: "🟨", ABSENT: "⬛"}


def load_answers() -> list[str]:
    """Load the curated pool of 5-letter answer words shipped with the env."""
    text = (_DATA_DIR / "answers.txt").read_text(encoding="utf-8")
    words = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return [w for w in words if is_valid_word(w)]


def load_valid_guesses() -> set[str]:
    """Load the allowed-guess dictionary (real 5-letter words).

    Built offline from a system dictionary unioned with the answer pool; see
    ``scripts/build_valid_guesses.py``.
    """
    text = (_DATA_DIR / "valid_guesses.txt").read_text(encoding="utf-8")
    return {
        line.strip().lower()
        for line in text.splitlines()
        if is_valid_word(line.strip())
    }


def is_valid_word(word: str) -> bool:
    """A structurally valid Wordle guess: exactly 5 ASCII letters."""
    return len(word) == 5 and word.isalpha() and word.isascii()


def score_guess(guess: str, answer: str) -> list[str]:
    """Return per-position feedback marks using standard Wordle rules.

    Handles duplicate letters correctly: greens are assigned first, then
    yellows are only awarded while unmatched copies of the letter remain.
    """
    guess = guess.lower()
    answer = answer.lower()
    marks = [ABSENT] * 5
    remaining: dict[str, int] = {}

    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            marks[i] = CORRECT
        else:
            remaining[a] = remaining.get(a, 0) + 1

    for i, g in enumerate(guess):
        if marks[i] == CORRECT:
            continue
        if remaining.get(g, 0) > 0:
            marks[i] = PRESENT
            remaining[g] -= 1

    return marks


def render_feedback(guess: str, marks: list[str]) -> str:
    """Render a compact, model-readable feedback line for one guess."""
    squares = "".join(_MARK_EMOJI[m] for m in marks)
    letters = " ".join(
        f"{g.upper()}({m})" for g, m in zip(guess.upper(), marks)
    )
    return f"{squares}  {letters}"
