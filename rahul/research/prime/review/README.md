# Independent Countdown rule review

Pinned source: `../sources/sami__countdown__e821f68a918d/countdown.py`.
The source system prompt permits `+`, `-`, `*`, `/`, each of six numbers at most
once, any subset of those numbers, and positive integer intermediate results.
`countdown_oracle.py` checks those rules for one bounded expression using an AST
and exact fractions. It never evaluates the expression as Python code.

On Slurm `amd-tw-verification`, job 55676 ran `verify_countdown.py` against the
pinned source and completed with exit code 0. The source generator with seed 339
and `ensure_solvable=False` produced numbers `[2, 5, 3, 2, 50, 7]`, target 125.

| Expression | Independent rule verdict | Source `validate_solution` |
| --- | --- | --- |
| `(5/2)*50` | Invalid: `5/2` is fractional | Valid: `Correct! 125 = 125` |
| `(5*50)/2` | Valid | Valid: `Correct! 125 = 125` |
| `5**3` | Invalid: exponentiation is outside the permitted operations | Valid: `Correct! 125 = 125` |

The source validator checks the final value but leaves its intermediate-integer
check unimplemented, and its character allowlist permits both asterisks in
`**`. Its exact-match reward calls this validator, so these invalid expressions
are eligible for exact-match reward on this generated puzzle. The paired
component probe is needed to observe the full parser/rubric score.

Wordle's unsolved-game partial credit and reverse-text's sequence similarity
are explicit rubric choices, not defects by themselves. Wordle's source also
caps full rollouts at `max_turns = max_guesses * 2`. A direct `guess` call can
show that an invalid word does not consume a valid guess, but does not show an
unlimited number of model turns.
