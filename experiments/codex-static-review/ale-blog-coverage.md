# Coverage of Sankalp Shubham's ALE investigation

Author: Codex. Reviewed 2026-10-20. This is a comparison for the independent
Codex static-review experiment, not a shared detection standard or a set of
adjudicated ALE findings.

Source: Sankalp Shubham, [Honey, I Looked at the Data of a Frontier Benchmark
and Found some Issues: Porting Agents' Last Exam Linux CLI subset to Verifiers
v1](https://sankalp.bearblog.dev/porting-ale-linux-cli-i-looked-at-the-data-of-a-frontier-benchmark-and-found-some-issues/),
dated 2026-09-16, read 2026-10-20. All ALE observations and rollout scores below
are reported by the author; we have not independently reproduced them or pinned
the affected ALE source versions. Some were subsequently fixed upstream.

The comparison describes env-review at commit
`5777b7ec3d227f232d3d12723afb68bcab7bad71`. Later detector changes need a new
assessment. See the [proposal](proposal.md), [scope](../../docs/scope.md), and
[initial run](../../env/XiaomiMiMo/MiMo-V2.6-RL-oss/runs/2026-10-20-initial).

## Assessment

The catalog categories can represent the dataset-level failure families in the
post. The proposed review criteria address most conceptually. Implemented
detection is much narrower, and we have no measured recall on ALE.

The current structural screen checks MiMo JSON/Python syntax, metadata, rubric
IDs and function references, weights, and manifest upload sources against the
pinned file inventory. It does not compare prompt semantics with grader
expectations, inspect system-library compatibility, or validate scientific
references. The derived read-only screen recognizes one particular MiMo pattern:
answer-only grading alongside exposed SQL writes, with known verifier and
dispatcher hashes. It is not a general detector for unenforced constraints.

The initial structural and derived screens each inspected 34 cached MiMo tasks.
The model discovery screens inspected three and six tasks, with different
prompts and scopes; they did not record exhaustive criterion-by-criterion
coverage. Their results cannot establish sensitivity to the ALE examples.

## Failure-family comparison

“Proposed only” means relevant criteria exist in our optional method, but no
implemented detector or completed systematic review establishes coverage.
“Partial” describes an analogous mechanism, not a claim that our code would
detect the ALE task. None of the screens has been run against ALE.

| Reported issue and concrete example | Catalog fit / scope | Actual detection coverage |
| --- | --- | --- |
| Hidden output schemas, enums, types, or ordering. Moodle accepts `zero` but the agent writes `count_as_zero`; clinical-trial CSV headers differ; survival says `ph_test` is flexible but rejects `ph_test.tests`; ETL expects an ordered name list rather than fill counts. | `specification`, `grader_mismatch`; in scope. | Proposed only. Syntax and metadata validation do not detect these semantic mismatches. |
| Documented schema rejected and undisclosed work required. BPMN governance can receive zero for either mismatch. Building control also has undocumented output conventions. | `grader_mismatch`, `specification`; in scope. | Proposed only. Need to trace each grading condition to the solver-visible contract. |
| Answers encoded in ordering. Forty causal-inference datasets occur in five-item blocks matching eight listed scenario families; `SCENARIOS[index // 5]` recovers labels and related answers worth 70% of the rubric. | `answer_exposure`; in scope under intended presentation. | No detector. Requires attention to ordering, grouping, filenames, and IDs; literal answer-key searches miss this mechanism. |
| Online answer retrieval and weak information-source restrictions. The Go task forbids an engine or browser, but an agent uses `curl` to recover the exact 168-move game from a public archive. The pathology filename `tumor_001.tif` prompts a search for `tumor_001.xml`. | `answer_exposure` when reachable under the applicable contract; separately `environment_specification` if a necessary restriction is absent or contradictory. | Proposed only. No systematic identifier/answer lookup or network-contract comparison. The pathology example reports attempted lookup, not established annotation retrieval. |
| Incomplete dependency specification. The lake-calibration binary needs undeclared system libraries. A required MuJoCo development wheel returns 404 and is absent from the humanoid task archive. | `environment_specification`, potentially `unreachable`; in scope if the published contract cannot support the task. | Partial asset-existence check only: manifest upload paths. No dependency closure, ABI/library check, external availability check, or environment reconstruction. |
| Missing, corrupt, or scientifically wrong references. Chisel source-location truth contradicts the supplied evidence; variant-annotation truth appears to mishandle deletion normalization and allele-specific ClinVar. | `incorrect_reference`, sometimes `grader_mismatch`; in scope. Preserve the tentative wording of the variant claim. | Partial for absent manifest assets or malformed JSON. No scientific validation or general binary-format integrity check. |
| A prohibited strategy still earns reward. Healthcare bias reproduction permits a direct race bonus through its output-only scorer; the reported controlled probe scores 0.861. | `grader_mismatch`, `reward_shortcut`; in scope. | Strongest existing analogue: the confirmed MiMo read-only finding and its derived screen. That screen does not detect arbitrary ungraded method constraints or this ALE case. |
| Task-specific scorer fails on a submission. Ranking feature recovery treats a string payload as a mapping and crashes. | `grader_mismatch` if a permitted submission breaks task scoring; inspect the source to locate the cause. | Syntax errors and limited missing-function references are checked. General runtime type mismatches are not. |
| Requirements cannot jointly hold. Low-thrust trajectory design has conflicting thrust, duration, and velocity-change requirements. | `specification`, `unreachable`; in scope. | Proposed only. Need independent dimensional, numerical, or logical consistency checks. |
| Coarse scores obscure progress. Urban traffic requires all 12 checks to pass; cell tracking's aggregate score hides the failed component. | `scoring`; usually a behavior/observability observation unless evidence establishes a defective criterion. | Partial scoring inspection covers weights/defaults. No general analysis of thresholds, conjunctions, or diagnostic resolution. A zero alone is not evidence of impossibility. |
| Scoring cannot finish within its declared budget. Prostate radiotherapy's matRad scorer repeatedly exceeds a one-hour timeout. | An inconsistent task resource contract can be in scope; insufficient provisioning or a generic runner failure is deferred. Cause unresolved from the post alone. | No timing/resource detector. Static review can flag the assumption; performance requires suitable runtime evidence. |

## Harness boundary and network-policy versions

The post contains implementation problems as well as task defects. Our current
scope distinguishes them by cause:

- **Undeclared dependency:** the lake-calibration task lists Python and a binary
  but omits required `libgd3`, `libgfortran5`, `libgomp1`, and `libx11-6` system
  libraries. This is evidence for reviewing the environment specification.
- **Declared dependency omitted by a port:** the Heisenberg task explicitly
  requires Python, NumPy, and SciPy; the port's image omits them. That belongs to
  the deferred harness layer.
- **Scorer logic versus execution wrapper:** a task scorer mishandling a valid
  payload remains in scope. OpenROAD's reported shell PID-parsing failure occurs
  before its verifier starts and appears to belong to the deferred wrapper
  layer. Confirm the source before assigning a canonical claim.
- **Other infrastructure:** artifact transfer limits, missing chunked streaming,
  ACP/inference integration failures, and provider throttling are outside the
  current dataset reference set.

The author reports that ALE generally permits network access, partly for
dependency repair; some tasks require APIs and others specify restrictions.
Network-policy metadata was not public during the original investigation;
upstream later published five offline tasks. A later contract can change which
presentation conforms to the dataset. Record that contract revision with any
claim, including restrictions in dataset-wide instructions and required
configuration, not just the task prompt.

“No web browser” does not unambiguously forbid every form of HTTP retrieval.
That is a useful specification case to investigate. Conversely, an applicable
explicit requirement that the VM be offline should be assumed enforced in this
phase; a port allowing traffic despite that requirement is a harness issue.
The post's online rollouts alone do not establish a defect under every later
contract version.

## What to test next in this experiment

These are proposed experiments, not implemented checks or collaboration-wide
requirements. Several can run without executing downloaded task code:

1. **Output-contract comparison.** Extract accepted keys, enums, types, ordering,
   tolerances, and required artifacts from task graders as inert source. Compare
   each with the intended instructions and supplied schemas. A useful witness
   is a permitted answer that the stated condition rejects, or an exact pair of
   contradictory requirements. This is a more focused model review than asking
   a model to solve the whole task.
2. **Implicit answer exposure.** Review names, IDs, ordering, and grouping across
   all assets visible within a task. Check metadata-to-label relationships with
   independent analysis. Where the contract exposes relationships across tasks,
   review those too. Do not attribute audit-only corpus ordering to the solver.
   A pattern is a candidate until its visibility and consequence are supported;
   intended retrieval and scientifically meaningful features are not defects.
3. **Dependency and input inventory.** Compare declared packages, binaries,
   libraries, versions, resource requirements, and referenced artifacts against
   supplied assets. Check public artifact availability without installing or
   running it. Distinguish an unavailable URL from proof that no supported
   alternative exists. Binary dependency inspection must not execute the binary
   or invoke its dynamic loader.
4. **Obligation-to-grader comparison.** Map required and prohibited methods to
   what the grader observes. Look for both valid answers rejected and prohibited
   strategies rewarded. Treat our read-only rule as one specific mechanism.
5. **Independent reference and feasibility checks.** Recompute small quantities
   or trace authoritative evidence. Flag physical contradictions, impossible
   state transitions, and inconsistent references. Domain-specific checks and
   scorer timing will have different evidence and execution needs.

Build a small, pinned set of source-backed ALE cases from distinct mechanisms
before scaling an optional detector. Recover the actual prompt, grader,
relevant assets, contract, and version for each claim; try to refute it; then
adjudicate it separately from detector outputs. Cases used to design these
checks are development examples, not held-out evidence of generalization.
Other investigators can evaluate their own methods against an adjudicated
snapshot without adopting this procedure.

## Limits of using ALE-Gold as reference data

The author reviewed 105 public Linux CLI tasks and excluded nine, leaving 96.
The nine exclusions are not all the problems described in the post, and are
not all unambiguously dataset defects under our scope. The author explicitly
retained some questionable tasks; the engineering discussion describes further
issues among retained tasks.

Likewise, a successful rerun does not establish that a repair is coherent. The
ETL prompt patch produced a 1.0 rollout, but later inspection still found its
ordering instruction contradicted the scorer. Use revision-specific claims
and witnesses; do not label every retained or patched task as a clean negative.

The post links an [upstream PR](https://github.com/rdi-berkeley/agents-last-exam/pull/66)
and a [fix commit](https://github.com/rdi-berkeley/agents-last-exam/commit/75a3f866535946b67f9a57e4f158eb30ad50be8a).
These are starting points for recovering evidence, not independently verified
fixes in this comparison. No ALE records were added to the canonical index by
this review.
