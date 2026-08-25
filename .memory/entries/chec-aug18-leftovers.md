---
id: chec-aug18-leftovers
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-6eca5d31
title: '18 Aug: 3.12 venv rebuilt, Angelo hooks adopted'
node_label: '18 Aug leftovers'
tags: checkpoint,venv,python,angelo,hooks,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-18T14:30:00+00:00'
updated_at: '2026-08-18T14:30:00+00:00'
---
Leftover cleanup from 17 Aug, done in the Desktop repo window.

## Venv
`.venv` rebuilt on system Python 3.12.10. Dead 3.14.6 interpreter is gone.
Pinned `pandas>=2.2,<3` in `Structured Narrative/requirements.txt` because system
Python now has pandas 3.0.5 (the version Angelo pulls) and scoring still expects
2.x. Installed venv: pandas 2.3.3, numpy 2.5.2, pyarrow 24.0.0, streamlit 1.61.1,
pytest 9.1.1. Smoke: 61 passed in `test_evaluate_narrative_signals` +
`test_quant_quality`.
Angelo stays in `C:\Users\BobbyWhittaker\AppData\Local\angelo-venv`.

## Hooks
Adopted `hooks.json.new` (Angelo 1.7.23 managed hooks) and deleted the leftover
`.new` file.

## Memory tracking (agreed, not committed)
User chose: finish venv + hooks now; commit the memory tree later on request.
`.gitignore` carves out the retired scraper's stores. `no-auto-commit.mdc`
updated so main-repo `.memory/entries/` is intended to be tracked; agent still
never commits unless asked; `mcp.json` stays uncommitted (machine-specific
angelo-venv path).
