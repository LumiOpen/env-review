# wordle

### Overview
- **Environment ID**: `wordle`
- **Short description**: Multi-turn Wordle where the model guesses a hidden five-letter word through a `guess` tool and receives standard green/yellow/gray feedback.
- **Tags**: multi-turn, tool-use, games, train, eval

### Datasets
- **Primary dataset(s)**: A curated pool of ~2,300 *common* five-letter answer words shipped in `wordle/data/answers.txt`. Each word becomes one game (rollout) with the target hidden from the model. The pool is restricted to common words (as in real Wordle) so games are solvable and the reward carries signal; the full dictionary makes most games unsolvable and flattens reward to zero.
- **Allowed guesses**: `wordle/data/valid_guesses.txt` (~17k real five-letter words) built offline from a public-domain system dictionary unioned with the answer pool; see `scripts/build_valid_guesses.py`. The `guess` tool rejects any word not in this list, matching real Wordle. Every answer is a legal guess by construction.
- **Source**: The answer pool is curated by frequency (`scripts/curate_answers.py`, using `wordfreq` Zipf scores) from the legal-guess set. `scripts/generate_answers.py` (LLM fan-out) is also available for synthetic generation.
- **Split sizes**: ~2,300 answer words; used for both `dataset` and `eval_dataset`.

### Task
- **Type**: multi-turn tool use
- **Interaction**: The model calls `guess(word)` up to six times. The hidden target and per-rollout game state are injected into the tool call at runtime via `StatefulToolEnv`, so the model only sees `guess(word)`.
- **Rubric overview**: Shaped `game_reward`. A solve scores `0.5 + 0.5 * speed` (solving in fewer guesses scores higher, so every solve is in `[0.5, 1.0]`); an unsolved game earns dense partial credit `0.4 * best_green_fraction` (capped below `0.5`, so any solve always outranks any non-solve). This gives RL a gradient even before the policy solves consistently. Additional 0-weight metrics track behavior.

### Quickstart
```bash
prime env install wordle
prime eval run wordle -m openai/gpt-4.1-mini -n 10 -r 3 -s
```

### Environment Arguments
| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `max_guesses` | int | `6` | Maximum number of valid guesses per game. |

### Metrics
| Metric | Meaning |
| ------ | ------- |
| `reward` | Shaped score: `[0.5, 1.0]` for a solve (higher = fewer guesses), else `0.4 * best_green_fraction` |
| `solved` | 1.0 if solved within the guess limit, else 0.0 (0-weight metric) |
| `num_guesses` | Number of valid guesses made |
| `invalid_guesses` | Count of rejected guesses (not five letters, or not a real dictionary word); these do not consume a guess |
| `letters_correct` | Greens in the best guess, normalized to [0, 1] |

### Regenerating the answer pool
```bash
# Curate the ~2,300 most common legal words as answers (recommended)
uv pip install wordfreq
python scripts/curate_answers.py --size 2300

# Or synthesize candidates with an LLM
OPENAI_API_KEY=... python scripts/generate_answers.py --model gpt-4.1-mini --per-topic 25
```
