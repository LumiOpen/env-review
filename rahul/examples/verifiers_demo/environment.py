"""Small Verifiers v0 environment used to exercise the generic audit adapter."""

from datasets import Dataset
import verifiers as vf


def copy_token_reward(completion, answer, parser) -> float:
    """Score only an exact copy of the requested token inside answer tags."""
    return 1.0 if parser.parse_answer(completion) == answer else 0.0


def load_environment() -> vf.Environment:
    parser = vf.XMLParser(fields=["answer"], answer_field="answer")
    dataset = Dataset.from_list([
        {
            "question": "Copy the token exactly inside <answer> tags: maple",
            "answer": "maple",
            "info": {},
        }
    ])
    rubric = vf.Rubric(funcs=[copy_token_reward], weights=[1.0], parser=parser)
    return vf.SingleTurnEnv(
        dataset=dataset,
        system_prompt="Copy the requested token exactly inside <answer> tags.",
        parser=parser,
        rubric=rubric,
    )
