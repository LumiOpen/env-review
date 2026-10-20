"""Independent oracle checks against submitted probe inputs."""

from __future__ import annotations

import unittest

from rlaudit.oracles import OracleError, evaluate


COUNTDOWN = {
    "kind": "arithmetic",
    "expression": {"case": "input.completion"},
    "tag": "solution",
    "numbers": {"task": "metadata.numbers"},
    "target": {"task": "metadata.target"},
    "rules": {
        "operators": ["add", "sub", "mul", "div"],
        "positive_literals": True,
        "positive_intermediates": True,
        "integer_intermediates": True,
        "use_each_at_most_once": True,
    },
}
TASK = {"metadata": {"numbers": [2, 5, 3, 2, 50, 7], "target": 125}}


def countdown(expression: str) -> dict:
    return evaluate(COUNTDOWN, TASK, {"input": {"completion": f"<reasoning>work</reasoning><solution>{expression}</solution>"}})


class OracleTests(unittest.TestCase):
    def test_arithmetic_validity_comes_from_submitted_completion(self) -> None:
        self.assertEqual(countdown("(5*50)/2")["expected_reward"], 1.0)
        self.assertTrue(countdown("(5×50)÷2")["valid"])
        self.assertEqual(countdown("(5/2)*50")["reason"], "fractional intermediate result")
        self.assertEqual(countdown("5**3")["expected_reward"], 0.0)
        self.assertEqual(countdown("5+5+50+50+5+5+5")["expected_reward"], 0.0)

    def test_arithmetic_tag_and_rule_boundaries(self) -> None:
        malformed = evaluate(COUNTDOWN, TASK, {"input": {"completion": "<solution>5</solution><solution>5</solution>"}})
        self.assertTrue(malformed["malformed_candidate"])
        spec = {**COUNTDOWN, "rules": {**COUNTDOWN["rules"], "operators": ["add"]}}
        result = evaluate(spec, TASK, {"input": {"completion": "<solution>(5*50)/2</solution>"}})
        self.assertFalse(result["valid"])
        self.assertIn("not allowed", result["reason"])

    def test_declared_arithmetic_rules_can_allow_negative_and_fractional_steps(self) -> None:
        spec = {**COUNTDOWN, "rules": {**COUNTDOWN["rules"], "positive_literals": False, "positive_intermediates": False, "integer_intermediates": False}}
        task = {"metadata": {"numbers": [-1, 2], "target": 1}}
        result = evaluate(spec, task, {"input": {"completion": "<solution>2+(-1)</solution>"}})
        self.assertTrue(result["valid"])

    def test_exact_text_preserves_whitespace_inside_tag(self) -> None:
        spec = {"kind": "exact_text", "candidate": {"case": "input.completion"}, "expected": {"task": "metadata.gold"}, "tag": "reversed_text"}
        task = {"metadata": {"gold": "abc "}}
        self.assertTrue(evaluate(spec, task, {"input": {"completion": "\n<reversed_text>abc </reversed_text>\n"}})["match"])
        self.assertEqual(evaluate(spec, task, {"input": {"completion": "<reversed_text>abc</reversed_text>"}})["expected_reward"], 0.0)
        self.assertTrue(evaluate(spec, task, {"input": {"completion": "no tag"}})["malformed_candidate"])

    def test_lcs_uses_independent_dynamic_programming(self) -> None:
        spec = {"kind": "lcs", "candidate": {"case": "input.completion"}, "expected": {"task": "metadata.gold"}, "tag": "reversed_text"}
        result = evaluate(spec, {"metadata": {"gold": "ABCDEF"}}, {"input": {"completion": "<reversed_text>ACE</reversed_text>"}})
        self.assertEqual(result["lcs_length"], 3)
        self.assertEqual(result["expected_reward"], 2 * 3 / 9)
        self.assertEqual(evaluate(spec, {"metadata": {"gold": ""}}, {"input": {"completion": "<reversed_text></reversed_text>"}})["expected_reward"], 1.0)

    def test_oracle_malformed_spec_and_missing_ref_raise(self) -> None:
        with self.assertRaisesRegex(OracleError, "unsupported oracle"):
            evaluate({"kind": "magic"}, {}, {"input": {}})
        with self.assertRaisesRegex(OracleError, "missing field"):
            evaluate({"kind": "exact_text", "candidate": {"case": "input.answer"}, "expected": "x"}, {}, {"input": {}})
        with self.assertRaisesRegex(OracleError, "bounded work"):
            evaluate({"kind": "lcs", "candidate": "x" * 2000, "expected": "y" * 2000}, {}, {})

    def test_observation_cannot_change_reference_fact(self) -> None:
        spec = {"kind": "exact_text", "candidate": {"case": "input.answer"}, "expected": "correct"}
        case = {"input": {"answer": "wrong"}}
        self.assertEqual(evaluate(spec, {}, case, {"reward": 1}), evaluate(spec, {}, case, {"reward": 0}))


if __name__ == "__main__":
    unittest.main()
