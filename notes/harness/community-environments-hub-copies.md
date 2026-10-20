# Prime Intellect hub: environment copies have no version attribution

Observed: 2026-10-20  
Dataset: `gh:PrimeIntellect-ai/community-environments`

## Observation

The Prime Intellect Environments Hub allows any user to republish an
environment under their own namespace without version attribution or a
traceable link to the canonical source. When a verifier bug exists in the
canonical `community-environments` submission, all hub copies inherit the
same bug silently with no notification mechanism.

### Confirmed example: mastermind

The mastermind environment was authored by `xlr8harder` and merged into
`community-environments` in commit `305d7e6` (2025-10-20). The same
environment appears on the hub under at least five namespaces:

- `xlr8harder/mastermind` (author's own listing)
- `primeintellect/mastermind`
- `juyoung/mastermind`
- `prime-community/mastermind`
- `petern/mastermind`

The latent `ord()-48` index bug documented in finding ER-91c19cbf exists in
`scoring.py` of the canonical source. Any hub copy that shares the same
verifier code inherits the bug without the copy author being aware.

## Why this matters for env-review

Findings filed against `gh:PrimeIntellect-ai/community-environments` at a
pinned revision should be understood as affecting all hub copies of the same
environment that were taken from that revision or earlier. A separate finding
per hub namespace is not needed if the verifier code is byte-identical to the
canonical source — the blast radius is wider than the single dataset entry
implies.

## What was not checked

- Whether hub copies are byte-identical to the canonical source or contain
  local modifications
- Whether Prime Intellect has a private version-tracking or notification
  mechanism not visible in the public hub interface
- The full list of environments with multiple hub copies beyond mastermind

## Relation to task findings

This note is background for interpreting the scope of findings in
`env/PrimeIntellect-ai/community-environments/findings/`. It does not itself
claim a task defect and is not indexed as a finding.
