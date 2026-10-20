# Static-review rubric v0.1: 12-task MiMo pilot

**No confirmed answer-correctness or impossibility defect was established in these 12 tasks.** The reviewers produced 19 explicit claims: **5 confirmed constraint-enforcement gaps, 6 unresolved candidates, 4 behavior-only observations, and 4 rejected claims**. A correct compliant solution remains possible in all five confirmed gap cases. This is a lead-generation result, not evidence that five environments are unusable.

The five confirmed gaps are five affected task instances in one broad family: a prohibited state change can leave grading evidence unchanged. Four instances are new to the catalog; one was already known. No task code, grader, tool server, setup script, or solution was executed.

This is one investigation’s experimental method. It is not the collaboration’s standard rubric, and its raw outputs are not canonical labels.

## Run and sample

- Three `gpt-6-luna` subagents, high reasoning effort, four tasks per agent in a shared batch context. The parent Codex agent adjudicated every explicit claim.
- Twelve tasks: the four tasks in the existing catalog plus eight selected with seed `20261020` from the remaining cached sample. This is neither a representative prevalence sample nor a held-out test.
- The [frozen rubric](prompts/rubric.md), [response template](prompts/review-template.yaml), packet instructions, exact assignments, source revision, and acquisition hashes are preserved. Dataset identity/revision stays in collector provenance, outside the reviewer response format.
- See [run.json](run.json), [summary.json](summary.json), [adjudications.json](adjudications.json), and the per-task raw reviews below.

## Per-task results

Counts are claims, not distinct broken tasks. A task can have several statuses. “No claim” leaves the task unlabeled.

| Task | Claims | Confirmed compliance gap | Unresolved | Behavior only | Rejected |
| --- | ---: | ---: | ---: | ---: | ---: |
| [0000 — Tax reconciliation (EN)](raw/s3k_0000_accounting_audit_tax_en_t1_rl_008.yaml) | 3 | 1 | 1 | 1 | 0 |
| [0988 — Hedge reconciliation (ZH)](raw/s3k_0988_finance_insurance_zh_t1_rl_005.yaml) | 1 | 1 | 0 | 0 | 0 |
| [1587 — Beverage variance (ZH)](raw/s3k_1587_hospitality_fnb_zh_t4_rl_003.yaml) | 3 | 0 | 1 | 0 | 2 |
| [2328 — Manufacturing change (ZH)](raw/s3k_2328_manufacturing_quality_zh_t3_rl_007.yaml) | 1 | 0 | 0 | 1 | 0 |
| [1867 — Continuity acceptance (ZH)](raw/s3k_1867_it_information_systems_zh_t3_rl_001.yaml) | 1 | 0 | 1 | 0 | 0 |
| [0807 — CECL hold (EN)](raw/s3k_0807_finance_insurance_en_t1_rl_005.yaml) | 3 | 1 | 1 | 0 | 1 |
| [1806 — DNS closeout (EN)](raw/s3k_1806_it_information_systems_en_t3_rl_001.yaml) | 1 | 0 | 1 | 0 | 0 |
| [1564 — Food incident analysis (EN)](raw/s3k_1564_hospitality_fnb_en_t2_rl_002.yaml) | 0 | 0 | 0 | 0 | 0 |
| [0607 — Subaward review (EN)](raw/s3k_0607_education_research_admin_en_t2_rl_003.yaml) | 2 | 0 | 0 | 2 | 0 |
| [0399 — Scope correction (EN)](raw/s3k_0399_consulting_bizops_analytics_en_t2_rl_006.yaml) | 1 | 0 | 1 | 0 | 0 |
| [0990 — Insurance pricing (ZH)](raw/s3k_0990_finance_insurance_zh_t1_rl_008.yaml) | 2 | 1 | 0 | 0 | 1 |
| [0172 — Inventory reconciliation (ZH)](raw/s3k_0172_accounting_audit_tax_zh_t1_rl_008.yaml) | 1 | 1 | 0 | 0 | 0 |

## What the confirmed findings establish

An available forbidden action is not automatically a flaw: following the restriction can itself be part of the task. These findings go further by tracing a concrete successful mutation path and showing that the task’s grading evidence does not distinguish that violation. They still do not establish an incorrect answer, an impossible task, a higher obtainable reward, or exploitation during training.

| Task | Unobserved prohibited change | Canonical finding |
| --- | --- | --- |
| Finance 0988 | Append execution evidence during a read-only reconciliation | [ER-2f4b62ce](../../findings/ER-2f4b62ce.yaml), previously known |
| Tax 0000 | Change a Yardi asset while the narrow sanity check observes only DealCloud and SharePoint | [ER-2b8fd984](../../findings/ER-2b8fd984.yaml) |
| CECL 0807 | Append a hold event to an unrelated already-held recommendation, leaving checked balances and the selected historical event unchanged | [ER-e51ea1c7](../../findings/ER-e51ea1c7.yaml) |
| Inventory 0172 | Post an inventory adjustment while all active grading criteria read only the written answer | [ER-e29fcf72](../../findings/ER-e29fcf72.yaml) |
| Pricing 0990 | Rewrite an existing baseline’s effective date/provenance while preserving the checked rates and benchmark flag | [ER-d7a08cf2](../../findings/ER-d7a08cf2.yaml) |

These are conditional static proofs for the published standalone scoring path and exposed task tools. An optional external grading implementation or additional deployment guard was not verified. Canonical records include exact source quotations, read-only witnesses, assumptions, and limitations. During adjudication, the user clarified the consequence distinction; the catalog now uses `constraint_enforcement` for these gaps. The frozen v0.1 prompts and substantive raw claims were preserved.

## Leads requiring further adjudication

- **Tax 0000:** approved economic terms, transaction amounts and tax-base figures differ across sources. This may reflect a legitimate comparison or source-precedence distinction; no incorrect reference has been proved.
- **Beverage 1587:** inspected APIs use persisted quantity/amount thresholds without returning them, although the prompt asks for exact threshold comparisons. Availability through every other intended source has not been excluded.
- **CECL 0807:** the memorandum, analytics and ledger use different hotel identifiers and amounts. The ledger supplies a governed narrative linkage that the rubric explicitly accepts; the consequences remain unclear.
- **Continuity 1867:** the standard requires detailed drill evidence before accepting RTO/RPO, while the answer anchor asks for pass conclusions from numerical summaries. A response distinguishing numerical pass from formal evidence sufficiency may satisfy both; no judge rejection has been demonstrated.
- **DNS 1806:** the required signoff and supporting briefing disclose the counts and success rate that the task asks to recompute. Verifying a supplied calculation may be intentional, and the copy-only witness does not account for the required percentage-point margin.
- **Scope 0399:** the named workbook Scope Log contains different options from the target record in Project Controls. The correction is unambiguous and feasible through the database; whether the workbook is wrongly attached or merely contextual remains unresolved.

## False alarms and output quality

- Two claims alleged that final chat replies would never reach `answer.md`. The supplied verifier explicitly materializes the reply before grading. These are rejected, not deferred open harness bugs.
- A claim that finalizing a draft beverage reconciliation evades the sanity rule ignored the state transition: becoming FINAL brings an additional row into the query and makes the check fail.
- A claim that the required insurance minutes were absent confused an audit-cache failure with a missing dataset input, despite the packet’s inventory warning. A separate retry recovered the pinned DOCX, including its 8.30% condition.
- Four claims establish behavior without proving a harmful defect: a 0.5 sanity baseline, partial credit despite failed state checks, tier labels without weighting, and write tools without an established no-write requirement.
- Two raw responses required formatting-only YAML repairs; their malformed versions and feedback are preserved. One claim/check back-reference inconsistency remains recorded in [validation.json](validation.json). Several fields named `quote` contain paraphrases or synthetic query summaries. Do not treat raw evidence strings as verified quotations.
- All 12 responses parse with the collector’s safe YAML loader, contain the 11 requested checks, and reference existing claim IDs. Raw check labels measure what the reviewer reported; they do not establish clean tasks.

## Check coverage

132 possible check entries were returned: 38 candidate, 20 observation, 66 checked-no-issue, 1 blocked, 6 not-checked, and 1 not-applicable. Several checks point to the same claim; 38 flagged checks are not 38 defects.

| Check | Candidate | Observation | Checked, no issue reported | Blocked | Not checked | Not applicable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| specification | 3 | 2 | 7 | 0 | 0 | 0 |
| inputs | 4 | 2 | 5 | 1 | 0 | 0 |
| environment_specification | 6 | 2 | 4 | 0 | 0 | 0 |
| feasibility | 1 | 0 | 11 | 0 | 0 | 0 |
| reference | 1 | 3 | 8 | 0 | 0 | 0 |
| false_negative | 3 | 1 | 8 | 0 | 0 | 0 |
| false_positive | 10 | 0 | 2 | 0 | 0 | 0 |
| answer_exposure | 1 | 2 | 7 | 0 | 2 | 0 |
| verifier | 7 | 2 | 3 | 0 | 0 | 0 |
| reward | 2 | 6 | 3 | 0 | 1 | 0 |
| grader_tampering | 0 | 0 | 8 | 0 | 3 | 1 |

## Comparison with the existing cheap screens

The deterministic structural and derived read-only screens ran on the same 12 task snapshots in **0.436 seconds combined**. Their full output is [baselines.json](baselines.json).

- Structural screening emitted two implicit-sanity-weight signals. Both correspond to the already established 0.5 scoring behavior; neither is a confirmed correctness defect.
- The narrow read-only rule flagged six tasks. Two overlap the five adjudicated compliance gaps (0988 and 0172). It skipped the other three because they have state checks or are mutation tasks, even though the particular prohibited change is unobserved.
- The other rule flags remain screening signals: this pilot did not validate a concrete forbidden mutation for each. An answer-only grader plus write tools is not enough to confirm a constraint violation.
- Luna rediscovered the sole previously confirmed claim: **1 of 1**, now classified as a compliance gap. That tiny, development-contaminated reference supports no useful recall estimate. The prior rejected manufacturing bypass was not reasserted; its new partial-credit claim is a different observation. The tax scoring baseline was rediscovered as an explicit claim, while the analogous hospitality baseline was not.
- The reference contains no confirmed correctness-defect positive in this sample, so this run cannot measure recall for clearly broken environments. Neither an unflagged task nor a rejected claim creates a clean negative label.

## Data access, time and cost

Preparation took **8.8 minutes**. The frozen inventory had 430 files, of which 413 were available to the screeners. Python first failed certificate validation; system curl recovered most files, with 17 remaining timeout/TLS/HTTP2 failures. These were not upstream 404 or access-denied responses. A later two-worker, HTTP/1.1 retry retrieved all 17 in **12.474 seconds** into a separate cache. [Acquisition retry](acquisition-retry.json) records that expanded adjudication evidence; the frozen screening inputs were not changed.

The screeners received 114 extracted document/text assets. Three downloaded images were not extracted. Extraction limits were 100 PDF pages, 5,000 spreadsheet rows, 100 columns and 1,000,000 characters per extract; there was no OCR or formula execution. Cache and extraction gaps cannot be treated as task defects.

The recorded screening window was approximately **45.6 minutes wall time**, including parent interruptions that paused the agents, resumes, formatting, and handoffs. Active model time, token counts, and dollar cost are unavailable and recorded as null. A four-minute-per-task budget was initially soft and was reiterated during the run. The initial tasks took roughly 6–12 minutes to produce files; two later consecutive-task intervals were roughly 3–4 minutes. File timestamps are not per-task active-runtime measurements. This is insufficient for a dependable throughput or cost estimate.

Reviewers shared the filesystem. Withholding prior findings was instruction-based, not technical isolation. One reviewer disclosed an initial broad search that printed task IDs/paths from collector metadata, while reporting no inspection of prior findings, adjudications, or other reviews. Batch contexts also permit learning across a reviewer’s four tasks.

## Implications for the next run

This version finds useful compliance gaps and plausible source conflicts, but has not yet demonstrated detection of a clearly broken environment in the pilot. Scaling it unchanged would measure lead yield and review burden, not produce an automatic broken-task count. Preserve v0.1 if running that comparison; make any revised prompt a separate version.

For this investigation, the next version should distinguish consequence before flagging, require a concrete full witness plus a search for counterevidence, check the availability manifest before claiming missing inputs, trace state changes through grading filters, and separate ordinary partial credit from a demonstrated shortcut. Exact quotations and a submission-format check should be collected separately from semantic judgment. These are experimental lessons, not collaboration-wide requirements.

A broader run should use one task per reviewer context, instrument actual start/end time and usage where available, enforce an explicit cutoff, and report checked/blocked denominators. Cheap structural screening can cover every task; model review can add semantic leads. Review unresolved candidates and a sample of unflagged tasks, then use independently adjudicated positives and negatives to measure detection quality.

## Validation

71 repository tests passed. Catalog validation passed; 42 canonical source quotations were checked against the pinned source. All 413 frozen source-file hashes and all six prompt hashes were unchanged. New witnesses use independent read-only queries and static traces. Original tools and graders were never run.
