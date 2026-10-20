"""Focused generic Verifiers v0 adapter checks; execute on Slurm compute nodes."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from rlaudit import verifiers_adapter


SYNTHETIC_SOURCE = '''import logging

class Parser:
    def parse_answer(self, completion):
        return completion[-1]["content"].strip()

class Rubric:
    async def score_rollout(self, state):
        if state["info"].get("log_error"):
            logging.getLogger("verifiers.rubrics.rubric").error("synthetic grader failure")
            state["reward"] = 0.0
            state["metrics"] = {"quality": 0.0}
            return
        state["reward"] = float(len(state.get("moves", []))) if state["completion"] == [] else 0.75
        state["metrics"] = {"quality": state["reward"], "other": 2.0}

class Environment:
    def __init__(self, rows):
        self.dataset = rows
        self.max_turns = 3
        self.system_prompt = "Use the declared interface."
        self.parser = Parser()
        self.rubric = Rubric()

    async def setup_state(self, state):
        state["moves"] = []
        state["machine"] = {"token": state["answer"]}

    def update_tool_args(self, tool_name, arguments, messages, state):
        arguments["machine"] = state["machine"]
        arguments["moves"] = state["moves"]
        return arguments

    async def move(self, value, machine, moves):
        moves.append(value)
        return machine["token"] + value

    async def finished(self, state):
        return len(state["moves"]) >= 2

def build_environment(rows):
    print("source loader emitted evidence")
    return Environment(rows)
'''


class VerifiersAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)
        (self.source / "unrelated_fourth.py").write_text(SYNTHETIC_SOURCE)
        self.task = {"prompt": "A fresh task", "metadata": {"row": 1, "answer": "q"}}
        self.rows = [
            {"question": "Other task", "answer": "x", "info": {}},
            {"question": "A fresh task", "answer": "q", "info": {}},
        ]
        self.contract = {
            "schema_version": "rlaudit.environment/v1",
            "id": "unrelated/fourth",
            "framework": "verifiers_v0",
            "loader": {"source": "synthetic", "module": "unrelated_fourth",
                       "factory": "build_environment", "kwargs": {"rows": self.rows}},
            "task": {"dataset": "dataset", "index": {"task": "metadata.row"},
                     "expect": {"question": {"task": "prompt"},
                                "answer": {"task": "metadata.answer"}}},
            "interaction": {"kind": "completion"},
            "score": {"metric": "quality", "required_metrics": ["quality"]},
            "capture": {"parsed_answer": True},
        }
        self.payload = {"task": self.task, "case": {"input": {"completion": " q "}},
                        "sources": {"synthetic": str(self.source)}}

    def run_case(self):
        with mock.patch.object(verifiers_adapter, "_require_runtime"):
            return asyncio.run(verifiers_adapter.run_case(self.payload, self.contract))

    def test_unrelated_completion_uses_declared_module_row_and_rubric(self):
        result = self.run_case()
        self.assertEqual(result["reward"], 0.75)
        self.assertEqual(result["details"]["row_index"], 1)
        self.assertEqual(result["details"]["selected_row"]["answer"], "q")
        self.assertEqual(result["details"]["parsed_answer"], "q")
        self.assertEqual(result["details"]["rubric_metrics"]["quality"], 0.75)

    def test_initial_state_preserves_present_falsey_info(self):
        environment = type("Environment", (), {"system_prompt": ""})()
        for value in (None, False, 0, "", []):
            with self.subTest(info=value):
                row = {"question": "task", "answer": "answer", "info": value}
                self.assertIs(verifiers_adapter._initial_state(environment, row)["info"], value)
        self.assertEqual(
            verifiers_adapter._initial_state(environment, {"question": "task", "answer": "answer"})["info"],
            {},
        )




    def test_independent_oracle_does_not_change_source_reward(self):
        self.contract["oracle"] = {
            "kind": "exact_text", "candidate": {"case": "input.completion"},
            "expected": {"task": "metadata.answer"},
        }
        result = self.run_case()
        self.assertEqual(result["reward"], 0.75)
        self.assertEqual(result["details"]["oracle"]["expected_reward"], 0.0)

    def test_cli_emits_one_json_object_despite_source_stdout(self):
        contract_path = self.source / "contract.json"
        contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-m", "rlaudit.verifiers_adapter", "--contract", str(contract_path)],
            input=json.dumps(self.payload), text=True, capture_output=True,
            timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["reward"], 0.75)
        self.assertIn("source loader emitted evidence", completed.stderr)

    def test_unrelated_tool_sequence_calls_declared_source_methods(self):
        self.contract["interaction"] = {
            "kind": "tool_sequence", "tools": ["move"], "stop": "finished",
            "max_calls": 2, "state_keys": ["machine", "moves"],
        }
        self.contract["capture"] = {"parsed_answer": False}
        self.payload["case"]["input"] = {"calls": [
            {"tool": "move", "args": {"value": "a"}},
            {"tool": "move", "args": {"value": "b"}},
        ]}
        result = self.run_case()
        self.assertEqual(result["reward"], 2.0)
        self.assertTrue(result["details"]["stopped"])
        self.assertEqual([call["response"] for call in result["details"]["tool_calls"]], ["qa", "qb"])
        self.assertEqual(result["details"]["state"]["moves"], ["a", "b"])

    def test_selected_row_mismatch_fails_before_scoring(self):
        self.task["metadata"]["answer"] = "wrong"
        with self.assertRaisesRegex(ValueError, "differs at 'answer'"):
            self.run_case()

    def test_logged_grading_error_fails_instead_of_returning_zero(self):
        self.rows[1]["info"] = {"log_error": True}
        with self.assertRaisesRegex(RuntimeError, "synthetic grader failure"):
            self.run_case()

    def test_declared_tool_bound_and_stop_condition_are_enforced(self):
        self.contract["interaction"] = {
            "kind": "tool_sequence", "tools": ["move"], "stop": "finished",
            "max_calls": 3, "state_keys": [],
        }
        self.payload["case"]["input"] = {"calls": [
            {"tool": "move", "args": {"value": letter}} for letter in "abc"
        ]}
        with self.assertRaisesRegex(ValueError, "after source stop"):
            self.run_case()

    def test_source_turn_bound_is_enforced_even_if_contract_is_looser(self):
        self.contract["interaction"] = {
            "kind": "tool_sequence", "tools": ["move"], "stop": "finished",
            "max_calls": 4, "state_keys": [],
        }
        self.payload["case"]["input"] = {"calls": [
            {"tool": "move", "args": {"value": letter}} for letter in "abcd"
        ]}
        with self.assertRaisesRegex(ValueError, "source max_turns"):
            self.run_case()

    def test_reverse_source_loads_local_dataset_directory_without_hook(self):
        source = Path(__file__).resolve().parents[1] / "research/prime/sources/will__reverse-text__9523b627a28d"
        local_dataset = self.source / "local_dataset"
        local_dataset.mkdir()
        (local_dataset / "train.jsonl").write_text(
            '{"prompt":"first"}\n{"prompt":"second"}\n', encoding="utf-8"
        )
        contract = {
            "schema_version": "rlaudit.environment/v1", "id": "source/reverse-test",
            "framework": "verifiers_v0",
            "loader": {"source": "reverse", "module": "reverse_text", "factory": "load_environment",
                       "kwargs": {"dataset_name": {"source": "dataset"}}},
            "task": {"dataset": "dataset", "index": {"task": "metadata.fixture_index"},
                     "expect": {"question": {"task": "prompt"}}},
            "interaction": {"kind": "completion"},
            "score": {"metric": "reward", "required_metrics": []},
            "capture": {"parsed_answer": True},
        }
        payload = {
            "task": {"prompt": "second", "metadata": {"fixture_index": 1}},
            "case": {"input": {"completion": "<reversed_text>dnoces</reversed_text>"}},
            "sources": {"reverse": str(source), "dataset": str(local_dataset)},
        }
        result = asyncio.run(verifiers_adapter.run_case(payload, contract))
        self.assertEqual(result["reward"], 1.0)
        self.assertEqual(result["details"]["selected_row"]["answer"], "dnoces")

    def test_wordle_package_imports_and_replays_source_tool(self):
        source = Path(__file__).resolve().parents[1] / "research/prime/sources/apple999__wordle__7cea003c4fb9"
        question = "Start the game. Make your first guess with the `guess` tool."
        contract = {
            "schema_version": "rlaudit.environment/v1", "id": "source/wordle-test",
            "framework": "verifiers_v0",
            "loader": {"source": "wordle", "module": "wordle.wordle", "factory": "load_environment",
                       "kwargs": {"max_guesses": 6}},
            "task": {"dataset": "dataset", "index": {"task": "metadata.answer_index"},
                     "expect": {"question": {"task": "prompt"},
                                "answer": {"task": "metadata.answer"}}},
            "interaction": {"kind": "tool_sequence", "tools": ["guess"],
                            "stop": "game_over", "max_calls": 12, "state_keys": ["game"]},
            "score": {"metric": "reward", "required_metrics": []},
            "capture": {"parsed_answer": False},
        }
        payload = {
            "task": {"prompt": question, "metadata": {"answer_index": 1, "answer": "abbey"}},
            "case": {"input": {"calls": [{"tool": "guess", "args": {"word": "abbey"}}]}},
            "sources": {"wordle": str(source)},
        }
        result = asyncio.run(verifiers_adapter.run_case(payload, contract))
        self.assertEqual(result["reward"], 1.0)
        self.assertTrue(result["details"]["stopped"])
        self.assertTrue(result["details"]["state"]["game"]["solved"])


if __name__ == "__main__":
    unittest.main()
