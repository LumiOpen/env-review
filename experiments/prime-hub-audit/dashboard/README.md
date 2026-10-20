# Prime Hub audit dashboard (snapshot)

Interactive view of the [Prime Environments Hub audit](../README.md): every one of the 1,835 environments with
our verdict, a plain-language explanation, the step-by-step test result, reviewer findings with evidence,
correct-answer vs nonsense-answer scores, and the first tasks each environment was run on.

## View it

```bash
cd experiments/prime-hub-audit/dashboard
python3 serve.py          # no dependencies
# open http://127.0.0.1:8000
```

`serve.py` answers the dashboard's `/api/*` requests from the JSON files in `data/`, so the app works offline
and deep links (`/env/<owner>__<name>`) can be shared and reloaded.

## What's in the snapshot

- Snapshot of 2026-10-20 (package versions as of that day).
- `data/envs.json`: the table; `data/env/<owner>__<name>.json`: one detail record per environment;
  `data/overview.json`, `findings.json`, `glossary.json`: start page, charts and plain-language glossary.
- Omitted on purpose: raw run logs and environment source code (third-party code). Very long prompts or
  replies are truncated at 4,000 characters.
- Six environments with no installable build on the hub are listed only as "Not installable".

Every coloured tag explains itself on hover; the Glossary page lists all of them. Method and limitations:
[../README.md](../README.md).
