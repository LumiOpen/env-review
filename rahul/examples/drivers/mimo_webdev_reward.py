"""Synthetic component probe of the pinned Webdev group reward arithmetic.

Only five literal constants and two reviewed pure functions are selected from
group_pick.py. No service imports, screenshots, renderer, or judge are used.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys


SOURCE_SHA256 = "5f8edbc6ed5e0c4c842658b8c06069b8c7c69e5482d19399c61f8dbb98b0fe38"
CONSTANTS = {"QUERY_FLOOR", "QUERY_DEDUCT", "RAW_LO", "RAW_HI", "RUNTIME_FLOOR"}
FUNCTIONS = {"query_deduct", "reward_one"}


def load_component(path: Path):
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("group_pick.py SHA-256 does not match reviewed pin")
    tree = ast.parse(source, filename=str(path))
    selected = []
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            assigned = ({target.id} if isinstance(target, ast.Name) else
                        {elt.id for elt in target.elts} if isinstance(target, ast.Tuple)
                        and all(isinstance(elt, ast.Name) for elt in target.elts) else set())
            if assigned and assigned <= CONSTANTS:
                if not isinstance(node.value, (ast.Constant, ast.List, ast.Tuple, ast.UnaryOp)):
                    raise ValueError(f"unexpected initializer for {sorted(assigned)}")
                selected.append(node)
                names.update(assigned)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
            if not isinstance(node, ast.FunctionDef):
                raise ValueError(f"unexpected async function: {node.name}")
            selected.append(node)
            names.add(node.name)
    if names != CONSTANTS | FUNCTIONS:
        raise ValueError(f"missing reviewed component names: {sorted((CONSTANTS | FUNCTIONS) - names)}")
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    namespace = {}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["reward_one"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    data = json.load(sys.stdin)["case"]["input"]
    pick = data["pick_norm"]
    query = data["query_score"]
    runtime = data.get("runtime_factor")
    if any(type(x) not in (int, float) for x in (pick, query)) or type(runtime) not in (int, float, type(None)):
        raise ValueError("numeric pick_norm, query_score and optional runtime_factor required")
    if not -1 <= pick <= 1 or not 0 <= query <= 1 or runtime not in (None, 0, 1):
        raise ValueError("input outside reviewed component range")
    reward_one = load_component(args.source)
    reward, missing = reward_one(float(pick), float(query), runtime)
    if missing or reward is None:
        raise ValueError(f"unexpected missing component inputs: {missing}")
    print(json.dumps({"reward": reward, "details": {"component": "group_pick.reward_one",
                                                 "synthetic": True, "missing": missing}}, allow_nan=False))


if __name__ == "__main__":
    main()
