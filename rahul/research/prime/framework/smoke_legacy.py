"""Bounded import and real-rubric smoke check; run only on Slurm compute."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import datasets
import verifiers as vf


SOURCES = Path(__file__).resolve().parents[1] / "sources"


def load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def main():
    reverse = load_file(
        "prime_reverse_smoke",
        SOURCES / "will__reverse-text__9523b627a28d" / "reverse_text.py",
    )
    reverse.load_dataset = lambda *_args, **_kwargs: datasets.Dataset.from_list(
        [{"prompt": "abc"}]
    )
    reverse_env = reverse.load_environment()
    reverse_state = {
        "prompt": [{"role": "user", "content": "abc"}],
        "completion": [{"role": "assistant", "content": "<reversed_text>cba</reversed_text>"}],
        "answer": "cba",
        "trajectory": [],
    }
    await reverse_env.rubric.score_rollout(reverse_state)

    countdown = load_file(
        "prime_countdown_smoke",
        SOURCES / "sami__countdown__e821f68a918d" / "countdown.py",
    )
    countdown.load_precomputed_puzzles = lambda: {"train": [], "eval": []}
    countdown.build_dataset_from_puzzles = lambda *_args, **_kwargs: (
        datasets.Dataset.from_list(
            [{
                "question": "Use 1 and 2 to make 3",
                "answer": "1+2",
                "info": {"numbers": [1, 2], "target": 3},
            }]
        )
    )
    countdown_env = countdown.load_environment(num_examples=1, eval_examples=1)
    countdown_state = {
        "prompt": [{"role": "user", "content": "Use 1 and 2 to make 3"}],
        "completion": [
            {"role": "assistant", "content": "<reasoning>add</reasoning><solution>1+2</solution>"}
        ],
        "answer": "1+2",
        "info": {"numbers": [1, 2], "target": 3},
        "trajectory": [],
    }
    await countdown_env.rubric.score_rollout(countdown_state)

    sys.path.insert(0, str(SOURCES / "apple999__wordle__7cea003c4fb9"))
    from wordle.wordle import load_environment as load_wordle

    wordle_env = load_wordle()
    wordle_state = {
        "prompt": [{"role": "user", "content": "Start the game"}],
        "completion": [],
        "answer": "apple",
        "trajectory": [],
    }
    await wordle_env.setup_state(wordle_state)
    await wordle_env.rubric.score_rollout(wordle_state)

    print(
        json.dumps(
            {
                "verifiers": vf.__version__,
                "datasets": datasets.__version__,
                "reverse": {
                    "reward": reverse_state["reward"],
                    "metrics": reverse_state["metrics"],
                },
                "countdown": {
                    "reward": countdown_state["reward"],
                    "metrics": countdown_state["metrics"],
                },
                "wordle": {
                    "reward": wordle_state["reward"],
                    "metrics": wordle_state["metrics"],
                    "game": wordle_state["game"],
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
