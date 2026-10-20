"""Pinned Prime source regressions through the shared environment contract CLI."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from rlaudit import verifiers_adapter
from rlaudit.contracts import load_environment_contract


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "research/prime/sources"
DATA = ROOT / "research/prime/data"
CONTRACTS = ROOT / "examples/contracts"
TASKS = ROOT / "research/prime/tasks"


def task_record(filename: str, task_id: str) -> dict:
    records = [json.loads(line) for line in (TASKS / filename).read_text().splitlines() if line]
    return next(record for record in records if record["task_id"] == task_id)


def payload(task: dict, input_data: dict, source_id: str, source_dir: str,
            additional_sources: dict[str, Path] | None = None) -> dict:
    sources = {source_id: str(SOURCES / source_dir)}
    sources.update({key: str(path) for key, path in (additional_sources or {}).items()})
    return {"task": task, "case": {"id": "test", "input": input_data},
            "workspace": "/tmp", "sources": sources}


def run_contract(name: str, case_payload: dict) -> dict:
    command = [sys.executable, "-m", "rlaudit.verifiers_adapter", "--contract",
               str(CONTRACTS / f"prime_{name}.json")]
    completed = subprocess.run(command, input=json.dumps(case_payload), text=True,
                               capture_output=True, timeout=45, check=False)
    if completed.returncode:
        raise AssertionError(f"shared contract CLI failed: {completed.stderr}")
    return json.loads(completed.stdout)


@unittest.skipUnless(importlib.util.find_spec("verifiers") and (DATA / "reverse_rows.json").is_file(),
                     "optional Prime runtime and frozen source fixtures required")
class PrimeDriversTest(unittest.TestCase):
    def test_countdown_real_generated_row_and_invalid_solutions(self):
        task = task_record("countdown.jsonl", "prime-countdown-seed-339-row-0")
        for expression, oracle_reward in (("(5*50)/2", 1.0), ("5**3", 0.0), ("(5/2)*50", 0.0)):
            completion = f"<reasoning>Compute.</reasoning><solution>{expression}</solution>"
            case = payload(task, {"completion": completion}, "countdown",
                           "sami__countdown__e821f68a918d")
            result = run_contract("countdown", case)
            self.assertEqual(result["reward"], 1.0, expression)
            self.assertEqual(result["details"]["rubric_reward"], 1.4, expression)
            self.assertEqual(result["details"]["oracle"]["expected_reward"], oracle_reward)

    def test_reverse_real_row_uses_pinned_source_ratio(self):
        dataset = json.loads((DATA / "reverse_rows.json").read_text())
        row = dataset["selected"][0]
        task = task_record("reverse_text.jsonl", "prime-reverse-text-train-0000")
        sources = {"reverse_dataset": DATA / "reverse_dataset"}
        source = "will__reverse-text__9523b627a28d"
        exact = payload(task, {"completion": f"<reversed_text>{row['answer']}</reversed_text>"},
                        "reverse_text", source, sources)
        correct = run_contract("reverse_text", exact)
        self.assertEqual(correct["reward"], 1.0)
        self.assertEqual(correct["details"]["selected_row"]["source_row_id"], 0)
        candidate = dataset["metric_case"]["candidate_answer"]
        changed = payload(task, {"completion": f"<reversed_text>{candidate}</reversed_text>"},
                          "reverse_text", source, sources)
        observed = run_contract("reverse_text", changed)
        self.assertAlmostEqual(observed["reward"], dataset["metric_case"]["sequence_matcher_ratio"])
        self.assertEqual(observed["details"]["parsed_answer"], candidate)

    def test_reverse_logged_grader_error_is_not_recorded_as_zero_reward(self):
        source_dir = SOURCES / "will__reverse-text__9523b627a28d"
        source = verifiers_adapter._source_module(source_dir, "reverse_text")
        original = source.load_environment

        def broken_environment(*args, **kwargs):
            env = original(*args, **kwargs)

            def injected_failure(**_kwargs):
                raise RuntimeError("injected scorer failure")

            env.rubric.rubrics[0].funcs[0] = injected_failure
            return env

        task = task_record("reverse_text.jsonl", "prime-reverse-text-train-0000")
        answer = task["metadata"]["expected_answer"]
        case = payload(task, {"completion": f"<reversed_text>{answer}</reversed_text>"},
                       "reverse_text", "will__reverse-text__9523b627a28d",
                       {"reverse_dataset": DATA / "reverse_dataset"})
        contract = load_environment_contract(CONTRACTS / "prime_reverse_text.json")
        with (
            mock.patch.object(source, "load_environment", side_effect=broken_environment),
            mock.patch.object(verifiers_adapter, "_source_module", return_value=source),
        ):
            with self.assertRaisesRegex(RuntimeError, "source rubric logged a grading error"):
                asyncio.run(verifiers_adapter.run_case(case, contract))

    def test_wordle_tool_state_and_speed(self):
        task = task_record("wordle.jsonl", "prime-wordle-answer-abbey")
        source = "apple999__wordle__7cea003c4fb9"

        def play(words: list[str]) -> dict:
            calls = [{"tool": "guess", "args": {"word": word}} for word in words]
            return run_contract("wordle", payload(task, {"calls": calls}, "wordle", source))

        first = play(["abbey"])
        invalid = play(["123", "abbey"])
        slower = play(["apple", "abbey"])
        self.assertEqual(first["reward"], 1.0)
        self.assertEqual(invalid["reward"], 1.0)
        self.assertEqual(invalid["details"]["state"]["game"]["invalid"], 1)
        self.assertEqual(len(invalid["details"]["state"]["game"]["guesses"]), 1)
        self.assertAlmostEqual(slower["reward"], 0.9)
        self.assertTrue(first["details"]["stopped"])


if __name__ == "__main__":
    unittest.main()
