"""Local mechanics baseline for the Wordle environment.

Live inference (Prime Inference / provider keys) is unavailable in this shell,
so instead of measuring a model we drive the environment's real custom code
paths -- ``update_tool_args`` -> ``guess`` tool -> ``game_over`` stop condition
-> ``WordleRubric`` -- with two reference policies:

* random  : pick a random word from the answer pool each turn (weak lower bound)
* greedy  : keep only pool words consistent with all feedback so far, then guess
            the first remaining candidate (informed upper bound)

This validates the reward wiring and shows the solve-rate / metric spread the
task produces, which is what we inspect before iterating.
"""

from __future__ import annotations

import argparse
import asyncio
import random

from wordle import WordleEnv, WordleRubric, load_environment
from wordle.words import load_answers, score_guess


def _consistent(candidate: str, guess: str, marks: list[str]) -> bool:
    return score_guess(guess, candidate) == marks


async def _play(env: WordleEnv, rubric: WordleRubric, answer: str, policy: str,
                pool: list[str], rng: random.Random) -> dict:
    state = {
        "answer": answer,
        "game": {
            "answer": answer,
            "guesses": [],
            "invalid": 0,
            "solved": False,
            "max_guesses": env.max_guesses,
        },
    }
    candidates = list(pool)
    while True:
        if policy == "greedy" and candidates:
            word = candidates[0]
        else:
            word = rng.choice(pool)

        args = env.update_tool_args("guess", {"word": word}, [], state)
        await env.guess(**args)

        last = state["game"]["guesses"][-1]
        candidates = [
            c for c in candidates
            if c != last["word"] and _consistent(c, last["word"], last["marks"])
        ]
        if await env.game_over(state):
            break

    return {
        "reward": await rubric.solved(state),
        "num_guesses": await rubric.num_guesses(state),
        "letters_correct": await rubric.letters_correct(state),
    }


async def run(policy: str, rollouts: int, seed: int) -> None:
    env = load_environment(max_guesses=6)
    rubric = WordleRubric()
    pool = load_answers()
    rng = random.Random(seed)

    results = []
    for word in pool:
        for _ in range(rollouts):
            results.append(await _play(env, rubric, word, policy, pool, rng))

    n = len(results)
    solve_rate = sum(r["reward"] for r in results) / n
    avg_guesses = sum(r["num_guesses"] for r in results) / n
    solved = [r for r in results if r["reward"] == 1.0]
    avg_solve_len = sum(r["num_guesses"] for r in solved) / len(solved) if solved else 0.0

    print(f"policy={policy}  games={n}")
    print(f"  solve_rate      : {solve_rate:.3f}")
    print(f"  avg_guesses     : {avg_guesses:.2f}")
    print(f"  avg_solve_len   : {avg_solve_len:.2f} (solved games only)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=["random", "greedy"], default="greedy")
    parser.add_argument("--rollouts", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(run(args.policy, args.rollouts, args.seed))


if __name__ == "__main__":
    main()
