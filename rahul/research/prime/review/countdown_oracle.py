"""Independent, bounded checker for the published Countdown puzzle rules.

This is a review oracle, not the environment's validator. It evaluates only a
single arithmetic expression and never calls Python's ``eval``.
"""

from __future__ import annotations

import ast
from collections import Counter
from fractions import Fraction


_OPERATORS = {ast.Add, ast.Sub, ast.Mult, ast.Div}
_TRANSLATION = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "—": "-"})
_MAX_EXPRESSION_LENGTH = 256
_MAX_NODES = 64
_MAX_ABSOLUTE_VALUE = 10**12


def check_expression(expression: str, numbers: list[int], target: int) -> dict:
    """Return a rule verdict and reason for one small expression.

    A true verdict means the expression reaches the target using a subset of
    the six supplied numbers, each no more often than supplied. Every binary
    operation must produce a strictly positive integer, including the final
    operation. Decimal literals, unary operators, exponentiation, floor
    division, calls, and all other Python syntax are rejected.
    """
    if not isinstance(expression, str) or not expression.strip():
        return {"valid": False, "reason": "empty expression"}
    expression = expression.translate(_TRANSLATION).strip()
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return {"valid": False, "reason": "expression too long"}
    if any(character not in "0123456789+-*/() \t\n" for character in expression):
        return {"valid": False, "reason": "character outside arithmetic syntax"}

    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        return {"valid": False, "reason": "malformed expression"}
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        return {"valid": False, "reason": "expression too complex"}

    available = Counter(numbers)
    used: Counter[int] = Counter()

    def evaluate(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
            if value <= 0 or value > _MAX_ABSOLUTE_VALUE:
                raise ValueError("nonpositive or excessive literal")
            used[value] += 1
            if used[value] > available[value]:
                raise ValueError(f"source number {value} absent or reused")
            return Fraction(value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            else:
                if right == 0:
                    raise ValueError("division by zero")
                value = left / right
            if value <= 0:
                raise ValueError("nonpositive intermediate result")
            if value.denominator != 1:
                raise ValueError("fractional intermediate result")
            if abs(value.numerator) > _MAX_ABSOLUTE_VALUE:
                raise ValueError("intermediate result too large")
            return value
        raise ValueError("operator or syntax outside Countdown rules")

    try:
        result = evaluate(tree.body)
    except ValueError as error:
        return {"valid": False, "reason": str(error)}
    if result != target:
        return {"valid": False, "reason": f"result {result} differs from target {target}"}
    return {"valid": True, "reason": "satisfies the puzzle rules", "result": int(result)}
