---
id: chec-onboard
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-sec-confidence
title: Project onboarded
node_label: Project onboarded
tags: onboarding
status: active
success: 'null'
files: ''
open_threads: 0
created_at: '2026-07-08T20:18:00+00:00'
updated_at: '2026-07-08T20:18:00+00:00'
---
Angelo memory bootstrapped for this repo.

## Current state
- Angelo 1.7.5 installed with zettelkasten extra; Cursor MCP config in `.cursor/`
- User preference: no automatic git commits (`.memory/` and `.zettelkasten/` gitignored)
- Main entry point: `main.py` — SEC filing confidence analyzer with EDGAR fetch
- Secondary pipeline: `Structured Narrative/` — dimension scoring, surprise scoring, delta reports
- Key config: `config/edgar.yaml`, `config/fiscal_calendars.yaml`, sector lists under `config/sectors/`
- Requires `ANTHROPIC_API_KEY` in `.env` for LLM runs

## Layout
- `src/` — ingest (EDGAR, filings), LLM, validation, export, pipeline
- `data/filings/` — filing packages per ticker/quarter
- `output_confidence/` — generated Excel outputs
- `tests/` — unit tests
