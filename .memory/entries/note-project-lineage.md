---
id: note-project-lineage
type: note
project: earnings-call-summarizer
parent_id: earnings-call-summarizer
title: Summarizer, Structured Narrative and Roz are three generations of one project
node_label: Three-generation lineage
tags: orientation,architecture,lineage,onboarding,workspace
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:25:00+00:00'
updated_at: '2026-08-17T20:25:00+00:00'
---
Read this first. The repo layout invites a wrong inference about how these pieces relate.

## The progression
They are not parallel experiments or side projects. Each is the next generation of the one
before it, and the lineage is the necessary progression of a single effort:

1. **Earnings Call Summarizer** — the origin, and the git root. Provided the base scaffolding.
2. **Structured Narrative** — built on that scaffolding. The extraction and scoring pipeline:
   dimension scoring, evidence verification, narrative z-scores, the consolidated panel.
3. **Roz** (`services/earnings_monitor/`) — built on Structured Narrative. The dashboard and
   research surface, including the Rank IC Research and Lab pages.

Later generations did not replace earlier ones; they are layered on top and still depend on
them. Structured Narrative produces the artifacts Roz reads.

## Why the layout misleads
Everything lives in **one git repo**, with no nested repo anywhere:

```
Earnings Call Summarizer/          <- gen 1, and the git root
├── Structured Narrative/          <- gen 2
├── services/earnings_monitor/     <- gen 3 (Roz)
├── src/                           <- shared: market data, validation, fiscal calendars
└── tests/                         <- one suite covering all three
```

On disk `Structured Narrative/` sits beside `services/`, so it reads as a sibling directory —
a parallel component — rather than as the generation Roz was built from. It is not a sibling
in any sense that matters. `src/` and `tests/` are shared across all three.

## What `earnings-scraper-main/` is, and is not
It sits at the top level and looks like a fourth component. It is **not part of the lineage**.
It is the Angelo companion project, vendored in on 9 July 2026 — the day after Angelo was
installed — as `earnings-scraper-main/earnings-scraper-main/` (doubly nested, 32 tracked
files, no `.git` of its own). It carries its own `.memory/`, `.zettelkasten/` and
`.cursor/rules/`, which is why rules from it can surface in an agent's context.

Its transcript source is **roic.ai** (`src/roic_client.py`, `scripts/fetch_transcripts.py`,
key at `secrets/roic_api`), with `src/edgar_fallback.py` as backup. But fetching is only one
of three front doors into an `inbox/`; the actual purpose is Angelo grounded extraction
(extractor → scribe → auditor → synthesizer) into a zettelkasten.

That extraction chain is the one the 17 August assessment concluded **should not** be run over
these transcripts: it produces quote-backed claims, which is the job `dimension_scorer.py`
already does with a stricter verification ladder. Treat this directory as the scraper plus an
Angelo demo, not as part of the pipeline.

**It is now largely retired.** As of August 2026 the roic.ai fetch path is superseded by the
**Quartr MCP connector** — a remote server at `https://mcp.quartr.com/mcp`, registered in
`.cursor/mcp.json`, exposing ~46 tools including `read_transcript`, `list_documents`,
`search_documents` and `get_financials` (the last with page-level citation deep-links back to
the source report). Prefer Quartr for any transcript, filing or financials retrieval; reach for
`earnings-scraper-main/` only for something Quartr genuinely does not cover.

Quartr's OAuth registration is scoped to the main repo's Cursor project, so the connector is
unavailable from a scratch-worktree window — one more reason to work from the top-level folder.

## The practical consequence
**Always open the top-level `Earnings Call Summarizer` folder as the workspace.** Cursor keys
chat history, settings and the Angelo memory store to whichever folder path a window is opened
on. Opening `Structured Narrative/` directly:

- registers as a distinct Cursor project with its own, much shorter chat history
- puts shared `src/` and the test suite outside the workspace
- roots a **second Angelo memory store** at the subfolder, fragmenting the tree recorded here

The same hazard applies to scratch git worktrees. See the Angelo memory decision entry for
how a worktree under `AppData\Local\Temp` split reads and writes across two stores.
