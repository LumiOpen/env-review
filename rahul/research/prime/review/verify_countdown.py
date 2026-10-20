"""Compute-node reproduction of one source-generated Countdown discrepancy."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import types
from pathlib import Path

from countdown_oracle import check_expression


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    # Only puzzle generation/validation is exercised, so replace the unused
    # runtime framework imports with inert modules for this independent check.
    verifiers = types.ModuleType("verifiers")
    verifiers.Environment = object
    datasets = types.ModuleType("datasets")
    datasets.Dataset = object
    sys.modules["verifiers"] = verifiers
    sys.modules["datasets"] = datasets
    spec = importlib.util.spec_from_file_location("reviewed_countdown", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    random.seed(339)
    puzzle = module.generate_puzzle(ensure_solvable=False)
    assert puzzle == {"numbers": [2, 5, 3, 2, 50, 7], "target": 125}, puzzle
    expressions = ["(5/2)*50", "(5*50)/2", "5**3"]
    observations = []
    for expression in expressions:
        actual_valid, actual_message = module.validate_solution(
            expression, puzzle["numbers"], puzzle["target"]
        )
        observations.append(
            {
                "expression": expression,
                "oracle": check_expression(expression, puzzle["numbers"], puzzle["target"]),
                "source_validator": {"valid": actual_valid, "message": actual_message},
            }
        )
    assert [item["oracle"]["valid"] for item in observations] == [False, True, False]
    assert [item["source_validator"]["valid"] for item in observations] == [True, True, True]
    print(json.dumps({"seed": 339, "puzzle": puzzle, "observations": observations}, sort_keys=True))


if __name__ == "__main__":
    main()
