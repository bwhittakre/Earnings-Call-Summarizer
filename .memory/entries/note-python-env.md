---
id: note-python-env
type: note
project: earnings-call-summarizer
parent_id: plan-6eca5d31
title: Repo .venv is Python 3.12; keep Angelo out of it
node_label: Python environment
tags: gotcha,environment,python,venv,setup
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:03:00+00:00'
updated_at: '2026-08-18T14:30:00+00:00'
---
Read this before running anything in this repo.

## The repo venv (rebuilt 18 Aug 2026)
`.venv/` at the repo root is a **Python 3.12.10** environment created from
`C:\Users\BobbyWhittaker\AppData\Local\Programs\Python\Python312\python.exe`.
Use `.venv\Scripts\python.exe` for pipeline work and pytest.

`pandas` is pinned `>=2.2,<3` in `Structured Narrative/requirements.txt`. The
18 Aug rebuild resolved **pandas 2.3.3**. System Python 3.12 currently has
pandas **3.0.5** (the version Angelo pulls); do not run scoring on system
Python if you can use the venv instead.

Smoke after rebuild: 61 passed in `test_evaluate_narrative_signals` +
`test_quant_quality`.

## What used to be broken
The previous `.venv` was created on Python **3.14.6**, and that interpreter was
removed from the machine. Every console script then failed with exit 103.
That venv was deleted and replaced on 18 Aug.

## Do not install Angelo into this venv
Angelo 1.7.23 pulls **pandas 3.0.5 and numpy 2.5.2**. Scoring and panel code
expect pandas 2.x. Angelo lives in its own isolated environment at
`C:\Users\BobbyWhittaker\AppData\Local\angelo-venv`.
