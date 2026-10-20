"""Independent, bounded reference facts for small declarative probe families."""

from __future__ import annotations

import ast
from collections import Counter
from fractions import Fraction
import re
from typing import Any, Mapping

from .contracts import ContractError, _oracle, resolve_ref


class OracleError(ContractError):
    """An oracle cannot produce a meaningful reference fact."""


_AST_OPERATORS = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div"}
_TRANSLATION = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "—": "-"})
_MAX_EXPRESSION_LENGTH = 256
_MAX_AST_NODES = 64
_MAX_VALUE = 10**12
_MAX_TEXT_LENGTH = 4096
_MAX_LCS_CELLS = 1_000_000


def _resolved(value: Any, task: Mapping[str, Any], case: Mapping[str, Any]) -> Any:
    try:
        return resolve_ref(value, task, {}, case)
    except ContractError as error:
        raise OracleError(str(error)) from error


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise OracleError(f"{field} must resolve to text")
    if len(value) > _MAX_TEXT_LENGTH:
        raise OracleError(f"{field} exceeds {_MAX_TEXT_LENGTH} characters")
    return value


def _extract_tag(text: str, tag: str) -> str | None:
    # Match a single simple answer field without importing the environment parser.
    if text.count(f"<{tag}>") != 1 or text.count(f"</{tag}>") != 1:
        return None
    pattern = re.compile(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", re.DOTALL)
    matches = pattern.findall(text)
    return matches[0] if len(matches) == 1 else None


def _arithmetic(spec: dict, task: Mapping[str, Any], case: Mapping[str, Any]) -> dict:
    expression = _text(_resolved(spec["expression"], task, case), "oracle.expression")
    numbers = _resolved(spec["numbers"], task, case)
    target = _resolved(spec["target"], task, case)
    if not isinstance(numbers, list) or not numbers or len(numbers) > 32 or any(type(number) is not int or abs(number) > _MAX_VALUE for number in numbers):
        raise OracleError("oracle.numbers must resolve to 1–32 bounded integers")
    if type(target) is not int or abs(target) > _MAX_VALUE:
        raise OracleError("oracle.target must resolve to a bounded integer")
    rules = spec["rules"]
    allowed = set(rules["operators"])
    available = Counter(numbers)
    used: Counter[int] = Counter()

    def verdict(reason: str, *, result: int | None = None) -> dict:
        outcome: dict[str, Any] = {"valid": False, "reason": reason, "expected_reward": 0.0}
        if result is not None:
            outcome["result"] = result
        return outcome

    if "tag" in spec:
        extracted = _extract_tag(expression, spec["tag"])
        if extracted is None:
            return {"valid": False, "malformed_candidate": True, "reason": "answer tag missing or repeated", "expected_reward": 0.0}
        expression = extracted

    if not expression.strip():
        return verdict("empty expression")
    expression = expression.translate(_TRANSLATION).strip()
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return verdict("expression too long")
    if any(character not in "0123456789+-*/() \t\n" for character in expression):
        return verdict("character outside arithmetic syntax")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return verdict("malformed expression")
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        return verdict("expression too complex")

    def literal(number: int) -> Fraction:
        if abs(number) > _MAX_VALUE or (rules["positive_literals"] and number <= 0):
            raise ValueError("literal violates range or sign rule")
        if number not in available:
            raise ValueError(f"source number {number} absent")
        used[number] += 1
        if rules["use_each_at_most_once"] and used[number] > available[number]:
            raise ValueError(f"source number {number} reused")
        return Fraction(number)

    def calculate(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return literal(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) is ast.USub and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int:
            return literal(-node.operand.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _AST_OPERATORS:
            operator = _AST_OPERATORS[type(node.op)]
            if operator not in allowed:
                raise ValueError(f"operator {operator} is not allowed")
            left, right = calculate(node.left), calculate(node.right)
            if operator == "add":
                result = left + right
            elif operator == "sub":
                result = left - right
            elif operator == "mul":
                result = left * right
            else:
                if right == 0:
                    raise ValueError("division by zero")
                result = left / right
            if rules["positive_intermediates"] and result <= 0:
                raise ValueError("nonpositive intermediate result")
            if rules["integer_intermediates"] and result.denominator != 1:
                raise ValueError("fractional intermediate result")
            if abs(result.numerator) > _MAX_VALUE or result.denominator > _MAX_VALUE:
                raise ValueError("intermediate result too large")
            return result
        raise ValueError("operator or syntax outside declared arithmetic rules")

    try:
        result = calculate(tree.body)
    except (ValueError, RecursionError) as error:
        return verdict(str(error))
    if result != target:
        return verdict(f"result {result} differs from target {target}", result=int(result) if result.denominator == 1 else None)
    return {"valid": True, "reason": "satisfies declared arithmetic rules", "result": int(result), "expected_reward": 1.0}


def _lcs_length(left: str, right: str) -> int:
    previous = [0] * (len(right) + 1)
    for character in left:
        current = [0]
        for column, other in enumerate(right, 1):
            current.append(previous[column - 1] + 1 if character == other else max(previous[column], current[-1]))
        previous = current
    return previous[-1]


def _text_oracle(spec: dict, task: Mapping[str, Any], case: Mapping[str, Any]) -> dict:
    candidate = _text(_resolved(spec["candidate"], task, case), "oracle.candidate")
    expected = _text(_resolved(spec["expected"], task, case), "oracle.expected")
    if "tag" in spec:
        extracted = _extract_tag(candidate, spec["tag"])
        if extracted is None:
            return {"malformed_candidate": True, "reason": "answer tag missing or repeated", "expected": expected, "candidate": None, "expected_reward": 0.0}
        candidate = extracted
    if spec["kind"] == "exact_text":
        match = candidate == expected
        return {"match": match, "expected": expected, "candidate": candidate, "expected_reward": float(match)}
    if len(candidate) * len(expected) > _MAX_LCS_CELLS:
        raise OracleError("LCS input exceeds bounded work limit")
    common = _lcs_length(candidate, expected)
    total = len(candidate) + len(expected)
    ratio = 1.0 if total == 0 else 2.0 * common / total
    return {"lcs_length": common, "candidate_length": len(candidate), "expected_length": len(expected), "expected_reward": ratio}


def evaluate(spec: Mapping[str, Any], task: Mapping[str, Any], case: Mapping[str, Any], observation: Mapping[str, Any] | None = None) -> dict:
    """Evaluate declared input against independent rules; never call source code.

    `observation` is accepted for callers that retain source output alongside the
    oracle, but it cannot influence reference facts or expected reward.
    """
    try:
        _oracle(spec)
    except ContractError as error:
        raise OracleError(str(error)) from error
    if not isinstance(task, Mapping) or not isinstance(case, Mapping):
        raise OracleError("task and case must be objects")
    if spec["kind"] == "arithmetic":
        return _arithmetic(dict(spec), task, case)
    return _text_oracle(dict(spec), task, case)
