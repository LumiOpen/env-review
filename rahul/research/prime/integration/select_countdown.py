"""Select small, reproducible Countdown probes from the pinned generator.

Run this on an amd-tw-verification compute node. The generator definitions are
extracted unchanged from the frozen Hub module so its optional runtime imports
are not needed for fixture search.
"""

import ast
from itertools import permutations
from pathlib import Path
import random


SOURCE = Path(__file__).parents[1] / "sources/sami__countdown__e821f68a918d/countdown.py"


def generator_namespace():
    tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
    names = {"LARGE_NUMBERS", "SMALL_NUMBERS", "generate_source_numbers", "generate_target", "generate_puzzle"}
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
    namespace = {"random": random}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace


def legal_witness(numbers, target):
    for a, b in permutations(numbers, 2):
        for value, expr in ((a + b, f"{a}+{b}"), (a * b, f"{a}*{b}"),
                            (a - b, f"{a}-{b}"), (a // b if a % b == 0 else -1, f"{a}/{b}")):
            if value == target:
                return expr
    for a, b, c in permutations(numbers, 3):
        for ab, left in ((a + b, f"({a}+{b})"), (a * b, f"({a}*{b})"),
                         (a - b, f"({a}-{b})"), (a // b if a % b == 0 else -1, f"({a}/{b})")):
            if ab <= 0:
                continue
            for value, expr in ((ab + c, f"{left}+{c}"), (ab * c, f"{left}*{c}"),
                                (ab - c, f"{left}-{c}"), (ab // c if ab % c == 0 else -1, f"{left}/{c}")):
                if value == target:
                    return expr
    return None


def forbidden_witness(numbers, target):
    for a, b in permutations(numbers, 2):
        if b > 5 or a > 25:
            continue
        power = a ** b
        if power == target:
            return f"{a}**{b}"
        for c in numbers:
            remaining = numbers.copy()
            remaining.remove(a)
            remaining.remove(b)
            if c not in remaining:
                continue
            if power + c == target:
                return f"{a}**{b}+{c}"
            if power - c == target:
                return f"{a}**{b}-{c}"
            if power * c == target:
                return f"{a}**{b}*{c}"
    return None


def main():
    generate_puzzle = generator_namespace()["generate_puzzle"]
    found = 0
    for seed in range(10000):
        random.seed(seed)
        puzzle = generate_puzzle(ensure_solvable=False)
        numbers, target = puzzle["numbers"], puzzle["target"]
        forbidden = forbidden_witness(numbers, target)
        if forbidden is None:
            continue
        legal = legal_witness(numbers, target)
        print({"seed": seed, "numbers": numbers, "target": target,
               "forbidden": forbidden, "legal": legal}, flush=True)
        found += 1
        if legal is not None or found >= 10:
            break


if __name__ == "__main__":
    main()
