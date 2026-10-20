# countdown

### Overview
- **Environment ID**: `sami/countdown`
- **Short description**: Countdown Numbers Game - reach a target using arithmetic operations
- **Tags**: single-turn, math, reasoning, train, eval

### Datasets
- **Primary dataset(s)**: Procedurally generated arithmetic puzzles
- **Source links**: Generated at runtime
- **Split sizes**: Configurable (default: 200 train, 30 eval)

### Task
- **Type**: single-turn
- **Parser**: XMLParser with fields `["reasoning", "solution"]`
- **Rubric overview**: Rewards exact solutions, closeness to target, and proper XML formatting

### Quickstart
Run an evaluation with default settings:

```bash
prime eval run sami/countdown
```

Configure model and sampling:

```bash
prime eval run sami/countdown \
  -m qwen/qwen3-8b \
  -n 20 -r 3 -t 1024 -T 0.7 \
  -a '{"num_examples": 100, "ensure_solvable": false}'
```

### Environment Arguments

| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `num_examples` | int | `200` | Number of training puzzles to generate |
| `eval_examples` | int | `30` | Number of evaluation puzzles |
| `ensure_solvable` | bool | `True` | Only generate puzzles with known solutions |
| `seed` | int | `42` | Random seed for reproducibility |

### Metrics

| Metric | Meaning |
| ------ | ------- |
| `reward` | Weighted sum of all reward functions |
| `exact_match_reward` | 1.0 if solution reaches target exactly |
| `closeness_reward` | Exponential decay based on distance from target |
| `format_reward` | Proper XML formatting with reasoning/solution tags |
