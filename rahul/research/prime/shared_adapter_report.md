# Shared adapter validation

Three Prime Intellect audits now use one Verifiers v0 adapter and three JSON contracts. The 340 lines of bespoke driver code have been removed. Loader selection, dataset binding, interactions, and score selection are declarative; the adapter contains no environment-name branches.

The reusable reference checks cover arithmetic rules, exact text, and longest common subsequence. They examine the actual submitted completion and record facts beside the upstream source reward. They never replace the grader under audit. Probe relations remain reviewed hypotheses.

## Results

All execution used `amd-tw-verification`, with no GPUs, model inference, training, or paid judges.

| Audit | Real task rows | Cases | Preserved findings | Frozen replay |
| --- | ---: | ---: | ---: | --- |
| Reverse Text | 4 | 12 | 2 | Identical |
| Countdown | 1 | 8 | 2 | Identical |
| Wordle | 2 | 14 | 0 | Identical |

Slurm job **55712** completed all audits and replays. Job **55714** verified parity with the original pilot: all case rewards, source metrics, relation outcomes, and finding identities/statuses match. Reverse parsed answers and Wordle game states/tool feedback also match. Each new run verifies and reproduces its own fingerprint and semantic digest; migration changes the engine and input fingerprints by design.

The four source/reference disagreements are the existing findings: Reverse Text strips meaningful answer whitespace and uses SequenceMatcher where its description specifies LCS; Countdown accepts forbidden exponentiation and fractional intermediate results. The [validation record](shared_adapter_validation.json) retains exact scores and reference facts. This migration does not add new upstream defect claims.

An unrelated [token-copy environment](../../examples/verifiers_demo/) used the same module adapter without a custom driver. Its actual Verifiers loader/rubric produced `[1, 0]`, matching the independent exact-text reference. Its archive verified and replay comparison reproduced (jobs55704,55705,55708,55709).

The complete standard-library test suite passed **81 tests**, job **55713**, including source-backed regressions, logged grading failures, wrong-row rejection, tool limits, reference checks, and archived-engine module imports. The first full run exposed a leaking test mock; it was scoped and the full suite rerun. Independent review found no material blocker.

## Reuse and limits

Follow [the contract guide](../../docs/environment-contracts.md) to add a compatible environment. Repeat the Prime collection with:

```sh
sbatch scripts/audit_prime.slurm --output runs/prime-new
```

These are source component checks, not full agent or training validation. Wordle has no independent game oracle yet. Unsupported interfaces need a framework adapter, and new semantic families need reviewed oracles. Trusted execution has no network isolation.

Separate Slurm replay submission exposed an existing dependency issue: installed optional dependencies are overcaptured, including a site-local ROCm torch wheel unavailable from the package index. Archived replay succeeded on compute inside the matching runtime; the collection also replays in that runtime. This provisioning limitation remains documented rather than silently weakening dependency locks. See [implementation evidence](shared_adapter_implementation.json) for jobs, hashes, and limits.
