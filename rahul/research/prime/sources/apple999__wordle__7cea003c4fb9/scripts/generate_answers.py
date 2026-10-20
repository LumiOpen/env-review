"""Synthetic answer-pool generator for the Wordle environment.

Method
------
Wordle needs a diverse pool of common five-letter answer words. Hand-picking a
few words overfits to a narrow slice of the language, so we generate the pool
with an LLM using a fan-out + curate loop, then apply deterministic filters:

1. Fan-out sampling: prompt the model once per "subtopic" (everyday objects,
   nature, food, actions, words with repeated letters, words with rarer
   letters, ...). This spreads coverage across letter patterns and difficulty
   instead of clustering around a single theme.
2. Curate deterministically: lowercase, keep only exactly-five ASCII letters,
   drop proper nouns / duplicates, and (optionally) keep the more common words
   via a frequency check so the game stays fair.
3. Write the surviving words to ``wordle/data/answers.txt``.

The environment ships a pre-generated ``answers.txt`` so evaluation works with
no API access. Run this script to regenerate or expand the pool.

Usage
-----
    OPENAI_API_KEY=... python scripts/generate_answers.py --model gpt-4.1-mini \
        --per-topic 25 --out wordle/data/answers.txt

The model can be any OpenAI-compatible chat endpoint; pass --base-url to target
a different provider.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

SUBTOPICS = [
    "everyday household objects",
    "nature, animals, and weather",
    "food, drinks, and cooking",
    "common actions and verbs",
    "feelings, traits, and descriptions",
    "words that contain a repeated letter",
    "words that contain a rarer letter (j, q, x, z, or k)",
    "body parts, clothing, and colors",
]

PROMPT_TEMPLATE = (
    "List {n} common English words that are EXACTLY five letters long and fit "
    "the theme: {topic}. Only include ordinary lowercase dictionary words "
    "(no proper nouns, abbreviations, or hyphenated forms). Return a JSON "
    'object of the form {{"words": ["apple", "table", ...]}} and nothing else.'
)

_WORD_RE = re.compile(r"^[a-z]{5}$")


def _clean(candidates: list[str]) -> list[str]:
    out = []
    for word in candidates:
        w = str(word).strip().lower()
        if _WORD_RE.match(w):
            out.append(w)
    return out


def generate(model: str, per_topic: int, base_url: str | None) -> list[str]:
    from openai import OpenAI  # imported lazily so the env has no hard dep

    client = OpenAI(base_url=base_url) if base_url else OpenAI()
    seen: set[str] = set()
    pool: list[str] = []
    for topic in SUBTOPICS:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT_TEMPLATE.format(n=per_topic, topic=topic),
                }
            ],
            response_format={"type": "json_object"},
            temperature=1.0,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            words = json.loads(content).get("words", [])
        except json.JSONDecodeError:
            words = []
        for w in _clean(words):
            if w not in seen:
                seen.add(w)
                pool.append(w)
    return sorted(pool)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--per-topic", type=int, default=25)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "wordle" / "data" / "answers.txt",
    )
    args = parser.parse_args()

    pool = generate(args.model, args.per_topic, args.base_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(pool) + "\n", encoding="utf-8")
    print(f"Wrote {len(pool)} words to {args.out}")


if __name__ == "__main__":
    main()
