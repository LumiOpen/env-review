"""
Countdown Numbers Game Environment

The classic UK TV show arithmetic puzzle where players must reach a target number (101-999)
using 6 source numbers with +, -, *, / operations. Each source number can only be used once.
"""

import json
import os
import random
import re
from itertools import permutations, product
from typing import Callable, Optional

import verifiers as vf
from datasets import Dataset

# Path to pre-computed puzzles
PUZZLES_FILE = os.path.join(os.path.dirname(__file__), "puzzles.json")

# Type alias for dataset builders
DatasetBuilder = Callable[[], Dataset]


# =============================================================================
# Puzzle Generation & Solving
# =============================================================================

LARGE_NUMBERS = [25, 50, 75, 100]
SMALL_NUMBERS = list(range(1, 11)) * 2  # 1-10, each appears twice


def generate_source_numbers(num_large: int = 2) -> list[int]:
    """Generate 6 source numbers with specified count of large numbers."""
    num_large = max(0, min(4, num_large))  # Clamp to 0-4
    large = random.sample(LARGE_NUMBERS, num_large)
    small = random.sample(SMALL_NUMBERS, 6 - num_large)
    numbers = large + small
    random.shuffle(numbers)
    return numbers


def generate_target() -> int:
    """Generate a random target between 101 and 999."""
    return random.randint(101, 999)


def solve_countdown(numbers: list[int], target: int, find_all: bool = False) -> list[str]:
    """
    Find solution(s) to reach the target using the given numbers.

    Uses recursive search trying all combinations of operations.
    Returns list of solution strings, or empty list if unsolvable.
    """
    solutions = []

    def search(available: list[tuple[int, str]], depth: int = 0):
        """Recursive search for solutions."""
        if len(solutions) > 0 and not find_all:
            return

        # Check if we've reached the target
        for val, expr in available:
            if val == target:
                solutions.append(expr)
                if not find_all:
                    return

        if len(available) < 2:
            return

        # Try all pairs and operations
        for i in range(len(available)):
            for j in range(len(available)):
                if i == j:
                    continue

                a_val, a_expr = available[i]
                b_val, b_expr = available[j]

                # Build remaining numbers (excluding i and j)
                remaining = [available[k] for k in range(len(available)) if k != i and k != j]

                # Try each operation
                ops = [
                    (a_val + b_val, f"({a_expr} + {b_expr})"),
                    (a_val * b_val, f"({a_expr} * {b_expr})"),
                ]

                # Subtraction (must stay positive)
                if a_val > b_val:
                    ops.append((a_val - b_val, f"({a_expr} - {b_expr})"))
                elif b_val > a_val:
                    ops.append((b_val - a_val, f"({b_expr} - {a_expr})"))

                # Division (must be exact)
                if b_val != 0 and a_val % b_val == 0:
                    ops.append((a_val // b_val, f"({a_expr} / {b_expr})"))
                if a_val != 0 and b_val % a_val == 0 and a_val != b_val:
                    ops.append((b_val // a_val, f"({b_expr} / {a_expr})"))

                for new_val, new_expr in ops:
                    if new_val > 0:  # Must stay positive
                        search(remaining + [(new_val, new_expr)], depth + 1)

    # Initialize with source numbers as expressions
    initial = [(n, str(n)) for n in numbers]
    search(initial)

    return solutions


def is_solvable(numbers: list[int], target: int) -> bool:
    """Check if the puzzle has at least one solution."""
    return len(solve_countdown(numbers, target, find_all=False)) > 0


def generate_puzzle(ensure_solvable: bool = True, max_attempts: int = 100) -> dict:
    """Generate a puzzle, optionally ensuring it's solvable."""
    for _ in range(max_attempts):
        num_large = random.randint(1, 3)  # Typically 1-3 large numbers
        numbers = generate_source_numbers(num_large)
        target = generate_target()

        if not ensure_solvable or is_solvable(numbers, target):
            return {
                "numbers": numbers,
                "target": target,
            }

    # Fallback: return anyway (may be unsolvable)
    return {
        "numbers": numbers,
        "target": target,
    }


# =============================================================================
# Solution Validation
# =============================================================================

def normalize_operators(expr: str) -> str:
    """Normalize Unicode operators to ASCII equivalents."""
    replacements = {
        '×': '*',
        '÷': '/',
        '−': '-',
        '–': '-',  # en-dash
        '—': '-',  # em-dash
    }
    for unicode_op, ascii_op in replacements.items():
        expr = expr.replace(unicode_op, ascii_op)
    return expr


def validate_solution(solution: str, numbers: list[int], target: int) -> tuple[bool, str]:
    """
    Validate a solution string.

    Returns (is_valid, message) tuple.
    """
    if not solution or not solution.strip():
        return False, "Empty solution"

    # Normalize operators first
    solution = normalize_operators(solution)

    # Strip "= result" from the end (e.g., "6 * 5 = 30" -> "6 * 5")
    if '=' in solution:
        solution = solution.split('=')[0].strip()

    # Extract numbers used in the solution
    used_numbers = [int(n) for n in re.findall(r'\d+', solution)]

    # Check that all used numbers are from the source
    available = numbers.copy()
    for num in used_numbers:
        if num in available:
            available.remove(num)
        else:
            return False, f"Number {num} not available or used more than once"

    # Check only valid operations are used
    allowed_chars = set('0123456789+-*/() \n\t')
    solution_chars = set(solution)
    invalid_chars = solution_chars - allowed_chars
    if invalid_chars:
        return False, f"Invalid characters: {invalid_chars}"

    # Evaluate the expression
    try:
        # Clean up the solution for evaluation
        clean_solution = solution.strip()

        # Handle multi-step solutions (take the last expression or result)
        lines = [l.strip() for l in clean_solution.split('\n') if l.strip()]

        # Try to find a final result
        result = None
        for line in reversed(lines):
            # Remove comments or explanations
            if '=' in line:
                line = line.split('=')[-1].strip()

            try:
                # Safely evaluate arithmetic expression
                result = eval_arithmetic(line)
                if result is not None:
                    break
            except:
                continue

        if result is None:
            # Try evaluating the whole thing
            result = eval_arithmetic(clean_solution)

        if result is None:
            return False, "Could not evaluate expression"

        # Check for integer intermediate results (Countdown rule)
        # This is a simplified check - full validation would trace each step

        if result == target:
            return True, f"Correct! {result} = {target}"
        else:
            return False, f"Result {result} does not equal target {target}"

    except Exception as e:
        return False, f"Evaluation error: {str(e)}"


def eval_arithmetic(expr: str) -> Optional[int]:
    """Safely evaluate an arithmetic expression."""
    try:
        # Normalize Unicode operators first
        expr = normalize_operators(expr)

        # Strip "= result" from the end
        if '=' in expr:
            expr = expr.split('=')[0].strip()

        # Only allow digits and basic operators
        if not re.match(r'^[\d\s\+\-\*\/\(\)\.]+$', expr):
            return None

        result = eval(expr, {"__builtins__": {}}, {})

        # Check if result is a valid integer
        if isinstance(result, (int, float)) and result == int(result) and result > 0:
            return int(result)
        return None
    except:
        return None


# =============================================================================
# Dataset Generation
# =============================================================================

SYSTEM_PROMPT = """You are solving a Countdown Numbers Game puzzle.

Rules:
- You are given 6 source numbers and a target number
- Use +, -, *, / to reach the target exactly
- Each source number can only be used once
- All intermediate results must be positive integers
- You don't have to use all numbers

Format your response as:
<reasoning>
Show your step-by-step working here
</reasoning>
<solution>
Your final arithmetic expression that equals the target
</solution>"""


def load_precomputed_puzzles():
    """Load pre-computed solvable puzzles from JSON file."""
    if os.path.exists(PUZZLES_FILE):
        with open(PUZZLES_FILE, "r") as f:
            return json.load(f)
    return None


def build_dataset_from_puzzles(puzzles: list, num_examples: int, seed: int = 42) -> Dataset:
    """Build dataset from pre-computed puzzle list."""
    random.seed(seed)

    # Shuffle and take num_examples
    shuffled = puzzles.copy()
    random.shuffle(shuffled)
    selected = shuffled[:num_examples]

    examples = []
    for puzzle in selected:
        numbers = puzzle["numbers"]
        target = puzzle["target"]
        question = f"Numbers: {', '.join(map(str, numbers))}\nTarget: {target}"
        examples.append({
            "question": question,
            "answer": puzzle.get("solution", ""),
            "info": {"numbers": numbers, "target": target}
        })

    return Dataset.from_list(examples)


def build_dataset(num_examples: int = 1000, ensure_solvable: bool = True, seed: int = 42) -> Dataset:
    """Build a dataset of Countdown puzzles."""
    random.seed(seed)

    examples = []
    for i in range(num_examples):
        puzzle = generate_puzzle(ensure_solvable=ensure_solvable)
        numbers = puzzle["numbers"]
        target = puzzle["target"]

        # Skip solving for speed - reward functions use info, not answer
        answer = ""

        question = f"Numbers: {', '.join(map(str, numbers))}\nTarget: {target}"

        examples.append({
            "question": question,
            "answer": answer,
            "info": {
                "numbers": numbers,
                "target": target,
            }
        })

    return Dataset.from_list(examples)


def get_dataset_builder(
    num_examples: int = 1000,
    ensure_solvable: bool = True,
    seed: int = 42
) -> DatasetBuilder:
    """Returns a builder that lazily loads the dataset."""
    def build() -> Dataset:
        return build_dataset(num_examples, ensure_solvable, seed)
    return build


# =============================================================================
# Reward Functions
# =============================================================================

def parse_completion(completion, parser):
    """Parse the completion using the XML parser."""
    if not completion:
        return None
    # Get the last assistant message content
    content = completion[-1].get("content", "") if isinstance(completion[-1], dict) else ""
    if not content:
        return None
    return parser.parse(content)


async def exact_match_reward(completion, info, parser) -> float:
    """Reward for reaching the target exactly."""
    try:
        parsed = parse_completion(completion, parser)
        if not parsed:
            return 0.0

        solution = getattr(parsed, 'solution', "") or ""
        if not solution:
            return 0.0

        numbers = info["numbers"]
        target = info["target"]

        is_valid, _ = validate_solution(solution, numbers, target)
        return 1.0 if is_valid else 0.0
    except Exception:
        return 0.0


async def closeness_reward(completion, info, parser) -> float:
    """Reward based on how close the result is to the target."""
    try:
        parsed = parse_completion(completion, parser)
        if not parsed:
            return 0.0

        solution = getattr(parsed, 'solution', "") or ""
        if not solution:
            return 0.0

        # Reject "give up" responses - must be an arithmetic expression
        give_up_phrases = ["unable", "cannot", "impossible", "no solution", "not possible"]
        if any(phrase in solution.lower() for phrase in give_up_phrases):
            return 0.0

        target = info["target"]

        # Only reward valid arithmetic expressions
        result = eval_arithmetic(solution)
        if result is None:
            return 0.0

        # Exponential decay based on distance
        distance = abs(result - target)
        if distance == 0:
            return 1.0

        # Decay with half-life of ~10
        reward = 0.5 ** (distance / 10)
        return reward

    except Exception:
        return 0.0


async def format_reward(completion, parser) -> float:
    """Reward for proper XML format compliance with valid arithmetic solution."""
    try:
        parsed = parse_completion(completion, parser)
        if not parsed:
            return 0.0

        score = 0.0

        # Check for reasoning section
        if getattr(parsed, 'reasoning', None):
            score += 0.5

        # Check for solution section with actual arithmetic (not give-up text)
        solution = getattr(parsed, 'solution', None)
        if solution:
            give_up_phrases = ["unable", "cannot", "impossible", "no solution", "not possible"]
            if not any(phrase in solution.lower() for phrase in give_up_phrases):
                # Must contain at least one arithmetic operator to be valid
                if any(op in solution for op in ['+', '-', '*', '/', '×', '÷', '−']):
                    score += 0.5

        return score
    except Exception:
        return 0.0


# =============================================================================
# Environment
# =============================================================================

def load_environment(
    num_examples: int = 400,
    seed: int = 42,
    eval_examples: int = 80,
) -> vf.Environment:
    """
    Load the Countdown Numbers Game environment.

    Args:
        num_examples: Number of training examples (from pre-computed set)
        seed: Random seed for reproducibility
        eval_examples: Number of evaluation examples
    """
    # Load pre-computed solvable puzzles
    precomputed = load_precomputed_puzzles()

    if precomputed:
        print(f"Loading {num_examples} training puzzles from pre-computed set...")
        dataset = build_dataset_from_puzzles(precomputed["train"], num_examples, seed)
        print(f"Loading {eval_examples} evaluation puzzles from pre-computed set...")
        eval_dataset = build_dataset_from_puzzles(precomputed["eval"], eval_examples, seed + 1000)
    else:
        print("Warning: No pre-computed puzzles found, generating on the fly...")
        dataset = build_dataset(num_examples, ensure_solvable=False, seed=seed)
        eval_dataset = build_dataset(eval_examples, ensure_solvable=False, seed=seed + 1000)

    # Parser for structured output
    parser = vf.XMLParser(fields=["reasoning", "solution"])

    # Build rubric with weighted rewards
    rubric = vf.Rubric(
        funcs=[exact_match_reward, closeness_reward, format_reward],
        weights=[1.0, 0.3, 0.1],
        parser=parser,
    )

    return vf.SingleTurnEnv(
        dataset=dataset,
        eval_dataset=eval_dataset,
        system_prompt=SYSTEM_PROMPT,
        rubric=rubric,
        parser=parser,
    )
