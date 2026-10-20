# 2026-10-20 calendar_scheduling audit

Full-corpus structural audit of `nvidia/Nemotron-RL-agent-calendar_scheduling`
at revision `8b62cf67e53d02f2eacf1392426ebea9cd4fa635` (3872 train + 128 val).
Discovery experiment, not a leaderboard.

## What was checked

1. **Feasibility** — does every `exp_cal_state` admit a non-overlapping schedule
   within 10:00–16:00? Parsed each event's constraint (`after`/`before`/
   `between`/`at`/`null`) into a start-window and brute-forced non-overlap
   scheduling over all event orderings. **Result: 0/4000 infeasible**, full
   parse coverage.
2. **Trajectory consistency** — do any assistant turns in the shipped
   conversations contain overlapping events, per the grader's own
   `is_event_conflicting`? Replicated `time_to_minutes` + `extract_json_list` +
   `is_event_conflicting` and ran over every assistant turn. **Result: 0/42547
   conflicting turns.** The 18% of turns with no extractable calendar are
   genuinely conversational (no `event_id`/`start_time`), not regex misses.
3. **Conflict design** — placing each event at the earliest time its own
   constraint allows, do requests collide (requiring reschedule)? **72% of all
   samples** (92.6% of multi-event) have such soft conflicts, rising to 100% at
   6–7 events — but **0** are hard/unsatisfiable. This is the intended task
   (system-prompt rule 4), not a defect.
4. **Grader extraction** — can the shipped `extract_json_list` score a correct
   response 0? Yes, three ways (echo-example-first, bracket in event name,
   trailing comma). Recorded as finding **ER-f412381d** (`behavior_only`).

## Findings

| Candidate | Outcome |
| --- | --- |
| grader extraction false-negatives | ER-f412381d (behavior_only) |
| feasibility | no finding (0/4000 infeasible) |
| trajectory conflicts | no finding (0/42547) |
| conflict design | no finding (soft, reschedulable) |

## Files

- `run.json` — scope, detectors, models, limits
- `results.json` — raw quantitative outcomes
- `adjudications.json` — candidate→finding mapping and no-finding outcomes
- reproducer: `../../evidence/ER-f412381d/witness_extract.py`

## Limits

Static analysis only; no NeMo Gym rollout or `POST /verify` executed. Grader
read at Gym commit `d96b337`; production pin unconfirmed. Agent-assisted
(Claude Code) static adjudication, not independent human validation. Clean
results are checked-no-defect within this scope, not a clean label.
