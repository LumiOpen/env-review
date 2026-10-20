#!/usr/bin/env python3
"""Witness for ER-f412381d: the calendar reward extractor yields false negatives.

Reproduces three cases where a CORRECT model response is scored reward 0 by the
verbatim NeMo Gym calendar extractor (resources_servers/calendar/utils.py:
extract_json_list, github.com/NVIDIA-NeMo/Gym @ d96b33770392c5d25e03a69a8ced497eecd7298a).

Run: python3 witness_extract.py   (no dependencies beyond the standard library)
Expected: cases B, C, E report FAIL->reward0; A and F report PASS; negative
controls show the extractor never fabricates a correct schedule.
"""
import json
import re

# --- verbatim shipped extractor ---
_PATTERN = r"\[(?:[^\[\]]|\{[^}]*\})*\{(?:[^\[\]]|\{[^}]*\})*\}(?:[^\[\]]|\{[^}]*\})*\]"


def extract_json_list(text):
    m = re.search(_PATTERN, text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


GOOD = [{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 30}]
GOOD_C = [{"event_id": 0, "event_name": "Review [Q3] Budget", "start_time": "10:00", "duration": 30}]

CASES = {
    "A plain correct": (
        'Here is your calendar:\n'
        '[{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 30}]',
        GOOD,
    ),
    "B echoes system-prompt example first": (
        'As a reminder the format is '
        '[{"event_id": 0, "event_name": "event name", "start_time": "10:00", "duration": 60}].\n'
        'Final calendar:\n'
        '[{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 30}]',
        GOOD,
    ),
    "C bracket in event_name": (
        '[{"event_id": 0, "event_name": "Review [Q3] Budget", "start_time": "10:00", "duration": 30}]',
        GOOD_C,
    ),
    "E trailing comma": (
        '[{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 30,}]',
        GOOD,
    ),
    "F fenced json block": (
        '```json\n'
        '[{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 30}]\n'
        '```',
        GOOD,
    ),
}

NEG = {
    "wrong duration (must NOT become GOOD)":
        '[{"event_id": 0, "event_name": "Standup", "start_time": "10:00", "duration": 45}]',
    "example only, no real answer":
        'The format is [{"event_id": 0, "event_name": "event name", "start_time": "10:00", "duration": 60}].',
    "no json at all":
        'Sure, I scheduled it for you this morning.',
}

if __name__ == "__main__":
    print("case                                        verdict")
    for name, (text, ref) in CASES.items():
        got = extract_json_list(text)
        ok = got == ref
        print(f"  {name:40s} {'PASS' if ok else 'FAIL->reward0'}")
        if not ok:
            print(f"      extracted: {got}")
    print("\nnegative controls (extractor must not fabricate a correct schedule):")
    for name, text in NEG.items():
        print(f"  {name:40s} -> {extract_json_list(text)}")
