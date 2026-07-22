# earnings-scraper

Turn earnings-call transcripts/reports into grounded, quote-backed notes in an
Angelo **zettelkasten**, organized into comparable projects (by company, quarter,
sector, or theme).

## How it works

```
   drop files          fetch from the web           (future) Snowflake
 stage_inbox.py      fetch_transcripts.py            pull_to_inbox.py
          \                    |                          /
           \                   |                         /
            v                  v                        v
                        inbox/  (the one front door)
                                  |
                    "process the inbox"  (you ask the agent)
                                  |
        coordinator grounded extraction  (create_extraction_graph)
        driven by LOCAL Cursor subagents — no API key, no driver
                                  |
                                  v
                 zettelkasten: claim + quote notes per source
                 joined into the projects each source matches
```

Everything enters through `inbox/`. The **coordinator** (the Cursor agent) crunches
whatever's there — it spawns local subagents to run the fixed grounded-extraction
pipeline (extractor → scribe → auditor → synthesizer), so no Anthropic/OpenAI/Cursor
API key is required.

## Quickstart

```bash
# 1. (optional) editable install — only needed for the future Snowflake puller
python -m venv .venv && source .venv/bin/activate   # .venv already present
pip install -e .

# 2. Drop some earnings reports into the inbox
python scripts/stage_inbox.py ~/Downloads/AAPL-Q1.pdf --company AAPL --period FY2025Q1
python scripts/stage_inbox.py ~/Downloads/earnings/            # or a whole folder

# 3. In Cursor chat, ask the agent:  "process the inbox"
#    It runs grounded extraction and files each source into matching projects.

# 4. Inspect the results
#    ask: "open the zettelkasten dashboard"   (launches angelo-zk-dashboard)
```

## Secrets & credentials (`secrets/`)

The `secrets/` folder is **gitignored**, so nothing in it ships with a clone —
create the files you need locally. **None are required for the zero-setup
interactive path** ("process the inbox" in Cursor); each one below just unlocks a
specific optional path. All `*_api` files are a single line containing only the key.

| File / var | Needed for | Where to get it |
|---|---|---|
| `secrets/roic_api` | Fetching transcripts (`scripts/fetch_transcripts.py`) | Free key at https://roic.ai (free tier: 5 req/min, 2 yr history). Or `export ROIC_API_KEY=...` instead. |
| `secrets/anthropic_api` | Headless extraction via `stream` (`driver="claude"`) | https://console.anthropic.com → API Keys. Loaded into `ANTHROPIC_API_KEY` by `config.py` / `scripts/env_setup.sh`; or `export ANTHROPIC_API_KEY=...` directly. |
| `secrets/cursor_api` | Headless extraction via the Cursor SDK driver (`scripts/run_extraction.py`, `driver="cursor"`) | Your Cursor account settings (SDK/API key). Only if you use the `cursor` driver instead of `claude`. |
| `secrets/snowflake_key.p8` | The (future) Snowflake transcript puller (`scripts/pull_to_inbox.py`) | A Snowflake key-pair provisioned for **your own** Snowflake user — not shared. See `scripts/env_setup.sh` / `.env.example`. The puller is a stub until a transcript share is granted. |

`.env.example` documents the full set of environment variables (copy it to `.env`,
which is also gitignored). Quick start for the two common paths:

```bash
echo "YOUR_ROIC_KEY" > secrets/roic_api        # to fetch transcripts
echo "sk-ant-..."     > secrets/anthropic_api   # to run headless extraction with Claude
source scripts/env_setup.sh                     # loads the key files into the environment
```

## Fetching transcripts from the web (ROIC.ai + SEC EDGAR)

`scripts/fetch_transcripts.py` pulls earnings-call transcripts straight into
`inbox/` so they feed the same coordinator crunch. Primary source is the
[ROIC.ai](https://roic.ai) transcript API; if it has no transcript for a company
(or the period is outside your plan's history window) it falls back to the most
recent earnings **8-K (Item 2.02)** exhibit on SEC EDGAR.

```bash
# 1. Get a free ROIC.ai key (free tier: 5 req/min, 2 years of history) and put
#    it in secrets/roic_api  (one line), or export ROIC_API_KEY.
echo "YOUR_KEY" > secrets/roic_api

# 2. Fetch — a few shapes:
python scripts/fetch_transcripts.py AAPL MSFT               # latest call each
python scripts/fetch_transcripts.py AAPL --year 2025 --quarter 3
python scripts/fetch_transcripts.py AAPL --last 4           # 4 most recent quarters
python scripts/fetch_transcripts.py AAPL --all              # every available quarter

# 3. Bulk backfill a whole universe (one ticker per line; # comments ok):
python scripts/fetch_transcripts.py --tickers-file scripts/universe_overnight.txt --all --no-fallback
```

Each fetch writes a `<ticker>-fy<year>-q<quarter>-earnings-call.txt` with a small
metadata header (company, period, call date, source, provenance). Existing files
are skipped unless you pass `--force`, so a re-run is safe and resumable.

Notes:
- **`--no-fallback`** is recommended for bulk historical pulls — the EDGAR
  fallback only returns the *latest* 8-K per ticker, so in a backfill it would
  just duplicate. It's most useful for targeted single fetches.
- EDGAR requires a descriptive User-Agent with a contact email; set your own via
  `SEC_USER_AGENT` (see `.env.example` / `scripts/env_setup.sh`).
- The free tier caps at 5 requests/minute, so a ~100-ticker `--all` backfill
  takes a few hours. `scripts/run_overnight.sh` waits for the key to appear in
  `secrets/roic_api`, then runs the universe backfill and logs to `data/`.

## The extraction pipeline (zettelkasten)

The grounded-extraction pipeline is fully wired. Once a transcript is in `inbox/`,
running extraction turns it into `claim` + `quote` notes in `.zettelkasten/`, filed
into every project it matches (company, quarter, sector, theme).

**What's already set up**

- **Lenses** — `.cursor/extraction-schemas.yaml`: `earnings-call` (default),
  `guidance-tracker`, `qa-sentiment`, `kpi-scorecard`. Each is a rubric of tagged
  dimensions that double as the cross-source comparison index.
- **Agents** — `.cursor/agents.yaml`: the fixed trio `extractor → scribe → auditor`
  (plus a `synthesizer` and a `data-*` trio), model-pinned to `claude-sonnet-4-6`.
- **Workflow rules** — `.cursor/rules/earnings-ingest.mdc` (the "process the inbox"
  contract), `grounded-extraction.mdc` (pipeline + schema authoring), `stream.mdc`
  (the headless driver).

**How the pipeline works**

Extraction is one fixed pipeline applied to each source, parameterized by a
**schema** (the lens):

```
per source:  ingest + seed a hub note
   → extractor  (reads the source against the schema; proposes claim+quote candidates)
   → scribe     (commits them as claim + quote notes, tagged by schema dimension)
   → auditor    (checks every claim has a verbatim quote + full dimension coverage)
then once:   linker (cross-source links) → synthesizer (writes the spine prose)
```

Each schema **dimension** carries a `tag`, and the scribe stamps that tag on every
note it creates. Because the same tags recur across companies and quarters, they
become a **comparison index**: query one tag (e.g. `forward-guidance`) and line up
every company's answer. When a schema declares a `synthesis` block, the run also
builds a per-company **spine** (an apex note + one node per dimension) that
accumulates across quarters — the surface the dashboard and CSV matrix read.

**Two ways to run it**

1. **Interactive (no API key).** In Cursor chat, ask the agent to **"process the
   inbox"**. It acts as the coordinator and spawns local Cursor subagents for the
   trio — zero setup, nothing to install.

2. **Headless via the Claude API.** The `stream` capability drives the *same*
   pipeline through a portable driver, so it runs outside Cursor (a script, CI,
   cron, a colleague's machine):

```bash
pip install "angelo[stream]"        # or just: pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...  # or put it in secrets/anthropic_api (see Secrets)
```
```python
import stream

# Extract one or more inbox files into a project using the Claude API:
report = stream.apply(
    ["inbox/aapl-fy2025-q3-earnings-call.txt"],
    project="company-aapl",
    schemas=["earnings-call"],
    driver="claude",                # Anthropic API (default). also "gpt" or "cursor"
    # model="claude-sonnet-4-6",    # optional override
)

# Deterministically export the cross-source comparison matrix (no LLM):
stream.export_csv("company-aapl", "aapl.csv", schema="earnings-call")
```

For always-on ingestion, drop a `stream.yaml` at the repo root and run
`angelo-stream --once` (single pass) or `angelo-stream` (poll forever):

```yaml
defaults:
  driver: claude                    # claude | gpt | cursor
  project: research
feeds:
  - {name: inbox, type: drop_dir, options: {path: ./inbox, glob: "*.txt"}}
schemas:
  rules:
    - {match: {doc_type: txt}, schemas: [earnings-call]}
router:
  default: [research]
  axes: [{type: metadata, key: ticker}]   # one project per ticker
```

**Inspect the results.** Ask the agent to "open the zettelkasten dashboard"
(launches `angelo-zk-dashboard`), or export a deterministic comparison matrix with
`stream.export_csv("<project>", "out.csv", schema="<schema>")`. On disk, notes live
under `.zettelkasten/<source>/` (each source's claims + quotes) and
`.zettelkasten/<label>-earnings/` (the synthesis spine).

**Apply more than one lens.** Schemas are independent lenses over the same calls —
run `earnings-call` for the full picture and, say, `guidance-tracker` to build a
quarter-over-quarter guidance spine. Headless: pass
`schemas=["earnings-call", "guidance-tracker"]` in one `apply(...)`. Interactive:
run a second extraction over the same sources under the same project.

### Filing into projects (projects.yaml)

A **project** is a comparison set a source joins. `projects.yaml` lists them, each
with a plain-English `join_when` the coordinator evaluates per source — so one
transcript is *extracted once* but *filed into many*: its company, its quarter, its
sector, and any theme it matches.

```yaml
projects:
  - {name: company-aapl,      kind: company, join_when: "The source is an Apple / AAPL earnings call."}
  - {name: quarter-2025-q3,   kind: quarter, join_when: "The source's reported period is 2025 Q3."}
  - {name: sector-technology, kind: sector,  join_when: "The issuer is a technology company."}
  - {name: theme-ai-capex,    kind: theme,   join_when: "The call discusses AI capex/monetization materially."}
```

Keeping a company's project stable across quarters is what lets its synthesis spine
accumulate into a trajectory; peers that share a schema line up into a matrix
automatically. Edit `projects.yaml` freely — names are kebab-case and become the
zettelkasten project ids. There's no mechanical router: the coordinator reads the
descriptions and files each source into every project whose `join_when` fits.

### Processing once (dedup)

Nothing gets extracted twice, thanks to two layers:

- **Content-hash dedup (automatic).** Every source enters through
  `source(action="ingest")` → `source(action="create")`, which hashes the file
  bytes. Re-ingesting identical content returns the *existing* source instead of
  creating duplicate notes — so a file read twice never doubles the graph.
- **`inbox/_processed/` archive.** After a source is extracted, its original is
  moved to `inbox/_processed/`; the coordinator lists `inbox/` but ignores that
  folder, so processed files are skipped on the next run. `scripts/run_extraction.py`
  does this automatically; the headless `stream` daemon archives/deletes per
  `stream.yaml`. `scripts/fetch_transcripts.py` also skips any transcript already
  sitting in `inbox/_processed/`, so re-running a backfill won't re-download or
  re-process what's already been crunched.

### Rolling your own / overriding the agents

**Author a lens (schema).** A schema is the rubric a run reads each transcript
through. Add a block to `.cursor/extraction-schemas.yaml`:

```yaml
my-lens:
  description: "One line: what this lens pulls out."
  grounded: true          # require a verbatim quote per claim (default)
  strict: true            # reject notes with no valid schema tag (default)
  link_relation: component-of
  hub: {type: model, title_template: "{source_title}: My Lens"}
  dimensions:             # each tag becomes a note tag AND a comparison column
    - {tag: results-headline, desc: "revenue/EPS vs expectations", note_type: finding}
    - {tag: margins, desc: "gross/op margin level + direction",
       connect_to: results-headline, relation: qualifies}   # nest under a parent dimension
  relations:              # optional backbone wired between dimensions
    - {from: margins, to: results-headline, relation: qualifies}
  synthesis:              # optional: build a per-company spine that accumulates
    graph: "{label}-mylens"
    node: {type: synthesis, title_template: "{label}: My Lens Profile"}
```

- **`dimensions`** are what to look for; each `tag` is the contract — it's the note
  tag you later query and the column in the comparison matrix. Keep tags unique.
- **`connect_to` / `relations`** shape the notes into a spine instead of a flat
  list (a dimension can hang off a parent dimension rather than the hub).
- a **`synthesis`** block gives the lens a durable per-`{label}` spine (an apex node
  + one node per dimension) that every source's claims attach to — this is what
  makes a company's quarters accumulate into a trajectory and peers into a matrix.

The four shipped lenses are worked examples — copy the closest one. Full field
contract: `.cursor/rules/grounded-extraction.mdc`. You can also generate and
validate a schema with the zettelkasten `schema` tool
(`schema(action="validate")` then `schema(action="save")`).

**Soften grounding — allow paraphrase instead of exact quotes.** Every schema
defaults to `grounded: true`, which makes the **auditor** require a verbatim
supporting quote for each claim. To let claims stand on a faithful paraphrase,
author a variant with `grounded: false` — the scribe then skips the quote-note +
grounding step and writes paraphrased `claim` / `finding` notes:

```yaml
earnings-call-loose:
  description: "Earnings-call lens, paraphrase allowed (no verbatim-quote requirement)."
  grounded: false        # <- claims no longer need a backing verbatim quote
  strict: true           # keep tag discipline (set false to relax that too)
  link_relation: component-of
  hub: {type: model, title_template: "{source_title}: Earnings Call"}
  dimensions:
    - {tag: results-headline, desc: "reported revenue/EPS vs expectations", note_type: finding}
    # ... copy the dimensions you want from earnings-call
```

Then run with `schemas=["earnings-call-loose"]` (headless) or tell the coordinator
to use that lens. Caveat: `quote`-type notes are *always* verified against the
source text by the store — you can't fabricate a quote. `grounded: false` just
means claims don't *require* one.

**Override agent behavior.** `.cursor/agents.yaml` overrides the built-in agents
field-by-field (today it only pins each agent's `model`). To relax the auditor's
strictness in prose too, override its persona:

```yaml
auditor:
  model: claude-sonnet-4-6
  persona: |
    You verify schema-dimension COVERAGE. Grounding is advisory, not required: a
    claim may be backed by a verbatim quote OR a faithful paraphrase that does not
    distort the source. Only FAIL a claim that misrepresents the source or has no
    basis in it.
    ... (end with the mandatory DONE / FILES / RESULT: PASS|FAIL block)
```

You can override `extractor` / `scribe` the same way, or add entirely new agents.
Note the interactive `earnings-ingest.mdc` rule currently says *"don't relax
`grounded: true`"* — for paraphrase on the interactive path, point runs at a
`grounded: false` schema or edit that rule-of-thumb.

> After editing `extraction-schemas.yaml` or `agents.yaml`, **restart the
> coordinator + zettelkasten MCP servers** — both registries are cached at load.

## What's configurable

| File | Purpose |
|------|---------|
| `.cursor/extraction-schemas.yaml` | The extraction **lenses** — `earnings-call` (default), `guidance-tracker`, `qa-sentiment`, `kpi-scorecard`. Add your own. |
| `.cursor/agents.yaml` | **Agent overrides** — model and/or persona for `extractor`/`scribe`/`auditor`/`synthesizer` (e.g. soften grounding). Restart MCP servers after editing. |
| `projects.yaml` | The described **projects** + each one's `join_when` criteria the agent uses to file sources. |
| `.cursor/rules/earnings-ingest.mdc` | The coordinator **workflow** contract ("process the inbox"). |

## Data sources

- **Now:** manual drops into `inbox/` (any `*.pdf` / `*.txt` / `*.md` / `*.html` / `*.xml`),
  or `scripts/fetch_transcripts.py` (ROIC.ai API + SEC EDGAR fallback — see above).
- **Future:** LSEG StreetEvents transcripts via the Snowflake share, once it's
  provisioned to the account. The account's current entitlement (probed 2026-07-08)
  has **no** transcript share — only estimates/factor data — so `scripts/pull_to_inbox.py`
  is a stub with a single `TODO` to fill in when access lands. It writes transcripts
  into `inbox/`, so it feeds the exact same coordinator crunch.

Connection details (account/user/warehouse/role/key) mirror the sibling `Freischutz`
repo and live in `scripts/env_setup.sh` / `.env.example`.
