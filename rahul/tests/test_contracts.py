"""Boundary checks for declarative environment contracts and references."""

from __future__ import annotations

import copy
import unittest

from rlaudit.contracts import (
    ContractError,
    resolve_ref,
    validate_environment_contract,
    validate_source_ids,
)


def contract() -> dict:
    return {
        "schema_version": "rlaudit.environment/v1",
        "id": "small-arithmetic",
        "framework": "verifiers_v0",
        "loader": {"source": "1.source", "module": "puzzles.arithmetic", "factory": "load_environment", "kwargs": {"seed": {"task": "metadata.seed"}}},
        "task": {"dataset": "dataset", "index": 0, "expect": {"question": {"task": "prompt"}, "info.numbers": {"task": "metadata.numbers"}}},
        "interaction": {"kind": "completion"},
        "score": {"metric": "exact_match_reward", "required_metrics": ["exact_match_reward"]},
        "capture": {"parsed_answer": True},
    }


class ContractTests(unittest.TestCase):
    def test_valid_contract_and_recursive_resolution(self) -> None:
        spec = validate_environment_contract(contract())
        self.assertEqual(spec["loader"]["source"], "1.source")
        value = {"seed": {"task": "metadata.seed"}, "where": [{"source": "1.source"}, {"case": "input.answer"}]}
        self.assertEqual(resolve_ref(value, {"metadata": {"seed": 339}}, {"1.source": "/snapshot/source"}, {"input": {"answer": "  x"}}), {
            "seed": 339, "where": ["/snapshot/source", "  x"]
        })
        validate_source_ids(spec, {"1.source": "/snapshot/source"})

    def test_schema_rejects_mistakes(self) -> None:
        changes = [
            lambda value: value.update({"frmaework": "verifiers_v0"}),
            lambda value: value["loader"].update({"moudle": "foo"}),
            lambda value: value["task"].update({"index": True}),
            lambda value: value["interaction"].update({"stop": "game_over"}),
            lambda value: value["score"].update({"required_metrics": ["exact_match_reward", "exact_match_reward"]}),
            lambda value: value["capture"].update({"parsed_answer": 1}),
        ]
        for change in changes:
            with self.subTest(change=change):
                value = copy.deepcopy(contract())
                change(value)
                with self.assertRaises(ContractError):
                    validate_environment_contract(value)

    def test_tool_contract_allows_declared_public_stop_method(self) -> None:
        value = contract()
        value["interaction"] = {"kind": "tool_sequence", "tools": ["guess"], "stop": "is_done", "max_calls": 12, "state_keys": ["game"]}
        self.assertEqual(validate_environment_contract(value)["interaction"]["stop"], "is_done")
        value["interaction"]["tools"] = ["_private"]
        with self.assertRaisesRegex(ContractError, "public identifier"):
            validate_environment_contract(value)

    def test_bad_reference_fails_closed(self) -> None:
        references = [
            {"task": "metadata.missing"},
            {"task": "metadata..seed"},
            {"task": "metadata.__class__"},
            {"source": "../escape"},
            {"source": "undeclared"},
            {"task": "prompt", "source": "1.source"},
        ]
        for reference in references:
            with self.subTest(reference=reference), self.assertRaises(ContractError):
                resolve_ref(reference, {"metadata": {"seed": 339}}, {"1.source": "/snapshot/source"})

    def test_case_reference_requires_case_and_source_id_must_be_declared(self) -> None:
        with self.assertRaises(ContractError):
            resolve_ref({"case": "input.answer"}, {}, {})
        with self.assertRaisesRegex(ContractError, "undeclared source IDs"):
            validate_source_ids(contract(), set())

    def test_oracle_schema_rejects_unsupported_and_unknown_rules(self) -> None:
        value = contract()
        value["oracle"] = {"kind": "magic", "candidate": "a", "expected": "b"}
        with self.assertRaisesRegex(ContractError, "unsupported oracle"):
            validate_environment_contract(value)
        value["oracle"] = {"kind": "lcs", "candidate": {"case": "input.answer"}, "expected": {"task": "metadata.gold"}, "secret": True}
        with self.assertRaisesRegex(ContractError, "unknown keys"):
            validate_environment_contract(value)


if __name__ == "__main__":
    unittest.main()
