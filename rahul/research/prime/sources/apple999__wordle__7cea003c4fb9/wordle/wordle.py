import verifiers as vf
from datasets import Dataset

from .words import (
    is_valid_word,
    load_answers,
    load_valid_guesses,
    render_feedback,
    score_guess,
)

SYSTEM_PROMPT = """You are an expert Wordle player. The goal is to guess a hidden \
five-letter English word in as few guesses as possible (at most six).

Play by calling the `guess` tool with a single five-letter word. Every guess \
must be a real English word from the dictionary; invalid words are rejected and \
do not use up a guess. After each guess you receive per-letter feedback:
- 🟩 correct: the letter is in the word and in the right position.
- 🟨 present: the letter is in the word but in a different position.
- ⬛ absent: the letter is not in the word.

Reason step by step about the feedback before each guess, keep guesses \
consistent with all prior feedback, and prefer guesses that maximize information \
early. Call the `guess` tool exactly once per turn."""


class WordleRubric(vf.Rubric):
    """Shaped scoring for a Wordle rollout.

    A purely binary solve signal is flat at zero for a weak policy, giving RL
    no gradient. The weighted `game_reward` keeps solving dominant while adding
    dense partial credit for green progress, so unsolved games are still ranked
    by how close they got. Solving in fewer guesses scores higher, and every
    solve outranks every non-solve. The remaining functions are 0-weight metrics
    for inspecting behavior (solve rate, guess efficiency, invalid-guess rate,
    and best green coverage).
    """

    def __init__(self) -> None:
        super().__init__(funcs=[self.game_reward], weights=[1.0])
        self.add_metric(self.solved)
        self.add_metric(self.num_guesses)
        self.add_metric(self.invalid_guesses)
        self.add_metric(self.letters_correct)

    async def game_reward(self, state: vf.State) -> float:
        game = state["game"]
        max_guesses = game["max_guesses"]
        if game["solved"]:
            used = len(game["guesses"])
            speed = (max_guesses - used) / max(max_guesses - 1, 1)
            return 0.5 + 0.5 * speed
        # Unsolved: dense credit for the best green coverage achieved so far.
        # Capped at 0.4 (< the 0.5 solve floor) so any solve always wins.
        return 0.4 * await self.letters_correct(state)

    async def solved(self, state: vf.State) -> float:
        return 1.0 if state["game"]["solved"] else 0.0

    async def num_guesses(self, state: vf.State) -> float:
        return float(len(state["game"]["guesses"]))

    async def invalid_guesses(self, state: vf.State) -> float:
        return float(state["game"]["invalid"])

    async def letters_correct(self, state: vf.State) -> float:
        guesses = state["game"]["guesses"]
        if not guesses:
            return 0.0
        best = max(sum(1 for m in g["marks"] if m == "correct") for g in guesses)
        return best / 5.0


class WordleEnv(vf.StatefulToolEnv):
    """Multi-turn Wordle played through a single `guess` tool.

    The hidden target and per-rollout game state are injected into the tool
    call at runtime, so the model only ever sees `guess(word)`.
    """

    def __init__(self, max_guesses: int = 6, **kwargs) -> None:
        super().__init__(**kwargs)
        self.max_guesses = max_guesses
        self.valid_guesses = load_valid_guesses()
        self.add_tool(self.guess, args_to_skip=["answer", "game"])

    async def setup_state(self, state: vf.State) -> None:
        state["game"] = {
            "answer": str(state["answer"]).lower(),
            "guesses": [],
            "invalid": 0,
            "solved": False,
            "max_guesses": self.max_guesses,
        }
        await super().setup_state(state)

    def update_tool_args(
        self,
        tool_name: str,
        tool_args: dict,
        messages: vf.Messages,
        state: vf.State,
        **kwargs,
    ) -> dict:
        if tool_name == "guess":
            tool_args["answer"] = state["game"]["answer"]
            tool_args["game"] = state["game"]
        return tool_args

    @vf.stop
    async def game_over(self, state: vf.State) -> bool:
        game = state["game"]
        return game["solved"] or len(game["guesses"]) >= game["max_guesses"]

    async def guess(self, word: str, answer: str, game: dict) -> str:
        """Submit a five-letter guess and receive Wordle feedback.

        Args:
            word: A single five-letter English word to guess.

        Returns:
            Per-letter feedback for the guess and the number of guesses left.
        """
        word = word.strip().lower()
        if not is_valid_word(word):
            game["invalid"] += 1
            return (
                f"'{word}' is not a valid guess. Enter exactly five letters "
                "(a-z), no spaces or punctuation. This did not count as a guess."
            )
        if word not in self.valid_guesses:
            game["invalid"] += 1
            return (
                f"'{word}' is not in the word list. Guess a real five-letter "
                "English word. This did not count as a guess."
            )

        remaining_before = game["max_guesses"] - len(game["guesses"])
        if remaining_before <= 0:
            return "No guesses remaining. The game is over."

        marks = score_guess(word, answer)
        game["guesses"].append({"word": word, "marks": marks})
        game["solved"] = word == answer
        used = len(game["guesses"])
        remaining = game["max_guesses"] - used

        feedback = render_feedback(word, marks)
        if game["solved"]:
            return f"{feedback}\nCorrect! Solved in {used} guess(es)."
        if remaining <= 0:
            return f"{feedback}\nOut of guesses. The word was '{answer}'."
        return f"{feedback}\nGuess {used}/{game['max_guesses']}. {remaining} left."


def _build_dataset() -> Dataset:
    answers = load_answers()
    rows = [
        {
            "question": "Start the game. Make your first guess with the `guess` tool.",
            "answer": word,
        }
        for word in answers
    ]
    return Dataset.from_list(rows)


def load_environment(max_guesses: int = 6, **kwargs) -> vf.Environment:
    """Load the Wordle tool environment.

    Args:
        max_guesses: Maximum number of valid guesses allowed per game.
    """
    dataset = _build_dataset()
    # Allow slack turns beyond max_guesses so invalid guesses don't end the game.
    max_turns = max_guesses * 2
    return WordleEnv(
        dataset=dataset,
        eval_dataset=dataset,
        rubric=WordleRubric(),
        system_prompt=SYSTEM_PROMPT,
        max_guesses=max_guesses,
        max_turns=max_turns,
        **kwargs,
    )
