# Prime Intellect Environments Hub audit (2026-10-20)

Author: Daniel Zautner, with AI coding agents. Status: completed run on
2026-10-20. This is one investigation's method and raw results, not a shared
standard. Agent review is not independent human validation.

We installed every environment on the Prime Intellect Environments Hub and ran
it. We then checked whether its reward separates the environment's own
reference answer from nonsense. Most of the results describe whether an
environment installs and runs at all. Under [review scope](../../docs/scope.md)
those are deferred packaging and runtime observations, not task defects. They
are recorded here and summarized in
[notes/harness/prime-hub-runtime-failures.md](../../notes/harness/prime-hub-runtime-failures.md).
They are not indexed as findings.

Grader and reward defects are in scope. For an environment whose hub package is
byte-identical to a pinned public repository, we file a catalog finding
(currently [ER-5c3e9a71](../../env/PrimeIntellect-ai/community-environments/findings/ER-5c3e9a71.yaml)).
Most hub environments are uploaded directly to the hub, with no public git
repository or dataset revision to pin. Their reviewed defects stay in
`reviews.csv` (`genuine=true`) until someone pins them to a source revision.

## Files

| File | Contents |
| --- | --- |
| `results.csv` | One row per hub environment, with automated outputs, the final verdict, and agent-review evidence where it exists. |
| `reviews.csv` | One row per agent review: failure audits, fake-scoring reviews, and scoring reviews. Kept separate from the automated outputs. |
| `summary.json` | Counts per verdict, review decision, and scoring-check outcome. |

## Provenance

- **Automation:** our own harness. It installs from the hub inside one
  Firecracker microVM per environment and runs `vf-eval` against a local
  OpenAI-compatible mock model.
- **Reviewers:** Claude-family coding agents in the Oh My Pi harness. The
  orchestrator was claude-opus-5-5. Read-only reviewers ran as the harness's
  faster "scout" agent type, and reviewers that could write ran as "task"
  agents. The exact model per reviewer was not recorded. Token counts and cost
  were not recorded.
- **Not done:** no human adjudication.

## Method

1. **Inventory.** We listed all 1,835 hub environments and downloaded
   each one's source and metadata.
2. **Run check (stage 1).** Each environment was installed from the hub in its
   own Firecracker microVM, using the same command shape as
   `prime env install`. We imported it, called `load_environment()`, and ran
   5 tasks × 2 rollouts with `vf-eval` against the mock model. The mock always
   returns the same nonsense reply, `I think the answer is 0.\n\n\boxed{0}`.
   The judge calls those environments make got the same reply. A pass means
   the environment installed, loaded, ran and wrote numeric rewards.
3. **Scoring check (stage 2).** On the same tasks, the mock replied with each
   task's own reference `answer`. We sent it in several formats (raw,
   `\boxed{}`, XML tag, the environment's parser format) and compared the
   result with the nonsense reply. Outcomes: `scales`, `weak`, `flat`,
   `inverted`, `no_gold_hits` (the reference never reached the scorer),
   `no_answers`, and `not_run`.
4. **Publish-date rerun.** Failing environments were reinstalled with
   dependency versions resolved as of their publish date. `rotted` means the
   environment fails today but passed with publish-date versions. `broken`
   means it failed both ways.
5. **Fake-scoring scan and review.** A static scan flagged constant rewards,
   placeholder or dummy rows, swallowed dataset-load errors, and code that
   mentions the hub's quality scan. Agents reviewed the flagged environments.
6. **Agent review.** Agents read the source and run logs for three sets:
   a stratified sample of stage-1 failures (`failure_audit`), the fake-scoring
   flags (`fake_scoring_review`), and every environment whose reference answer
   did not clearly beat nonsense (`scoring_review`). Some scoring reviews blamed
   our answer format (`harness_format`). For those we replayed the reference in
   the format the environment requires and recorded the outcome in `replay`.
   That replay moved some of them to `grader_bug`.

Verdicts are assigned in this order:

1. `hollow`: a review confirmed fake scoring, or a scoring review found a
   genuine `grader_bug` or `reward_not_correctness` defect.
2. `not_installable`: not installable from the hub (no built package).
3. `works`, or `works_weak_reward` when a review found weak scoring: passed
   stage 1.
4. `undeclared_deps`: passed only after we installed an import the package
   does not declare.
5. `unverifiable_here`: blocked on a prerequisite we did not provide.
6. `harness`: our harness failed.
7. `listed_but_missing`: the listing returns 404.
8. `unverifiable_here`: a failure audit judged our setup at fault.
9. `rotted` or `unverifiable_here`: from the publish-date rerun.
10. Otherwise `broken`.

## Results

| Verdict | Environments | Meaning |
| --- | ---: | --- |
| `works` | 859 | Installs, loads and runs, and produces scores. |
| `works_weak_reward` | 2 | It runs, but its score only loosely tracks whether the answer is right. |
| `undeclared_deps` | 19 | Works only after installing a package the environment uses but forgot to list. |
| `rotted` | 64 | Broken today, but it worked with the package versions from the day it was published. |
| `broken` | 398 | It fails today and also failed with the package versions from its publish date. |
| `hollow` | 76 | It runs without errors, but its score or its tasks are fake, so its numbers are meaningless. |
| `not_installable` | 6 | Not installable from the hub (no built package). |
| `unverifiable_here` | 361 | It needs something we didn't provide, so we can't say whether it works. |
| `listed_but_missing` | 7 | It's in the hub listing, but its page or package is gone. |
| `harness` | 43 | Our testing setup failed, so we have no verdict on this environment. |
| **total** | **1835** | |

Scoring check (stage 2) outcomes for the 925 environments that reached it: `scales` 347, `no_answers` 250, `flat` 230, `weak` 55, `no_gold_hits` 25, `not_run` 13, `inverted` 5.

The verdict counts cover every listed environment and come from automated
runs. Only some environments had agent review: `reviewed_by` is `agent` for
those and `automated` for the rest. In the failure-audit sample, reviewers
judged 74 of the 92 sampled automated failures to be real environment problems; 17 were caused by our setup, 1 unclear (81% of decided cases). Treat unreviewed `broken`/`rotted` verdicts with that
error rate in mind. Do not read them as task-defect prevalence.

### Reviewed grader and reward defects

79 environments have a scoring or fake-scoring review that found a real problem. These are task-level grader, reward or data defects; see `reviews.csv` for full evidence. Some come from library drift: the grader reads chat messages as dicts, and verifiers 0.3.1 passes message objects. That cause is stated in the explanation.

| Environment | Review | Decision | Summary |
| --- | --- | --- | --- |
| `akhildeo/ProverBench` | fake_scoring_review | `hollow` | The flagged except is harmless, but the Lean verifier builds a bare `lake init` project with no Mathlib dependency. Every ProverBench header does `import Mathlib`, so the proof check can never pass and verification_success, the only weighted reward, is effectively always 0. |
| `alaminai/agent_prompt_eval_v2` | fake_scoring_review | `hollow` | The loader passes the literal placeholder token="huggigface_token_here" to load the gated Salesforce/xlam-function-calling-60k dataset. That load fails for every user, the broad except swallows the error, and the env silently swaps in 2 hand-written mock rows. |
| `alaminai/agent_prompt_eval_xlam_60k` | fake_scoring_review | `hollow` | Salesforce/xlam-function-calling-60k is gated. Without HF auth the broad except silently swaps in 2 hardcoded mock examples. On either data path the 'correctness' term reads info['expected_answer'], but the rows carry no info column, so the reward is pure format heuristics. |
| `alaminai/agent_prompt_eval_xlam_60k_v3` | fake_scoring_review | `hollow` | Same bug as v2: a hard-coded placeholder HF token on a gated dataset, a swallowed exception, and a 2-row mock fallback. The v3 env then builds its 'dynamic mock tools' from those 2 rows. |
| `amitprakash2005/anchoring-trap` | scoring_review | `reward_not_correctness` | The only weighted reward is proxy_reward, which pays 0.45 for answering the pre-update anchor (the WRONG answer) and nothing for the correct post-update verdict; correctness (true_update_score) is a weight-0 metric. Gold "NO" gets true_update_score 1.0 but only 0.275, while an anchored wrong answer… |
| `antbuilds/objective-conflict-refund-desk` | scoring_review | `reward_not_correctness` | The only weighted reward policy_held returns 1.0 unless the agent issued an over-cap refund, so a model that never emits a valid ACTION (garbage) or simply stalls gets the maximum 1.0; escalating (the correct action) is weight 0. Same pattern as antbuilds__tool-poisoned-refund-desk. |
| `antbuilds/policy-override-mailroom` | scoring_review | `reward_not_correctness` | The only weighted reward held_policy returns 1.0 unless the agent approved over the $50 cap, so a model that never emits any DECISION line (garbage) scores the maximum 1.0 on every case; escalating (the correct outcome) is weight 0. Same design as antbuilds__tool-poisoned-refund-desk. |
| `antbuilds/tool-poisoned-refund-desk` | scoring_review | `reward_not_correctness` | The only weighted reward is policy_held, which returns 1.0 whenever the agent never issued an over-cap refund, so a model that never emits a valid ACTION (garbage) gets the max reward 1.0 on every task. Escalation/lookup (actual task completion) are weight 0, so doing nothing ≡ perfect agent. |
| `arasaki/leetcode-solver` | fake_scoring_review | `hollow` | The flagged rows are real test harnesses. The real problem is that correctness_reward (weight 0.6) reads test_code from kwargs['info'], while build_dataset stores test_code as a top-level column with no info, so execution never runs and only AST-style heuristics score. |
| `arcee-ai/bfcl-v4-web-search` | fake_scoring_review | `hollow` | The default hf_dataset_name="bfcl_v4_web_search" has no namespace, so it does not exist on the Hub (the README points to arcee-ai/bfcl_v4_web_search). The error is printed and swallowed, and the dataset becomes a single 'What is 2+2?' row. |
| `arcee-ai/bfcl-v4-web-search` | scoring_review | `grader_bug` | The rubric is built as vf.Rubric() and then rubric.reward_funcs/reward_weights are assigned as plain attributes, which current verifiers ignores, so exact_match_reward/subanswer_reward never run (they are absent from the metrics) and reward is 0 for everything. Also the HF dataset id "bfcl_v4_web_s… |
| `austinmw/hosted-online-eval-shape-probe` | scoring_review | `reward_not_correctness` | This is a debugging probe published as an env: shape_reward only logs the completion shape and returns a constant 0.789 for any non-null completion (0.456 if a message has None content), never comparing to the answer "OK". Gold and garbage are identical by construction. |
| `aymaneo/metamedqa` | scoring_review | `grader_bug` | Under verifiers 0.3.x completion messages are pydantic objects, so `isinstance(last, dict)` fails and str(last) ("role='assistant' content='A' ...") is scanned; _first_letter then returns 'R' from 'role', so even the exact gold letter scores 0 (version rot). |
| `bhogan94/q-programming-language` | scoring_review | `grader_bug` | q_reward_func looks up test cases with prompt[0]["content"], but at scoring time prompt[0] is the env's system message ("You are an expert Q language programmer..."), while the map was keyed on the dataset's first (user) message, so the lookup always misses and the fallback returns a constant 0.5 f… |
| `cardan05/certainty-collapse` | scoring_review | `reward_not_correctness` | By default (hidden_weight=0.0) the training reward is 100% self_certainty — the mean sampled-token probability from logprobs — and correctness has weight 0, so gold (correctness=1.0) and garbage score identically; with our logprob-less mock self_certainty is 0 for both. This is an intentional RLIF … |
| `chaiko/hacking-ctf` | scoring_review | `reward_not_correctness` | 40% of the reward (flag_accuracy) requires a literal FLAG{...} string that the explanation-style questions never reveal, and the rest is substring matching against info.techniques/mitigations lists, not the reference answer — so the env's own reference answer scores only 0.09. A correct expert answ… |
| `charles/spreadsheet-ops-agent` | scoring_review | `grader_bug` | Gold raw is exactly the truth JSON, yet reconciliation_reward=0: _parse only reads text when completion[-1] is a dict and otherwise uses "", so under the installed verifiers (whose message objects support .get but are not dicts) every reply parses to None. [INFERENCE] same root cause as harleycoope… |
| `chepp/search-engine-simulator` | scoring_review | `reward_not_correctness` | No submitted code is executed: the reward is syntax-parses (0.2) + expected name defined (0.35) + style heuristics (0.2) + substring 'algorithm patterns' (0.25), so any parseable snippet containing the right keywords scores well regardless of correctness — e.g. the bare task id 'snippet_extractor' … |
| `cosmonaut/app-pot-code-eval` | fake_scoring_review | `hollow` | The whole dataset is a generated placeholder ('Write solve() that returns {i*2}') marked with a TODO to replace it. compilation_reward is not constant (it requires the code to compile), but the task carries no signal. |
| `d42me/bio-search-l3` | scoring_review | `grader_bug` | l3_heuristic_reward only reads the final response from messages where isinstance(msg, dict); under verifiers 0.3.x completion messages are pydantic objects, so response stays '' and every rollout returns 0 — even the verbatim reference answer, which should get ~0.65 from term overlap + no-hallucina… |
| `danielsveryown/vf_sycophancy_env` | scoring_review | `grader_bug` | The reference answer is stored in a dataset column `neutral_answer` that never reaches `state`, so state.get('neutral_answer','neutral') always returns 'neutral', the embedding-similarity term is skipped (semantic_score=1.0), and reward = 1.0 for any reply lacking a handful of flattery keywords (al… |
| `danruif/cot-theater` | scoring_review | `reward_not_correctness` | With default load_environment args every rubric weight is 0.0 (four proxies and correctness all default 0, three true metrics hard-coded 0), so the reward is identically 0 although the correctness metric itself works (gold correctness=1.0). |
| `dmnsh001/faultyjudge` | fake_scoring_review | `hollow` | The only reward function is `def rf(): return 1`. The 'faulty judge' interaction is unimplemented: env_response returns [] and its body is commented out. |
| `dmnsh001/LitBench` | scoring_review | `grader_bug` | Preference labels are inverted: with flip=False the prompt shows the rejected story as Response 1 and accuracy rewards score1>score2, and with flip=True it swaps scores so it again rewards the rejected story scoring higher — the env trains models to prefer the lower-upvoted story. (Gold 'A'/'B' is … |
| `dome/recipe-tool-use` | scoring_review | `grader_bug` | exact_match_reward treats completion as a string (completion.split("\n")), but in this chat ToolEnv completion is a list of messages, so it raises AttributeError and scores 0 for every rollout; the exact gold "160" therefore gets 0 like garbage. The env can never give a non-zero reward. |
| `donal/causal-inference-experiment-design` | scoring_review | `grader_bug` | check_conceptual_reasoning (weight 0.40) uses re.search but the module never imports re (only the other two scorers import it locally), so it raises NameError and scores 0 for every response, capping reward at 0.60. Also check_answer_completeness reads info["messages"], which the dataset never sets… |
| `dsm/irr-calculator` | scoring_review | `grader_bug` | Gold raw is the target JSON ({"irr_pct": -14.39, "decision": "PASS", ...}) yet irr_reward=0, and even garbage got exactly 0 although _tiny_reward_if_relevant would give it 0.01: _get_assistant_content skips every message that is not a dict and the fallback also requires a dict, so under the install… |
| `dynamo-ai/medqa-followup` | scoring_review | `grader_bug` | The weighted reward, accuracy_reward, hands the raw completion message list to MedQAParser.parse, which calls re.search on it. That raises 'expected string or bytes-like object, got list', the rubric catches it, and the score becomes 0. The weight-0 per-turn metrics also see empty text because thei… |
| `fenil/swe-task` | fake_scoring_review | `hollow` | Without explicit use_sandbox=True, load_environment() silently drops to a 'lightweight' SingleTurnEnv whenever it detects vf-eval in argv, pytest, or no Prime credentials. That env scores 1.0 for any non-empty reply and defaults to num_examples=1. If HF loading fails it also swaps in a 'dummy' task. |
| `harleycooper/cree1865-dictionary-qa` | scoring_review | `grader_bug` | With completion exactly "atim" and answer "atim", exact_reward=0, length_reward=0 and char_f1=0.08, so _extract_response did not get the text: it only handles dict messages and otherwise falls back to str(completion), i.e. the repr of the message-object list (~95 chars containing "atim"), leaving o… |
| `henriquegodoy/extract-zero` | scoring_review | `grader_bug` | Exact gold JSON scores 0 on 4/5 tasks: pyproject pins torch<2.6 but leaves sentence-transformers unpinned, which resolves to transformers 5.x that requires torch>=2.6 and disables PyTorch, so the SentenceTransformer string-similarity path raises and the bare except returns 0 for any reply with stri… |
| `himcules/sycophancy-truth-trap` | scoring_review | `grader_bug` | Every reward function reads the reply through _completion_text, which only returns content when the last completion message is a dict. verifiers 0.3.1 passes pydantic message objects, so the text comes back as "", nothing gets parsed (parse_success is 0), and a correct, non-sycophantic reply scores… |
| `jmedina9/crystal_relaxation` | fake_scoring_review | `hollow` | Defaults mock=True and testing=True give a built-in 2-row NaCl smoke dataset (1 train, 1 eval) and a MockCHGNet that always returns energy 0.05 and zero forces. chgnet is commented out of the dependencies, so even mock=False silently falls back to MockCHGNet. |
| `jmedina9/crystal_relaxation` | scoring_review | `reward_not_correctness` | load_environment defaults mock=True and testing=True, and with the default dataset that selects a smoke-test rubric whose only function _zero_reward returns 0.0, so a user loading the env with default args gets reward 0 for every rollout regardless of the relaxed CIF. The real rubrics (CHGNet energ… |
| `kartikkapoor/meeting_intent` | scoring_review | `grader_bug` | The reply was a valid {"action_items": [...]} JSON object that exactly matches the ground truth, yet even the shape-only format_reward scored 0. That means _completion_text returned "": it skips every message that is not a dict (`not isinstance(msg, dict)`), and the installed verifiers passes non-d… |
| `lassiter/adversarial-reward-hacking` | fake_scoring_review | `weak` | The dummy_rows lead is a false positive: the flagged string is a legitimate gold 'answer' describing good unit tests. However, sycophancy_resistance_reward (weight 0.8) returns a constant 0.8 for any non-flattering reply on 7 of 10 rows, and hidden_token_trap gives +1.0 (weight 0.1) for emitting th… |
| `liuliu/regex-craft` | scoring_review | `grader_bug` | All rewards read task_type/test_strings/expected_matches from kwargs["info"], but _build_dataset stores them as top-level columns and never sets info, so info={} for every row: every task is graded as "generate" with no test strings and any line that compiles as a regex (the exact reference or "I t… |
| `llm-wizard/nemotron-r2e-mini-v1` | fake_scoring_review | `hollow` | load_environment() is an explicit stub that exists to pass the Hub's legacy v0 quality scan: 1 row ('Reply with OK.') and a reward function that always returns 1.0. The real v1 NemotronR2EMiniTaskset (12 pinned R2E commits, hidden-test reward) lives separately. |
| `malisa/graph-navigation-pathfinding` | scoring_review | `grader_bug` | path_correctness (weight 0.6) reads task_type and metadata from kwargs['info'], but build_dataset stores them as top-level dataset columns and never sets info, so task_type is always '' and the function falls through to `return 0.0` even when the path and cost are exactly right. Gold only gets cred… |
| `mariasum/reward-hack-forensics` | scoring_review | `grader_bug` | _extract_json only reads completion[-1] if it is a dict; verifiers 0.3.1 passes completion messages as pydantic CustomBaseModel objects (legacy/types.py:77-88, subscriptable but not dict instances), so every reply (even a perfect JSON diagnosis) parses as None and trace_score returns 0. Secondarily… |
| `maziyar/OpenMed-ClinicalNER` | scoring_review | `grader_bug` | _extract_completion_text only accepts dict messages and otherwise returns ""; verifiers 0.3.1 passes completion messages as pydantic CustomBaseModel objects (legacy/types.py:77-88, subscriptable but not dict instances), so every reward function sees empty text and all five components score 0 for an… |
| `maziyar/OpenMed-MedSimplify` | scoring_review | `grader_bug` | _extract_completion_text only accepts dict messages and otherwise returns ""; verifiers 0.3.1 passes completion messages as pydantic CustomBaseModel objects (legacy/types.py:77-88, subscriptable but not dict instances), so every reward function sees empty text and all five components score 0 for an… |
| `maziyar/OpenMed-PICO` | scoring_review | `grader_bug` | _extract_completion_text only accepts dict messages and otherwise returns ""; verifiers 0.3.1 passes completion messages as pydantic CustomBaseModel objects (legacy/types.py:77-88, subscriptable but not dict instances), so every reward function sees empty text and all five components score 0 for an… |
| `maziyar/OpenMed_HoC` | scoring_review | `grader_bug` | f1/partial rewards read expected labels from kwargs['labels_list'], a dataset column verifiers never passes to reward funcs, so expected is always empty: answering 'none' always scores max and any correct hallmark list gets f1=0/partial=0.25 (garbage 0.69 > gold 0.59). |
| `maziyar/OpenMed_ICD10` | scoring_review | `grader_bug` | _evaluate_accuracy treats its `completion` argument as the extracted code string ("comma-separated codes") but the Rubric passes the full message list; it does str(completion) and splits the list repr on commas, so no reply (gold "\boxed{D13.4}" included) can ever match the codes and accuracy (80% … |
| `maziyar/OpenMed_MedKnowledge` | scoring_review | `grader_bug` | _map_example returns a letter but cais/mmlu's ClassLabel "answer" feature survives the map, so stored answers are 0-3 ints (results.jsonl answer=3,2,1); accuracy_reward normalizes them via 1-indexed LETTER_ALIASES ("3"->"C") or fails on int, so even the correct letter never earns accuracy credit (g… |
| `maziyar/OpenMed_PII_Detection` | scoring_review | `grader_bug` | Under verifiers 0.3.1, completion messages are pydantic objects, not dicts. _extract_completion_text skips any message that is not a dict and returns an empty string, so even structure_reward, which never reads the answer, scores 0 for a gold reply that is a perfectly valid JSON entity array. |
| `maziyar/OpenMed_SNOMED` | scoring_review | `grader_bug` | _evaluate_exact_match and _evaluate_hierarchical do str(completion).strip(). That stringifies the whole message list and never calls parser.parse_answer (MaybeThinkParser with extract_boxed_answer), so even \boxed{<correct id>} never equals the answer. Only the 5%-weight format func responds: gold … |
| `mohad/arabic-math` | scoring_review | `grader_bug` | extract_content only reads messages that are dicts, but current verifiers (0.3.1, unpinned dep) passes message objects, so completion text is always "" and math_reward/format_reward return 0 for every reply, including the exact answer "5". |
| `nair-akash/ladr-axler` | scoring_review | `grader_bug` | The exact reference in the exact required form ("The answer is \boxed{-2,0,1,2}", prompt: "values separated by commas ... ascending, like `-1,2,2`") scores exact_match 0 on all 5 tasks while answered=1, so the box is parsed but the comparison fails. [INFERENCE] normalise.equal needs the per-row `ki… |
| `nekoeiha/judge-cascade` | fake_scoring_review | `weak` | The swallowed_dataset leads are all in offline analysis/ scripts, not on the load path; the default dataset (TruthfulQA, 817 rows) loaded fine. However, the default judge_model="stub" makes the trained reward a length/confidence-word heuristic, and any unparseable answer escalates to the oracle tea… |
| `nekoeiha/judge-cascade` | scoring_review | `reward_not_correctness` | The only weighted reward is routed_reward, which is set by design to the judge's score minus cost, or to teacher_acc - lam*cost when it escalates. It never uses gold_correct. The default judge_model='stub' scores reasoning by length and confidence words, so short replies (gold or garbage) score js≈… |
| `nekoeiha/judge-cascade-esc` | scoring_review | `reward_not_correctness` | Same design as the judge-cascade sibling. The only weighted reward is routed_reward, the stub judge score minus lam*cost. The stub judge scores length and confidence words, so short answers score 0.251 < tau=0.55, escalate, and get teacher_acc - lam*c_frontier = 0.5 whether or not the answer is rig… |
| `nekoeiha/judge-cascade-fooled` | scoring_review | `reward_not_correctness` | Same design as the judge-cascade sibling. Only routed_reward has weight (weights [1,0,0,...]). The stub judge scores 0.251, below tau=0.55, so every rollout escalates to proxy_quality = teacher_acc = 1.0 minus lam*cost = 0.5, whether the answer is right or wrong. gold_correct is a weight-0 canary. |
| `nekoeiha/judge-cascade-gold` | scoring_review | `reward_not_correctness` | Same code as the judge-cascade sibling: the only weighted func is routed_reward = proxy_quality - lam*cost. The stub judge (0.251 < tau 0.55) escalates every rollout, so the reward is teacher_acc 1.0 - 0.5 = 0.5 whether the answer is right or wrong. gold_correct is 1.0 on every gold rollout, but it… |
| `nekoeiha/judge-cascade-jscore` | scoring_review | `reward_not_correctness` | This is the same code as the sibling: only routed_reward has weight, and it equals the stub judge score, or teacher_acc - lam*cost when the answer is escalated. gold_correct is a weight-0 metric. A correct gold answer gets a stub judge score of 0.251, which is below tau=0.55, so it escalates and ge… |
| `olala/biology-sequence-design` | scoring_review | `reward_not_correctness` | Rubric never reads `answer` (a prose summary) and awards 1.0 'not applicable' credit for most property funcs plus a fake protein extracted from any uppercase letters, so the garbage reply 'I think the answer is 0.' scores 3.49 (gold 3.86) with no sequence at all. |
| `olgaharri/recommendation-system-offline-evaluator` | scoring_review | `reward_not_correctness` | All six reward funcs are surface heuristics. completeness is keyword overlap with a one-line spec summary (the `answer`). 'implementation_correctness' only checks that the code parses and contains return, for or if, and pays a flat 0.2 when there is no code. Nothing runs or checks the metrics, so k… |
| `omni-georgio/vcbench` | scoring_review | `grader_bug` | parse_response treats any reply without YES/Y as NO, and also matches 'NO' as a substring. The dataset is generated with ~9% YES, so the sampled answers are all NO and garbage ('I think the answer is 0.') scores 1.0 just like gold. Unparseable output gets credit for the majority class. |
| `oso/syllabify-en` | scoring_review | `grader_bug` | indel_accuracy only reads message content when completion[0] is a dict. Verifiers 0.3.1 passes pydantic message objects, so it falls back to str(completion[0]), the object repr, and scores edit distance against that. The verbatim reference answer therefore scores only about 0.35 instead of 1.0. |
| `ppbhatt500/kernelbench` | fake_scoring_review | `hollow` | The flagged dataset except is minor and did not fire (200 real KernelBench rows loaded). The real problem is the reward: it calls a pre-deployed Modal app 'kernelbench-triton' by name, wraps the call in a broad except, and maps any failure to 0.1. No user without that private Modal deployment ever … |
| `prime-community/BigBench-BBH` | scoring_review | `grader_bug` | _completion_to_text only reads content from dict messages. verifiers 0.3.1 passes pydantic message objects, so it falls back to str(msg), and ChoiceParser takes the first 1-4 letter uppercase token from that repr (e.g. 'ROLE') instead of the label. The exact gold label 'B' therefore scores 0 (versi… |
| `primeintellect/llm-writing-detection` | scoring_review | `reward_not_correctness` | Five style-penalty functions (emoji, quotes, formatting, lists, punctuation) carry 0.45 of the weight and give about 1.0 to any short plain text, so garbage gets a 0.45 floor. Only similarity_reward (0.25) looks at the reference, and the 0.3 judge term needs an external LLM (0 here). The gold Wikip… |
| `primeintellect/reward-bench` | scoring_review | `grader_bug` | pairwise_rf reads the reply from state['responses'][0].choices[0].message.content. That key does not exist in verifiers 0.3.1 state, so every rollout raises KeyError and the except branch returns a constant 0.5 whatever the reply (version rot). A correct '[[A]]' verdict would score the same as garb… |
| `primeintellect/self-reward` | scoring_review | `reward_not_correctness` | load_environment builds a vf.JudgeRubric but never registers a reward function on it (no add_reward_func / funcs). The rubric has nothing to score, so reward is always 0 for every completion. If a function were added it would still need an external judge at <ip>. |
| `pronul/quoridor-path-blocking` | scoring_review | `reward_not_correctness` | None of the five reward functions uses `answer`. They score keyword hits (path/block/opponent), `MOVE:`/`WALL:` regex format, word count and newlines. On top of that, `answer` is just a JSON blob of positions, and the puzzles are generated with an unseeded random.seed(). |
| `sami/countdown` | scoring_review | `grader_bug` | parse_completion reads content only when completion[-1] is a dict; under verifiers 0.3.1 messages are pydantic objects so content is '' and every reward (exact/closeness/format) is 0 even for a valid <solution> (version rot; pyproject only pins verifiers>=0.1.9). Note the env also needs <solution>{… |
| `shashwat23/ifbench` | fake_scoring_review | `hollow` | The flagged dataset fallback is benign: the GitHub clone failed and it fell back to the real HF allenai/IFBench_test, 300 rows. But the reward never checks IFBench instructions. constraint_params is always {}, so constraint_adherence just buckets word or paragraph counts, and the other 0.4 weight i… |
| `shashwat23/ifbench` | scoring_review | `reward_not_correctness` | Constraint parameters never reach the scorer (answer is the constraint-id string and completion is a list, so constraint_params is always {}), so constraint_adherence falls back to pure word/paragraph-count buckets and the other 40% is length/capitalization/punctuation formatting — no reward term c… |
| `shunyaekam/rememo-fs` | scoring_review | `grader_bug` | The filesystem state is a single env-global self._state created once in __init__ via reset(0); verifiers never calls reset(), so all rollouts (concurrently) share example 0's workdir and are scored against example 0's golden, while every dataset row has the identical prompt — per-example grading is… |
| `slayer879/code-suggestion` | scoring_review | `grader_bug` | The exact reference inside <answer> scores 0 on both correctness terms: XMLParser strips whitespace but exact_match compares against the unstripped answer (code completions begin with indentation, so never equal), and token_accuracy deliberately returns 0.0 when response.strip()==answer.strip(). So… |
| `soundsem/pkb-second-brain` | fake_scoring_review | `weak` | The flagged row is a real hand-written reference answer. The rubric, though, is almost entirely reference-independent keyword and markdown counting with sigmoid floors: at most 0.13 of the 1.0 weight depends on the reference, and a nonsense answer gets a fixed floor of about 0.19. |
| `sundai-march-22/clinical-trial-prediction` | scoring_review | `reward_not_correctness` | Getting the trial outcome right is only 15% of the reward; 75% is keyword spotting (info.key_concepts many of which are lifted from the prompt, trial-name/percentage/'Phase N' regexes, connective words like 'because'/'unlike'), so a reply that predicts the WRONG outcome but parrots the prompt's evi… |
| `sweetisland/agentgp-passport` | fake_scoring_review | `hollow` | LATENT: the env currently crashes at load. By default every rubric function has weight 0, so the reward is identically 0. The only reward it advertises for RL (AGENTGP_REWARD_MODE=consistency) is a placeholder that always returns 0.5. |
| `tonyteo/api-migration-assistant` | scoring_review | `grader_bug` | Both reward funcs only read messages that are dicts; under verifiers 0.3.x messages are pydantic objects so text is '' and every reply gets keyword 0 + code_block 0.3 = 0.09, including the exact reference migration (version rot, pyproject only pins verifiers>=0.1.10). Even with dict messages, keywo… |
| `tonyteo/code-qa` | scoring_review | `reward_not_correctness` | code_qa_reward never uses answer/info or runs the code: any syntactically valid Python with no unused imports/functions or magic numbers scores 1.0 (e.g. `pass`), so bug-fixing correctness is unmeasured. Under vf 0.3.x it is worse: non-dict messages fall back to text=str(completion), whose repr par… |
| `unemployedvibecoder/usaco-verifier` | scoring_review | `grader_bug` | The answer is the hidden test-case list, so echoing it can't pass (gold==garbage); but the grader also writes the entire last message verbatim to a .py file and runs it, with no code-fence extraction and no prompt instruction to omit markdown, so a correct solution in the usual ```python fenced rep… |
| `vinayak1998/devops-gym` | scoring_review | `reward_not_correctness` | With default args (no hf_dataset_id / DEVOPS_GYM_ROOT) the env silently falls back to embedded smoke tasks whose answers are prose, while the default oracle_overlap reward only counts +/- unified-diff lines from the answer — so _patch_lines_for_overlap returns [] and reward is identically 0 for any… |
| `vxnuaj/cuda-kernel-generation` | fake_scoring_review | `hollow` | LATENT: the default path loads eval_data/rl_cuda_llm_0424.parquet from Path(__file__).parent.parent. That file is neither in the repo nor in the wheel, so with no dataset_path it silently uses a single hard-coded 'Write a CUDA kernel to add two vectors' row. Today the wheel itself is broken. |
| `walln/graphwalks` | scoring_review | `grader_bug` | Needs a last line 'Final Answer: [..]' (our variants lacked it), but under verifiers 0.3.x non-dict messages are coerced with str(item) = "role='assistant' content='...Final Answer: [a, b]' reasoning_content=None ... tool_calls=None", a single line that never ends with ']', so the end-anchored rege… |
| `wambosec/injection-detector` | fake_scoring_review | `hollow` | The placeholder rows are benign because setup_state replaces them with 15 real prompts. However, the default reward deliberately FLIPS the ground-truth labels, so an accurate injection detector is penalised and an inverted one maxes out. This is not disclosed in the README. |
| `will/summarize-text` | scoring_review | `reward_not_correctness` | The 'answer' is the full source paragraph, so lcs_reward rewards copying the input verbatim rather than summarizing, and sentence_reward requires len(text.split('.'))==3 — i.e. exactly two periods — so a proper three-sentence summary ending in '.' (4 pieces) scores 0 on the main 1.0-weight term. No… |
| `zerozerozerozero/minecraft-mineflayer-lite` | fake_scoring_review | `weak` | The placeholder system/user rows are benign because setup_state rebuilds the prompt from the scenario. But the env ships a hub-test bypass on by default: whenever OPENAI_API_KEY is 'EMPTY'/'DUMMY'/etc., every episode ends before generation with reward 0. The default 'minecraft' backend is also a to… |

## Limitations

- **Mock model.** A scripted model cannot play multi-turn games or use tools
  meaningfully. A pass shows that the pipeline runs and pays a reward. It does
  not show that the environment is a good benchmark.
- **No external credentials.** We had no Prime credentials or Prime sandboxes,
  no Docker, no GPU, no external API keys and no LLM judges. Environments that
  need them are `unverifiable_here`, which is not the same as broken.
- **V1 runtime.** `VERIFIERS_V1` environments ran in verifiers' subprocess
  runtime, not on Prime's hosted infrastructure.
- **Package versions.** Results reflect dependency versions resolvable on
  2026-10-20; most environments resolved verifiers 0.3.1. A later library
  release can break or fix an environment.
- **Small sample per environment.** Each environment ran 5 tasks × 2
  rollouts. Defects limited to rare tasks can be missed.
- **Scoring check limits.** The check needs stored reference answers. Many
  environments store something other than the expected reply in `answer`
  (`answer_not_target`) or grade with a judge, tests or an external service.
  Those environments get no scoring verdict.
- **Review coverage.** Reviews cover samples and flagged sets. They were done
  by agents, not humans, and the static scan can miss fake scoring written in
  other ways.
- **Run evidence not committed.** Evidence strings cite environment source as
  `file:line` within each hub package. They also cite our run logs by name
  (`install.log`, `load.log`, `rollout.log`, `gold_raw.log`, `freeze.log`,
  `probe.json`, `result.json`). Those logs and the third-party sources are not
  committed. Local paths and IP addresses are replaced with `<home>` and `<ip>`.

## Column reference

### `results.csv`

| Column | Meaning |
| --- | --- |
| `env_id` | Hub id, `owner/name`. |
| `source` | Always `Prime Intellect Environments Hub`. |
| `version` | Hub version we installed. |
| `library` | Runtime label declared on the hub (`VERIFIERS_V0` / `VERIFIERS_V1`). |
| `verifiers_installed` | verifiers version that actually installed. |
| `tested_on` | Run date. |
| `verdict`, `verdict_meaning` | Final verdict (see glossary) and its plain-language meaning. |
| `run_result` | Stage-1 outcome: Ran fine, Ran after a fix, Failed, Can't verify here, Our test failed, Listed but missing. |
| `failed_at`, `reason` | Phase and reason in plain words (see glossary). |
| `error_last_line` | Last error line from the automated run, truncated to 400 characters. |
| `publish_date_rerun` | Stage-1 outcome when rerun with publish-date dependency versions. |
| `packages_added` | For `undeclared_deps`, the imports we had to install for it to run. |
| `scoring_check`, `garbage_reward`, `correct_answer_reward` | Stage-2 outcome, mean reward for nonsense, and best mean reward for the reference answer. |
| `reviewed_by` | `agent` if any agent review exists, else `automated`. |
| `review_types`, `review_decision` | Which reviews exist and what each decided. |
| `key_evidence` | Reviewer evidence (`file:line` quotes, log excerpts). Reviews that confirmed a real problem come first. |
| `suggested_fix` | Reviewer's suggested fix, where one was given. |
| `catalog_finding` | Catalog finding id, if one was filed. |

### `reviews.csv`

| Column | Meaning |
| --- | --- |
| `review_type` | `failure_audit`, `fake_scoring_review`, or `scoring_review`. |
| `flagged_as` | What the automation flagged (`phase:reason`, `scaling:<outcome>`). |
| `decision`, `decision_meaning` | Review decision (glossary below). |
| `genuine` | `true` if the reviewer found a real environment problem, `false` if it was our setup or a false alarm, empty if unclear. |
| `explanation`, `evidence`, `user_impact`, `suggested_fix` | Reviewer's reasoning, cited source lines and log excerpts, impact on a typical user, and fix. |
| `replay` | For `harness_format` scoring reviews, the result of replaying the reference in the format the environment requires. |
| `garbage_reward`, `correct_answer_reward` | Same as in `results.csv`. |

## Glossary

### Verdicts

| Verdict | Meaning |
| --- | --- |
| `works` | Installs, loads and runs, and produces scores. |
| `works_weak_reward` | It runs, but its score only loosely tracks whether the answer is right. |
| `undeclared_deps` | Works only after installing a package the environment uses but forgot to list. |
| `rotted` | Broken today, but it worked with the package versions from the day it was published. |
| `broken` | It fails today and also failed with the package versions from its publish date. |
| `hollow` | It runs without errors, but its score or its tasks are fake, so its numbers are meaningless. |
| `unverifiable_here` | It needs something we didn't provide, so we can't say whether it works. |
| `listed_but_missing` | It's in the hub listing, but its page or package is gone. |
| `harness` | Our testing setup failed, so we have no verdict on this environment. |
| `not_installable` | Not installable from the hub (no built package). |

### Reasons (`failed_at` / `reason`)

| Code | Label | Meaning |
| --- | --- | --- |
| `install` | Installing | Installing the package and the packages it depends on, like a user would. |
| `import` | Starting up | Loading the environment's Python code. |
| `load` | Setting up tasks | Building the environment and loading its dataset of tasks. |
| `rollout` | Running tasks | Actually running tasks with the fake model and scoring the answers. |
| `harness` | Our test setup | A step in our own testing machinery, not the environment. |
| `ok` | No problem | Everything ran. |
| `undeclared_dependency` | Unlisted package | It uses a package that isn't in its dependency list; it ran once we installed it. |
| `resolver_conflict` | Conflicting requirements | The packages it needs ask for versions that can't all be installed together. |
| `build_failure` | Package won't build | A package it depends on fails to compile during install. |
| `package_missing` | Package not available | The package isn't available to download. |
| `version_not_on_hub` | Version not available | The listed version can't be downloaded from the hub. |
| `python_version` | Wrong Python version | It doesn't support the Python version we used. |
| `verifiers_api_drift` | Library changed | The code uses part of the verifiers library that was changed or removed in a newer release. |
| `missing_dependency` | Unlisted package | The code uses a package that it doesn't list as a requirement. |
| `relative_import` | Packaging mistake | The code imports its own files in a way that only works on the author's machine. |
| `invalid_taskset_export` | Packaging mistake | The package doesn't expose its tasks the way the newer library format expects. |
| `no_load_environment` | Missing entry point | The package has no load_environment function, the standard way to start an environment. |
| `template_stub` | Unedited template | The author published the unchanged starter template, with no real environment inside. |
| `dataset_load` | Dataset unavailable | Its dataset is missing, private, gated or not shipped with the package. |
| `hardcoded_path` | Reads author's files | It reads a file from a location that only exists on the author's own computer. |
| `requires_env_args` | Needs settings | It needs settings that its README documents but that we didn't provide. |
| `needs_prime_auth` | Needs Prime login | It needs a Prime Intellect account login we didn't provide. |
| `needs_sandbox_runtime` | Needs Prime sandbox | It runs code inside Prime's paid sandboxes, which we didn't provide. |
| `needs_credentials` | Needs API key | It needs an API key or credentials for an outside service. |
| `needs_docker` | Needs Docker | It needs Docker (a container tool) to run, which we didn't provide. |
| `mock_loop` | Needs a real model | A multi-step game or conversation our fake model can't play, so it ran until the time limit. |
| `timeout` | Took too long | It didn't finish within our time limit. |
| `oom` | Ran out of memory | It used more memory than our test machine had. |
| `network` | Network error | A download or connection failed during the test. |
| `exception` | Crashed | It crashed with an error not covered by the other reasons. |
| `no_rewards_written` | No score produced | It ran but never produced any scores. |
| `dist_name_lookup` | Test setup: name lookup | Our test setup couldn't work out the package's install name. |
| `readonly_cwd` | Test setup: read-only folder | The environment tried to write to a folder our test machine kept read-only. |
| `no_v1_cli` | Test setup: missing tool | Our test setup lacked the newer command-line tool these environments need. |
| `v1_on_legacy_path` | Test setup: wrong runner | We ran a newer-format environment with the older-format runner. |
| `vm_failure` | Test setup: VM failed | The throwaway virtual machine running the test failed. |
| `agent_error` | Test setup: agent error | The program inside our test machine that drives the test crashed. |
| `corrupt_result` | Test setup: bad result | The test's result file came back damaged. |
| `incomplete` | Test setup: unfinished | The test didn't finish, so there's no result. |

### Scoring check

| Code | Label | Meaning |
| --- | --- | --- |
| `scales` | Scoring makes sense | Correct answers clearly score higher than nonsense. |
| `weak` | Barely tells apart | Correct answers score only a little higher than nonsense. |
| `flat` | Can't tell apart | Correct answers and nonsense get about the same score. |
| `inverted` | Nonsense scores higher | Our nonsense answer scored higher than the correct answer. |
| `no_gold_hits` | Test didn't land | Our correct answers never reached the environment's scorer, so this test is inconclusive. |
| `no_answers` | No answers to test | The environment has no reference answers, so this test can't be done. |
| `not_run` | Not tested | We didn't run the scoring check for this environment. |

### Scoring review decisions

| Code | Label | Meaning |
| --- | --- | --- |
| `harness_format` | Our format was wrong | The environment is fine; our correct answer wasn't in the format it expects. |
| `harness_pairing` | Answer sent to wrong task | Our correct answer was matched to the wrong question. |
| `answer_not_target` | Test doesn't apply | The environment's stored 'answer' isn't something a model would reply with. |
| `judge_or_external` | Needs a judge | The score comes from an AI judge or an outside service we didn't have. |
| `grader_bug` | Scoring bug | Real problem: a correct answer still scores low because of a bug in the scoring code. |
| `reward_not_correctness` | Score ignores correctness | Real problem: the score doesn't depend on whether the answer is right. |
| `unclear` | Unclear | Reviewers couldn't determine the cause. |

### Failure audit and fake-scoring review decisions

| Code | Label | Meaning |
| --- | --- | --- |
| `genuine` | Confirmed real | A reviewer confirmed the failure is a real problem in the environment. |
| `artifact` | Our setup's fault | A reviewer found the failure was caused by our testing setup, not the environment. |
| `unclear` | Unclear | A reviewer couldn't tell whether the failure is real. |
| `hollow` | Fake scoring or data | A reviewer confirmed the score or data is fake. |
| `weak` | Weak scoring | A reviewer found the score only loosely tracks correctness. |
| `benign` | False alarm | Our automatic scan flagged it, but a reviewer found nothing wrong. |

### Fake-scoring scan flags

| Code | Label | Meaning |
| --- | --- | --- |
| `swallowed_dataset` | Hides data errors | If loading the real data fails, the code silently carries on, possibly with fallback or empty data. |
| `dummy_rows` | Placeholder data | The code contains placeholder or toy tasks instead of (or alongside) real data. |
| `const_reward` | Constant score | A scoring function gives the same score no matter what the answer is. |
| `scanner_gaming` | Mentions quality scan | The code refers to the hub's quality scan, which may mean it was written to pass the scan rather than to be useful. |
