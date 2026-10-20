# Deferred notes: Prime Environments Hub install and runtime failures

Observed: 2026-10-20
Source: [Prime hub audit](../../experiments/prime-hub-audit/README.md)
(`results.csv`, `reviews.csv`)

This note covers environments that fail to install, import, load or run. Under
[review scope](../../docs/scope.md) those are packaging, library-compatibility
and runtime observations, not task defects. They are not indexed as findings
or counted as broken tasks. Grader and reward defects from the same audit are
listed in the experiment README.

## Observation

We installed each listed hub environment in an isolated microVM and ran 5
tasks × 2 rollouts against a mock model. Failing environments were rerun with
dependency versions resolved as of their publish date:

- **`broken` (398):** failed today and with publish-date versions.
- **`rotted` (64):** failed today but passed with publish-date versions.
- **`undeclared_deps` (19):** passed only after we installed an import the
  package does not declare.

The largest groups:

| Group | Typical cause seen in reviews |
| --- | --- |
| Library changed (`verifiers_api_drift`) | Code written against an older verifiers API: removed classes or arguments, changed method signatures. Most `rotted` environments fail this way. |
| Unlisted package, conflicting requirements | Imports missing from `dependencies`. Unbounded requirements that now resolve to incompatible majors. Dependencies that do not exist on the package index. |
| Packaging mistakes | Wheels that omit sibling modules or data files. CWD-relative paths. Paths on the author's machine. Unedited `uv init` or template packages without `load_environment`. |
| Dataset unavailable | Gated or private Hugging Face datasets, or data never shipped in the wheel. |

A separate pattern affects rewards rather than crashes. Several graders read
chat messages with dict-only accessors (`isinstance(msg, dict)`, `msg["content"]`).
Under verifiers 0.3.1, which their open-ended `verifiers>=...` requirement
allows, messages are typed objects. These graders score every reply 0 or a
constant. The experiment marks them `hollow` because a user installing today
gets meaningless rewards. The cause is library drift, and each review's
explanation says so.

Reviewers checked a stratified sample of 92 automated failures. They judged
74 to be real environment problems, 17 to be caused by our setup, and 1
unclear.

## Relation to other notes

The five mastermind hub copies listed in
[community-environments-hub-copies.md](community-environments-hub-copies.md)
(see finding ER-91c19cbf) behave differently in our run (verifiers 0.3.1):

| Hub copy | Version | Verdict | Error |
| --- | --- | --- | --- |
| `primeintellect/mastermind` | 0.1.2 | broken | `MastermindEnv.is_completed() missing 1 required positional argument: 'state'` |
| `xlr8harder/mastermind` | 0.1.2 | broken | same |
| `juyoung/mastermind` | 0.1.0 | rotted | same; passes with publish-date versions |
| `petern/mastermind` | 0.1.0 | rotted | same, in a locally defined subclass |
| `prime-community/mastermind` | 0.1.2 | works | none |

This supports that note's observation that hub copies diverge without visible
version attribution. Here the copies differ in which library versions they
run with, which is separate from the latent scoring bug in ER-91c19cbf.

## What was not checked

- Prime-hosted execution: sandboxes, authenticated features, and hosted V1
  runtimes.
- Failures that need credentials, Docker, a GPU, or an LLM judge
  (`unverifiable_here`, 361 environments).
- Whether authors have since fixed the environments. Results reflect the hub
  and the package index as of 2026-10-20.
