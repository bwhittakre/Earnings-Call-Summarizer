"""Write the standalone Claims Desk workshop HTML.

Same books and helpers as Roz Claims Trees. Rebuild after any desk
change. Do not invent a second scoring path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.earnings_monitor.dashboard.claims_trees import (  # noqa: E402
    workshop_bundle,
)

REPORT_NAME = "claims_desk.html"


def workshop_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "reports"
        / REPORT_NAME
    )


def build_workshop_html(bundle: dict) -> str:
    data = json.dumps(bundle, ensure_ascii=False, default=str).replace("</", "<\\/")
    return _TEMPLATE.replace("__DESK_JSON__", data)


def write_workshop_html(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    path = workshop_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = workshop_bundle(history_source)
    path.write_text(build_workshop_html(bundle), encoding="utf-8")
    return path


def main() -> int:
    path = write_workshop_html(repo_root=ROOT)
    print(json.dumps({"path": str(path), "bytes": path.stat().st_size}, indent=2))
    return 0


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claims Desk</title>
<style>
  :root {
    --bg: #111318;
    --panel: #1b1e27;
    --ink: #e8e6df;
    --muted: #9a968c;
    --line: #2c3040;
    --accent: #c4b48a;
    --warn: #c9896a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font: 15px/1.45 "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--ink);
  }
  header, main { max-width: 1180px; margin: 0 auto; padding: 20px 24px; }
  header h1 { margin: 0 0 6px; font-size: 28px; font-weight: 600; }
  .sub, .cap, caption, .muted { color: var(--muted); }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 16px;
    flex: 1 1 240px;
  }
  h2 { margin: 28px 0 8px; font-size: 18px; font-weight: 600; }
  h3 { margin: 18px 0 8px; font-size: 15px; color: var(--accent); }
  label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  select, input[type="search"] {
    background: #10131a;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 6px 8px;
    min-width: 140px;
  }
  select[multiple] { min-width: 200px; min-height: 96px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; }
  details.tree {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 12px;
    margin: 8px 0;
  }
  details.tree[open] { border-color: var(--accent); }
  details.tree summary { cursor: pointer; font-weight: 600; }
  .cite { color: var(--muted); font-size: 12px; }
  .silent { color: var(--warn); }
  .metric { font-size: 28px; font-weight: 650; margin: 4px 0; }
  .controls { display: flex; gap: 12px; flex-wrap: wrap; margin: 10px 0 16px; }
  svg.chart { width: 100%; height: 220px; background: #10131a; border-radius: 8px; }
  .empty { color: var(--muted); font-style: italic; }
  .badge-provisional { font-size: 11px; font-weight: 500; background: #2d4a6e; color: #a8c4e8; border-radius: 4px; padding: 1px 6px; vertical-align: middle; }
  .review-banner {
    border: 1px solid var(--warn); border-left-width: 6px; border-radius: 8px;
    padding: 10px 14px; margin: 14px 0; background: #1a1512;
  }
  .review-banner h2 { margin: 0 0 6px; color: var(--warn); }
  .budget { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0 10px; font-size: 13px; }
  .budget span b { color: var(--accent); }
  .tier { display: inline-block; min-width: 18px; text-align: center; padding: 0 5px; border-radius: 4px;
          font-size: 11px; font-weight: 650; background: #24304a; color: #cfe0ff; }
  .tier.t3 { background: #3a3220; color: #f0d9a0; }
  .tier.t4, .tier.t5 { background: #4a2424; color: #ffd0d0; }
  .reason { font-family: ui-monospace, monospace; font-size: 11px; color: var(--warn); }
</style>
</head>
<body>
<header>
  <h1 id="title">Claims Desk</h1>
  <p class="sub" id="subtitle"></p>
</header>
<main>
  <div class="controls" id="book-controls"></div>
  <p class="cap" id="book-caption"></p>
  <p class="cap" id="book-meta"></p>
  <div class="row" id="rates"></div>
  <div id="conversion"></div>
  <div id="known-delivered"></div>
  <div id="transparency"></div>
  <div id="quant"></div>
  <div id="management-regimes"></div>
  <div id="seed-candidates"></div>
  <div id="needs-review"></div>
  <div id="terminal-candidates"></div>
  <div id="credibility"></div>
  <div id="clocks"></div>
  <div id="horizon"></div>
  <div id="quotes"></div>
  <div id="uncovered"></div>
  <div id="trees"></div>
</main>
<script type="application/json" id="desk-data">__DESK_JSON__</script>
<script>
const DESK = JSON.parse(document.getElementById("desk-data").textContent);
const ALL = "all";
const UNBUCKETED = "unbucketed";

function labelOf(ticker) {
  return DESK.labels[String(ticker || "").toUpperCase()] || String(ticker || "");
}
function treeBucket(tree) {
  const raw = String(tree.bucket || "").trim();
  return raw || null;
}
function bucketLabel(key) {
  if (key === null || key === undefined || key === "") return "unbucketed";
  return DESK.bucket_labels[key] || key;
}
function filterTreesToBucket(trees, choice) {
  const key = String(choice || ALL);
  if (key === ALL) return trees.slice();
  if (key === UNBUCKETED) return trees.filter(t => treeBucket(t) === null);
  return trees.filter(t => treeBucket(t) === key);
}
function groupTreesByBucket(trees) {
  const groups = {};
  for (const key of DESK.buckets) groups[key] = [];
  const unbucketed = [];
  for (const tree of trees) {
    const key = treeBucket(tree);
    if (!key || !groups[key]) unbucketed.push(tree);
    else groups[key].push(tree);
  }
  const ordered = [];
  for (const key of DESK.buckets) if (groups[key].length) ordered.push([key, groups[key]]);
  if (unbucketed.length) ordered.push([null, unbucketed]);
  return ordered;
}
function formatRate(rate) {
  if (rate === null || rate === undefined || rate === "") return "—";
  const number = Number(rate);
  if (!Number.isFinite(number)) return "—";
  return Math.round(number * 100) + "%";
}
function formatNRate(rate, n, yes) {
  const count = Number(n || 0);
  if (!count) return "—";
  return formatRate(rate) + " (" + yes + "/" + count + ")";
}
function scoredRateCaption(n, kind) {
  if (Number(n || 0) <= 0) return "No scored " + kind + " yet. Em dash is not a 0% keep rate.";
  return "Scored " + kind + " only. Unresolved is an em dash.";
}
function conversionCaption(c) {
  const nGoals = Number((c || {}).n_goals || 0);
  const nBecame = Number((c || {}).n_became_promise || 0);
  if (nGoals <= 0) return "No goals yet. Em dash is not a 0% conversion rate.";
  return nBecame + " of " + nGoals + " goals became a promise.";
}
const EXPIRE_CAPTION = "Expiration means it was never followed up in a way we can settle, so claiming completeness is unfeasible. It is not a miss and not a withdrawal. An untouched expired claim stays unknown.";
function knownDeliveredCaption(counts) {
  const aged = Number((counts || {}).n_aged || 0);
  if (aged <= 0) return "No aged trees yet. Em dash is not a 0% known-delivered rate.";
  return "This is what we know has been delivered. " +
    Number((counts || {}).n_confirmed || 0) + " of " + aged +
    " aged trees are confirmed delivered. " + Number((counts || {}).n_unknown || 0) +
    " unknown. Aged trees we cannot settle sit in the denominator. Expiry is not delivered and not dropped.";
}
function neglectCaption(counts) {
  const live = Number((counts || {}).n_live || 0);
  const neglected = Number((counts || {}).n_neglected || 0);
  const slipped = Number((counts || {}).n_slipped || 0);
  const treesDue = Number((counts || {}).n_trees_due || 0);
  const treesSlipped = Number((counts || {}).n_trees_slipped || 0);
  if (treesDue > 0) {
    return treesSlipped + " of " + treesDue + " dated claims went unanswered after the clock (" +
      slipped + " overdue quarters). Someday wants with no clock are not implicit neglect. Not desk_trust.";
  }
  if (live <= 0) return "No live follow-up quarters yet. Em dash is not a 0% neglect rate.";
  return neglected + " of " + live + " typed follow-ups left a prior claim unaddressed (" +
    slipped + " slipped). Someday wants with no clock are not implicit neglect. Not desk_trust.";
}
function treeKindLabel(tree) {
  return tree.kind_label || tree.kind || "";
}
function nodeEdgeLabel(row) {
  if (row.edge_label) return row.edge_label;
  if (row.edge === "harden-to-promise") return "became a promise";
  return row.edge || "";
}
function fiscalKey(fiscal) {
  const m = String(fiscal || "").trim().toUpperCase().match(/^FY(\d{4})-Q([1-4])$/);
  return m ? [Number(m[1]), Number(m[2])] : [-1, -1];
}
function cmpFiscal(a, b) {
  const A = fiscalKey(a), B = fiscalKey(b);
  return A[0] !== B[0] ? A[0] - B[0] : A[1] - B[1];
}
function nextFiscal(period) {
  const [y, q] = fiscalKey(period);
  if (y < 0) return null;
  return q === 4 ? ("FY" + (y + 1) + "-Q1") : ("FY" + y + "-Q" + (q + 1));
}
function fiscalSpan(start, end) {
  if (fiscalKey(start)[0] < 0 || fiscalKey(end)[0] < 0) return [];
  if (cmpFiscal(start, end) > 0) return [];
  const found = [start];
  let here = start;
  while (here !== end) {
    const nxt = nextFiscal(here);
    if (!nxt) break;
    found.push(nxt);
    here = nxt;
    if (found.length > 80) break;
  }
  return found;
}
function clockIsDue(clock, fiscal) {
  if (!clock) return false;
  const c = fiscalKey(clock), h = fiscalKey(fiscal);
  if (c[0] < 0 || h[0] < 0) return false;
  return cmpFiscal(fiscal, clock) >= 0;
}
function clockBoard(trees, latest) {
  const due = [], slipped = [], openNo = [];
  for (const tree of trees) {
    if (!tree.open) continue;
    const clock = String(tree.clock || "").trim() || null;
    const row = {tree_id: tree.tree_id, ticker: tree.ticker, title: tree.title, kind: tree.kind, clock, state: tree.state, slipped: !!tree.slipped};
    if (tree.slipped) { slipped.push(row); continue; }
    if (!clock) { openNo.push(row); continue; }
    if (latest && clockIsDue(clock, latest)) due.push(row);
  }
  return {due, slipped, open_no_clock: openNo};
}
function horizonLimit(choice) {
  if (choice === "all" || choice == null) return null;
  return ({"1Q": 1, "2Q": 2, "4Q": 4})[choice] ?? 1;
}
function filterHorizonEvents(events, {horizon, ticker, kinds, start, end}) {
  const limit = horizonLimit(horizon);
  const want = ticker && ticker !== ALL ? String(ticker).toUpperCase() : null;
  const wantKinds = kinds || null;
  return events.filter(ev => {
    if (limit != null && (ev.clock_length == null || ev.clock_length > limit)) return false;
    if (want && String(ev.ticker || "").toUpperCase() !== want) return false;
    if (wantKinds && !wantKinds.includes(ev.kind)) return false;
    const here = fiscalKey(ev.event_fiscal);
    if (fiscalKey(start)[0] >= 0 && cmpFiscal(ev.event_fiscal, start) < 0) return false;
    if (fiscalKey(end)[0] >= 0 && cmpFiscal(ev.event_fiscal, end) > 0) return false;
    return here[0] >= 0;
  });
}
function rateFromEvents(events) {
  const yes = events.filter(e => e.result === "success").length;
  const no = events.filter(e => e.result === "fail").length;
  const n = yes + no;
  return {rate: n ? yes / n : null, n, yes, no};
}
function horizonSeries(events, periods, kinds) {
  return periods.filter(p => fiscalKey(p)[0] >= 0).map(period => {
    const quarter = events.filter(e => e.event_fiscal === period && (!kinds || kinds.includes(e.kind)));
    const running = events.filter(e => cmpFiscal(e.event_fiscal, period) <= 0 && (!kinds || kinds.includes(e.kind)));
    const q = rateFromEvents(quarter);
    const c = rateFromEvents(running);
    return {
      fiscal_period: period,
      horizon_quarter_rate: q.rate, horizon_quarter_n: q.n, horizon_quarter_yes: q.yes,
      horizon_cum_rate: c.rate, horizon_cum_n: c.n, horizon_cum_yes: c.yes,
    };
  });
}
function treeNodeRows(tree) {
  const seed = tree.seed || {};
  const rows = [{
    fiscal_period: seed.fiscal_period, edge: "seed", excerpt: seed.excerpt,
    citation: seed.citation, clock: seed.clock || tree.clock, slipped: false, edge_label: "seed",
  }];
  for (const node of tree.nodes || []) {
    rows.push({
      fiscal_period: node.fiscal_period, edge: node.edge, edge_label: node.edge_label,
      excerpt: node.excerpt, citation: node.citation, clock: node.clock, slipped: !!node.slipped,
    });
  }
  return rows;
}
function el(html) { const d = document.createElement("div"); d.innerHTML = html; return d; }
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}
function table(headers, rows) {
  if (!rows.length) return '<p class="empty">None.</p>';
  return "<table><thead><tr>" + headers.map(h => "<th>" + esc(h) + "</th>").join("") +
    "</tr></thead><tbody>" + rows.map(r => "<tr>" + r.map(c => "<td>" + c + "</td>").join("") + "</tr>").join("") +
    "</tbody></table>";
}
function optionLabel(opt) {
  if (opt === ALL) return "All";
  if (opt === UNBUCKETED) return "Unbucketed";
  if ((DESK.book_labels || {})[opt]) return DESK.book_labels[opt];
  if (DESK.bucket_labels[opt]) return DESK.bucket_labels[opt];
  if (DESK.labels[opt]) return DESK.labels[opt];
  return opt;
}
const ALL_BOOKS = "all_books";
function bookLabel(id) {
  return (DESK.book_labels || {})[id] || ({
    all_books: "All books",
    nvda_gold_v2: "NVIDIA gold",
    desk_ops_v2: "Tech ops",
    desk_hc_v2: "Healthcare / Independent",
  }[id] || id);
}
function selectedBookId() {
  return document.getElementById("book")?.value || DESK.default_book || ALL_BOOKS;
}
function parseCustomList() {
  const raw = document.getElementById("custom-list")?.value || "";
  return raw.split(/[\s,;]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
}
function bookNames(bookId) {
  const names = DESK.book_order.filter(n => n !== ALL_BOOKS && DESK.books[n]);
  if (!bookId || bookId === ALL_BOOKS) return names;
  return names.includes(bookId) ? [bookId] : [];
}
function unionTrees(bookId) {
  const trees = [];
  for (const name of bookNames(bookId)) {
    for (const tree of (DESK.books[name] || {}).trees || []) trees.push(tree);
  }
  return trees;
}
function unionCues(bookId) {
  const missed = [];
  let latest = null;
  let goldRecall = null;
  for (const name of bookNames(bookId)) {
    const queue = (DESK.books[name] || {}).queue || {};
    latest = queue.latest_quarter || (DESK.books[name] || {}).latest || latest;
    if (name === "nvda_gold_v2" && (queue.gold || {}).recall != null) goldRecall = queue.gold.recall;
    for (const row of queue.missed || []) missed.push(row);
  }
  return {missed, latest, goldRecall};
}
function unionHorizonEvents(bookId, treeIds) {
  const ids = treeIds ? new Set(treeIds) : null;
  const events = [];
  for (const name of bookNames(bookId)) {
    for (const ev of (DESK.books[name] || {}).horizon_events || []) {
      if (!ids || ids.has(ev.tree_id)) events.push(ev);
    }
  }
  return events;
}
function unionQuotes(bookId, treeIds) {
  const ids = treeIds ? new Set(treeIds) : null;
  const rows = [];
  for (const name of bookNames(bookId)) {
    for (const row of (DESK.books[name] || {}).quotes || []) {
      if (!ids || ids.has(row.tree_id)) rows.push(row);
    }
  }
  return rows;
}
function unionSpan(bookId, trees) {
  if (trees && trees.length) {
    const periods = trees.map(t => (t.seed || {}).fiscal_period).filter(Boolean);
    if (periods.length) {
      const sorted = periods.slice().sort(cmpFiscal);
      return [sorted[0], sorted[sorted.length - 1]];
    }
  }
  let start = null, end = null;
  for (const name of bookNames(bookId)) {
    const span = (DESK.books[name] || {}).span || [];
    if (span[0] && (!start || cmpFiscal(span[0], start) < 0)) start = span[0];
    if (span[1] && (!end || cmpFiscal(span[1], end) > 0)) end = span[1];
  }
  return [start, end];
}
function deskTickers(trees, cues) {
  const found = new Set();
  for (const row of [...trees, ...(cues || [])]) {
    const t = String(row.ticker || "").toUpperCase();
    if (t) found.add(t);
  }
  return [...found].sort();
}
function filterByTickers(rows, tickers) {
  if (!tickers) return rows.slice();
  const allow = new Set(tickers);
  return rows.filter(r => allow.has(String(r.ticker || "").toUpperCase()));
}
function selectedCompanies(options) {
  const sel = document.getElementById("companies");
  if (!sel) return options.slice();
  const picked = [...sel.selectedOptions].map(o => o.value);
  return picked.length ? picked : options.slice();
}
function visibleFilter() {
  const bookId = selectedBookId();
  const custom = parseCustomList();
  const treesAll = unionTrees(bookId);
  const cuesAll = unionCues(bookId);
  let options = deskTickers(treesAll, cuesAll.missed);
  if (custom.length) {
    const allow = new Set(custom);
    options = options.filter(t => allow.has(t));
  }
  const visible = selectedCompanies(options);
  return {
    bookId,
    options,
    visible,
    trees: filterByTickers(treesAll, visible),
    cues: filterByTickers(cuesAll.missed, visible),
    latest: cuesAll.latest,
    goldRecall: cuesAll.goldRecall,
  };
}
function deliverRateCounts(trees) {
  const delivered = trees.filter(t => t.delivery === "delivered").length;
  const missed = trees.filter(t => t.delivery === "missed").length;
  const n = delivered + missed;
  return {delivered, missed, n_scoreable: n, deliver_rate: n ? delivered / n : null};
}
function hitRateCounts(trees) {
  const hit = trees.filter(t => t.goal_outcome === "hit").length;
  const missed = trees.filter(t => t.goal_outcome === "missed").length;
  const n = hit + missed;
  return {hit, missed, n_scoreable: n, hit_rate: n ? hit / n : null};
}
function conversionFromTrees(trees) {
  const goals = trees.filter(t => t.kind === "goal");
  const became = goals.filter(t => t.goal_outcome === "became-promise");
  const nGoals = goals.length;
  return {n_goals: nGoals, n_became_promise: became.length, harden_rate: nGoals ? became.length / nGoals : null};
}
function lastNodeEdge(tree) {
  const nodes = tree.nodes || [];
  if (!nodes.length) return null;
  return String(nodes[nodes.length - 1].edge || "") || null;
}
function treeAgedBucket(tree, asOf) {
  const delivery = String(tree.delivery || "");
  const goal = String(tree.goal_outcome || "");
  const state = String(tree.state || "");
  const edge = lastNodeEdge(tree);
  if (delivery === "delivered" || goal === "hit") return "confirmed";
  if (delivery === "missed" || goal === "missed") return "failed";
  if (goal === "dropped" || edge === "abandoned" || state === "abandoned") return "withdrawn";
  if (delivery === "expired" || goal === "expired" || state === "expired" || edge === "expired") return "unknown";
  if (!asOf || fiscalKey(asOf)[0] < 0) return null;
  if (clockIsDue(tree.clock, asOf) || clockIsDue(tree.expire, asOf)) return "unknown";
  return null;
}
function knownDeliveredCounts(trees, asOf) {
  let confirmed = 0, failed = 0, withdrawn = 0, unknown = 0;
  for (const tree of trees) {
    const b = treeAgedBucket(tree, asOf);
    if (b === "confirmed") confirmed++;
    else if (b === "failed") failed++;
    else if (b === "withdrawn") withdrawn++;
    else if (b === "unknown") unknown++;
  }
  const aged = confirmed + failed + withdrawn + unknown;
  return {
    n_confirmed: confirmed, n_failed: failed, n_withdrawn: withdrawn, n_unknown: unknown,
    n_aged: aged,
    known_delivered_rate: aged ? confirmed / aged : null,
    settled_share: aged ? (confirmed + failed + withdrawn) / aged : null,
  };
}
function ratesFromVisibleTrees(trees, latest) {
  const promises = trees.filter(t => t.kind === "promise");
  const goals = trees.filter(t => t.kind === "goal");
  return {
    deliver: deliverRateCounts(promises),
    hit: hitRateCounts(goals),
    conversion: conversionFromTrees(trees),
    known: knownDeliveredCounts(trees, latest),
  };
}
function rebuildCompanySelect() {
  const bookId = selectedBookId();
  const custom = parseCustomList();
  const treesAll = unionTrees(bookId);
  const cuesAll = unionCues(bookId);
  let options = deskTickers(treesAll, cuesAll.missed);
  if (custom.length) {
    const allow = new Set(custom);
    options = options.filter(t => allow.has(t));
  }
  const sel = document.getElementById("companies");
  if (!sel) return;
  const prev = [...sel.selectedOptions].map(o => o.value);
  const wasAll = !prev.length || prev.length === sel.options.length;
  const keep = wasAll ? options : options.filter(t => prev.includes(t));
  const chosen = keep.length ? keep : options;
  sel.innerHTML = options.map(opt =>
    '<option value="' + esc(opt) + '"' + (chosen.includes(opt) ? " selected" : "") + ">" +
    esc(labelOf(opt)) + "</option>"
  ).join("");
}
function select(id, options, selected, labels) {
  return '<label for="' + id + '">' + esc(labels || id) + '</label><select id="' + id + '">' +
    options.map(opt => '<option value="' + esc(opt) + '"' + (opt === selected ? " selected" : "") + '>' +
      esc(optionLabel(opt)) +
      "</option>").join("") + "</select>";
}
function firstBook(bookId) {
  const names = bookNames(bookId);
  return DESK.books[names[0]] || {};
}
function drawChart(rows) {
  const w = 1000, h = 220, pad = 28;
  const xs = rows.map(r => r.fiscal_period);
  if (!xs.length) return "";
  const points = [];
  rows.forEach((r, i) => {
    if (r.horizon_quarter_rate != null) points.push({i, y: r.horizon_quarter_rate, s: "quarterly"});
    if (r.horizon_cum_rate != null) points.push({i, y: r.horizon_cum_rate, s: "cumulative"});
  });
  if (!points.length) return "";
  const x = i => pad + (xs.length === 1 ? (w - 2 * pad) / 2 : i * (w - 2 * pad) / (xs.length - 1));
  const y = v => h - pad - v * (h - 2 * pad);
  function path(series) {
    const pts = points.filter(p => p.s === series);
    if (!pts.length) return "";
    return '<polyline fill="none" stroke="' + (series === "quarterly" ? "#c4b48a" : "#8aa4c4") +
      '" stroke-width="2" points="' + pts.map(p => x(p.i) + "," + y(p.y)).join(" ") + '" />';
  }
  return '<svg class="chart" viewBox="0 0 ' + w + ' ' + h + '">' + path("quarterly") + path("cumulative") + "</svg>";
}
function render() {
  document.getElementById("title").textContent = DESK.title;
  document.getElementById("subtitle").textContent = DESK.subtitle;
  const filter = visibleFilter();
  const trees = filter.trees;
  const rates = ratesFromVisibleTrees(trees, filter.latest);
  const deliver = rates.deliver;
  const hits = rates.hit;
  const conversion = rates.conversion;
  const known = rates.known;
  document.getElementById("book-caption").textContent =
    bookLabel(filter.bookId) + " · " +
    (parseCustomList().length ? "custom list " + parseCustomList().join(", ") + " · " : "") +
    filter.visible.length + (filter.visible.length === 1 ? " company" : " companies") +
    ". Rates are this filter, not the whole book.";
  document.getElementById("book-meta").textContent =
    "Company / custom-list filter is first. Books are an optional source.";
  const nProvisional = bookNames(filter.bookId).reduce((n, name) => n + Number((DESK.books[name] || {}).n_provisional || 0), 0);
  const provisionalBadge = nProvisional > 0
    ? ' <span class="badge-provisional">(+' + nProvisional + ' provisional)</span>'
    : '';
  document.getElementById("rates").innerHTML =
    '<div class="card"><h2>Deliver rate (this filter)' + provisionalBadge + '</h2><p class="cap">' + esc(scoredRateCaption(deliver.n_scoreable, "promises")) +
    '</p><div class="metric">' + esc(formatRate(deliver.deliver_rate)) + '</div><p class="cap">' +
    esc((deliver.delivered || 0) + " delivered / " + (deliver.n_scoreable || 0) + " scored") + "</p></div>" +
    '<div class="card"><h2>Hit rate (this filter)</h2><p class="cap">' + esc(scoredRateCaption(hits.n_scoreable, "goals")) +
    '</p><div class="metric">' + esc(formatRate(hits.hit_rate)) + '</div><p class="cap">' +
    esc((hits.hit || 0) + " hit / " + (hits.n_scoreable || 0) + " scored") + "</p></div>";
  document.getElementById("conversion").innerHTML =
    "<h2>Became a promise</h2><p class='cap'>" + esc(conversionCaption(conversion)) +
    "</p><div class='metric'>" + esc(formatRate(conversion.harden_rate)) +
    "</div><p class='cap'>" + esc((conversion.n_became_promise || 0) + " became a promise / " +
    (conversion.n_goals || 0) + " goals. Not desk_trust. Same tree stays open until the promise closes.") + "</p>";

  document.getElementById("known-delivered").innerHTML =
    "<h2>Known-delivered</h2>" +
    "<p class='cap'>This is what we know has been delivered. Aged trees we cannot settle sit in the denominator.</p>" +
    "<p class='cap'>" + esc(knownDeliveredCaption(known)) +
    "</p><div class='metric'>" + esc(formatRate(known.known_delivered_rate)) +
    "</div><p class='cap'>" + esc((known.n_confirmed || 0) + " confirmed / " +
    (known.n_aged || 0) + " aged · settled share " + formatRate(known.settled_share) +
    " · " + (known.n_unknown || 0) + " unknown. Not desk_trust.") + "</p>";

  renderTransparency(filter);
  renderQuant(filter);
  renderManagementRegimes(filter);

  const cred = document.getElementById("credibility");
  const showCred = DESK.metrics && (
    filter.bookId === "nvda_gold_v2" ||
    (filter.bookId === ALL_BOOKS && (!filter.visible.length || filter.visible.includes("NVDA")))
  );
  if (showCred) {
    const allow = new Set(filter.visible);
    const rows = (DESK.metrics.rows || []).filter(r =>
      (r.desk_trust_n || r.desk_ambition_n) &&
      (!allow.size || allow.has(String(r.ticker || "").toUpperCase()))
    );
    cred.innerHTML = "<h2>Trailing credibility</h2><p class='cap'>Point-in-time expanding rates on management_confidence. A quarter only sees terminals already cited. Null is an em dash.</p>" +
      table(["company", "fiscal_period", "trust", "trust_n", "ambition", "ambition_n"],
        rows.map(r => [esc(labelOf(r.ticker)), esc(r.fiscal_period), esc(formatRate(r.desk_trust)),
          esc(r.desk_trust_n), esc(formatRate(r.desk_ambition)), esc(r.desk_ambition_n)]));
  } else cred.innerHTML = "";

  const latest = filter.latest;
  const board = clockBoard(trees, latest);
  let clockHtml = "<h2>Due and slipped</h2><p class='cap'>As of " + esc(latest || "—") +
    ". Open clocks on typed trees. Slipped here is a typed silent plus a due clock, not missed. " +
    "The neglect ledger above scores later calls that did not take up a prior claim. " +
    "Open trees with no clock are someday wants, not due. Grouped by company — expand to see details.</p>";
  const clockRows = [...board.slipped, ...board.due];
  if (clockRows.length) {
    // Group by ticker
    const clockByTicker = {};
    for (const r of clockRows) {
      const t = r.ticker || "";
      if (!clockByTicker[t]) clockByTicker[t] = [];
      clockByTicker[t].push(r);
    }
    for (const [ticker, rows] of Object.entries(clockByTicker).sort((a, b) => a[0].localeCompare(b[0]))) {
      clockHtml += "<details style='margin-bottom:4px'><summary style='cursor:pointer;font-weight:600;padding:3px 0'>" +
        esc(labelOf(ticker)) + " — " + esc(String(rows.length)) + " clock" + (rows.length === 1 ? "" : "s") + "</summary>";
      clockHtml += table(["bucket", "claim", "kind", "clock"],
        rows.map(r => [esc(r.slipped ? "slipped" : "due"), esc(r.title), esc(r.kind), esc(r.clock || "—")]));
      clockHtml += "</details>";
    }
  }
  if (board.open_no_clock.length) {
    clockHtml += "<p class='cap'>" + board.open_no_clock.length + " open claims with no clock (soft someday wants) — grouped by company.</p>";
    const openByTicker = {};
    for (const r of board.open_no_clock) {
      const t = r.ticker || "";
      if (!openByTicker[t]) openByTicker[t] = [];
      openByTicker[t].push(r);
    }
    for (const [ticker, rows] of Object.entries(openByTicker).sort((a, b) => a[0].localeCompare(b[0]))) {
      clockHtml += "<details style='margin-bottom:4px'><summary style='cursor:pointer;font-weight:600;padding:3px 0'>" +
        esc(labelOf(ticker)) + " — " + esc(String(rows.length)) + " open</summary>";
      clockHtml += table(["claim", "kind", "state"],
        rows.map(r => [esc(r.title), esc(r.kind), esc(r.state)]));
      clockHtml += "</details>";
    }
  }
  document.getElementById("clocks").innerHTML = clockHtml;

  renderHorizon(filter, trees);
  renderQuotes(filter);
  renderUncovered(filter);
  renderSeedCandidates(filter);
  renderNeedsReview(filter);
  renderTerminalCandidates(filter);
  renderTrees(trees);
}
function renderTransparency(filter) {
  const host = document.getElementById("transparency");
  const payload = DESK.transparency;
  if (!payload) {
    host.innerHTML = "<h2>Management transparency</h2><p class='cap'>Rebuild the sidecar with python scripts/_desk_transparency_v2.py. This is not desk_trust.</p>";
    return;
  }
  const names = bookNames(filter.bookId);
  let companies = [];
  let ledger = [];
  let counts = {};
  for (const name of names) {
    const block = ((payload.books || {})[name] || {});
    companies = companies.concat(block.by_company || []);
    ledger = ledger.concat(block.ledger || []);
    const bookCounts = block.book || {};
    for (const [k, v] of Object.entries(bookCounts)) {
      if (typeof v === "number") counts[k] = (counts[k] || 0) + v;
    }
  }
  const allow = new Set(filter.visible);
  if (allow.size) {
    companies = companies.filter(r => allow.has(String(r.ticker || "").toUpperCase()));
    ledger = ledger.filter(r => allow.has(String(r.ticker || "").toUpperCase()));
  }
  if (allow.size && names.length !== 1) {
    counts = {
      n_trees_slipped: companies.reduce((n, r) => n + Number(r.n_trees_slipped || 0), 0),
      n_trees_due: companies.reduce((n, r) => n + Number(r.n_trees_due || 0), 0),
      n_slipped: companies.reduce((n, r) => n + Number(r.n_slipped || 0), 0),
      n_ignored: companies.reduce((n, r) => n + Number(r.n_ignored || 0), 0),
      n_withdrawn: companies.reduce((n, r) => n + Number(r.n_withdrawn || 0), 0),
    };
  }
  const due = Number(counts.n_trees_due || 0);
  counts.tree_slip_rate = due ? Number(counts.n_trees_slipped || 0) / due : null;
  let html = "<h2>Management transparency</h2><p class='cap'>" + esc(payload.caption || "") + "</p>" +
    "<p class='cap'>" + esc(neglectCaption(counts)) + "</p>" +
    '<div class="row"><div class="card"><h2>Due-clock slip rate</h2><div class="metric">' +
    esc(formatRate(counts.tree_slip_rate)) + "</div><p class='cap'>" +
    esc((counts.n_trees_slipped || 0) + " of " + (counts.n_trees_due || 0) +
    " dated trees went unanswered · " + (counts.n_slipped || 0) +
    " overdue quarters · " + (counts.n_ignored || 0) + " typed ignores · " +
    (counts.n_withdrawn || 0) + " withdrawn") + "</p></div></div>";
  if (companies.length) {
    html += table(["company", "tree_slip", "slipped_trees", "due_trees", "overdue_q", "typed_ignore", "addressed", "withdrawn"],
      companies.map(r => [esc(labelOf(r.ticker)), esc(formatRate(r.tree_slip_rate)),
        esc(r.n_trees_slipped), esc(r.n_trees_due), esc(r.n_slipped),
        esc(r.n_ignored), esc(r.n_addressed), esc(r.n_withdrawn)]));
  }
  html += "<p class='cap'>Ledger: dated claims they let slip, typed silences, or withdrawals. Implicit slips collapse to first/last quarter. Addressed stays in the rate.</p>";
  html += table(["status", "company", "first", "last", "quarters", "claim", "kind", "clock", "source"],
    ledger.map(r => [esc(r.status), esc(labelOf(r.ticker)),
      esc(r.first_fiscal || r.fiscal_period), esc(r.last_fiscal || r.fiscal_period),
      esc(r.n_quarters || 1), esc(r.title), esc(r.kind), esc(r.clock || "—"),
      esc(r.implicit ? "view" : "typed")]));
  host.innerHTML = html;
}
function renderQuant(filter) {
  const host = document.getElementById("quant");
  const payload = DESK.quant;
  let html = "<h2>Quant cross-check</h2><p class='cap'>" + esc(EXPIRE_CAPTION) + "</p>" +
    "<p class='cap'>Clocked trees check at the clock. Unclocked trees wait four silent quarters, then stop at expire or seed+8Q. A missing actual is expired, not a miss. Not desk_trust.</p>";
  if (!payload) {
    html += "<p class='cap'>Rebuild the sidecar with python scripts/_desk_quant_v2.py. This is not desk_trust.</p>";
    host.innerHTML = html;
    return;
  }
  const names = bookNames(filter.bookId);
  let rows = [];
  let asOf = filter.latest;
  for (const name of names) {
    const block = ((payload.books || {})[name] || {});
    rows = rows.concat(block.rows || []);
    asOf = block.as_of || asOf;
  }
  if (filter.visible.length) {
    const allow = new Set(filter.visible);
    rows = rows.filter(r => allow.has(String(r.ticker || "").toUpperCase()));
  }
  html += "<p class='cap'>" + esc(payload.caption || "") + "</p>" +
    "<p class='cap'>As of " + esc(asOf || "—") +
    ". Binding, clock vs unclocked cap, last actual, verdict, next check, stop fiscal.</p>";
  if (!rows.length) {
    html += "<p class='cap'>No expire or quant bindings in this filter.</p>";
    host.innerHTML = html;
    return;
  }
  html += table(
    ["status", "company", "claim", "clock", "first_check", "stop", "next", "actual"],
    rows.map(r => [
      esc(r.verdict),
      esc(labelOf(r.ticker)),
      esc(r.title),
      esc(r.clock || "—"),
      esc(r.first_check || "—"),
      esc(r.stop_fiscal || "—"),
      esc(r.next_check || "—"),
      esc((r.actual && r.actual.actual_value != null) ? r.actual.actual_value : "—"),
    ])
  );
  host.innerHTML = html;
}
function renderHorizon(filter, trees) {
  const host = document.getElementById("horizon");
  const spanPair = unionSpan(filter.bookId, trees);
  const span = fiscalSpan(spanPair[0], spanPair[1]);
  if (!span.length) {
    host.innerHTML = "<h2>Horizon keep rate</h2><p class='cap'>No dated clocks to score.</p>";
    return;
  }
  const horizon = document.getElementById("horizon-choice")?.value || "1Q";
  const kindChoice = document.getElementById("horizon-kind")?.value || "promises";
  const company = document.getElementById("horizon-company")?.value || ALL;
  const bucket = document.getElementById("horizon-bucket")?.value || ALL;
  const start = document.getElementById("horizon-from")?.value || span[0];
  const end = document.getElementById("horizon-through")?.value || span[span.length - 1];
  const tickers = [...new Set(trees.map(t => String(t.ticker || "").toUpperCase()).filter(Boolean))].sort();
  host.innerHTML = "<h2>Horizon keep rate</h2><p class='cap'>New series. A due clock with only a silent / slipped edge is a miss here. Tree delivery stays unresolved. This is not the locked gold 6/7 desk_trust.</p>" +
    '<div class="controls">' +
    select("horizon-choice", DESK.horizon_choices, horizon, "Horizon") +
    select("horizon-kind", ["promises", "goals", "both"], kindChoice, "Kind") +
    select("horizon-company", [ALL, ...tickers], company, "Company") +
    select("horizon-bucket", DESK.bucket_filter_choices, bucket, "Bucket") +
    select("horizon-from", span, start, "From") +
    select("horizon-through", span, end, "Through") +
    "</div><div id='horizon-body'></div>";
  const kinds = kindChoice === "promises" ? ["promise"] : kindChoice === "goals" ? ["goal"] : null;
  const filteredTrees = filterTreesToBucket(trees, bucket);
  const ids = new Set(filteredTrees.map(t => t.tree_id));
  const events = filterHorizonEvents(unionHorizonEvents(filter.bookId, ids), {
    horizon, ticker: company, kinds, start, end
  });
  const series = horizonSeries(events, fiscalSpan(start, end), kinds);
  const latest = series[series.length - 1] || {};
  document.getElementById("horizon-body").innerHTML =
    '<div class="row"><div class="card"><h2>This-window quarterly (last period)</h2><div class="metric">' +
    esc(formatNRate(latest.horizon_quarter_rate, latest.horizon_quarter_n, latest.horizon_quarter_yes)) +
    '</div></div><div class="card"><h2>Cumulative in window</h2><div class="metric">' +
    esc(formatNRate(latest.horizon_cum_rate, latest.horizon_cum_n, latest.horizon_cum_yes)) +
    "</div></div></div>" + drawChart(series) +
    table(["fiscal_period", "quarterly", "cumulative"], series.map(r => [
      esc(r.fiscal_period),
      esc(formatNRate(r.horizon_quarter_rate, r.horizon_quarter_n, r.horizon_quarter_yes)),
      esc(formatNRate(r.horizon_cum_rate, r.horizon_cum_n, r.horizon_cum_yes)),
    ]));
  ["horizon-choice", "horizon-kind", "horizon-company", "horizon-bucket", "horizon-from", "horizon-through"]
    .forEach(id => document.getElementById(id).onchange = () => renderHorizon(filter, trees));
}
function renderQuotes(filter) {
  const host = document.getElementById("quotes");
  const treeIds = (filter.trees || []).map(t => t.tree_id);
  const rows = unionQuotes(filter.bookId, treeIds);
  if (!rows.length) { host.innerHTML = ""; return; }
  const outcomes = [...new Set(rows.map(r => r.outcome || ""))].sort();
  const tickers = [...new Set(rows.map(r => String(r.ticker || "").toUpperCase()).filter(Boolean))].sort();
  const pickedO = [...document.querySelectorAll("#quote-outcomes input:checked")].map(i => i.value);
  const pickedK = [...document.querySelectorAll("#quote-kinds input:checked")].map(i => i.value);
  const pickedR = [...document.querySelectorAll("#quote-roles input:checked")].map(i => i.value);
  const pickedT = [...document.querySelectorAll("#quote-tickers input:checked")].map(i => i.value);
  const useO = pickedO.length ? pickedO : outcomes;
  const useK = pickedK.length ? pickedK : ["promise", "goal"];
  const useR = pickedR.length ? pickedR : ["seed", "change", "close"];
  const useT = tickers.length > 1 ? (pickedT.length ? pickedT : tickers) : tickers;
  const filtered = rows.filter(r =>
    useO.includes(r.outcome || "") && useK.includes(r.kind) && useR.includes(r.role) &&
    (tickers.length <= 1 || useT.includes(String(r.ticker || "").toUpperCase()))
  );
  function boxes(id, values, selected) {
    return '<div id="' + id + '">' + values.map(v =>
      '<label><input type="checkbox" value="' + esc(v) + '"' + (selected.includes(v) ? " checked" : "") + "> " +
      esc(v) + "</label>").join(" ") + "</div>";
  }
  host.innerHTML = "<h2>Quotes</h2><p class='cap'>Seed, later restatements, and the close. Silent quarters are omitted. Slipped is a filter tag, not a typed miss.</p>" +
    "<p class='cap'>Outcome</p>" + boxes("quote-outcomes", outcomes, useO) +
    "<p class='cap'>Quote kind</p>" + boxes("quote-kinds", ["promise", "goal"], useK) +
    "<p class='cap'>Role</p>" + boxes("quote-roles", ["seed", "change", "close"], useR) +
    (tickers.length > 1 ? "<p class='cap'>Quote company</p>" + boxes("quote-tickers", tickers, useT) : "") +
    table(["company", "fiscal_period", "role", "edge", "kind", "outcome", "claim", "clock", "excerpt"],
      filtered.map(r => [esc(labelOf(r.ticker)), esc(r.fiscal_period), esc(r.role), esc(r.edge),
        esc(r.kind), esc(r.outcome), esc(r.title), esc(r.clock || "—"), esc(r.excerpt)]));
  host.querySelectorAll("input").forEach(i => i.onchange = () => renderQuotes(filter));
}
function renderUncovered(filter) {
  const missed = filter.cues || [];
  const host = document.getElementById("uncovered");
  if (!missed.length) { host.innerHTML = ""; return; }
  host.innerHTML = "<h2>Uncovered cues</h2><p class='cap'>Seedable promise/goal cues in novelty_view that are not yet on a typed tree. Do not auto-seed. Gold 20Q recall stays locked.</p>" +
    "<p class='cap'>Missed " + esc(String(missed.length)) + " in this filter" +
    (filter.goldRecall != null ? " · gold recall " + esc(filter.goldRecall) : "") + "</p>" +
    table(["company", "book", "fiscal_period", "class", "dimension", "excerpt"],
      missed.map(r => [esc(labelOf(r.ticker)), esc(bookLabel(r.book_id)), esc(r.fiscal_period), esc(r.class), esc(r.dimension), esc(r.excerpt)]));
}
function buildTreeDetailsHtml(tree) {
  const scoring = tree.current_kind || tree.kind || "";
  const outcome = scoring === "promise" ? tree.delivery : tree.goal_outcome;
  const slippedBadge = tree.slipped ? " <span style='color:var(--warn);font-weight:700'>[SLIPPED]</span>" : "";
  const title = esc(labelOf(tree.ticker) + " " + (tree.title || "") + " · " + treeKindLabel(tree) + " · " +
    (tree.state || "") + " / " + (outcome || "")) + slippedBadge;
  // Always collapsed — slipped trees get a visual badge instead of auto-open
  let html = '<details class="tree"><summary>' + title + "</summary>";
  html += '<p class="cite">' + esc(tree.tree_id) + " · " + esc(bookLabel(tree.book_id)) + " · " +
    esc(tree.beat_id) + " · " +
    esc(bucketLabel(treeBucket(tree))) + " · clock " + esc(tree.clock || "—") + " · " +
    (tree.open ? "open" : "closed") + "</p>";
  if (tree.parent_tree_id) html += '<p class="cite">Evolved from ' + esc(tree.parent_tree_id) + ". Parent seed cite is kept.</p>";
  if (tree.goal_outcome === "became-promise") html += '<p class="cite">Became a promise. Same tree. Current label is promise (was goal) until the promise closes.</p>';
  for (const row of treeNodeRows(tree)) {
    let lab = (row.fiscal_period || "") + " · " + nodeEdgeLabel(row);
    if (row.slipped) lab += " · slipped";
    html += "<p><strong>" + esc(lab) + "</strong></p>";
    if (row.citation) html += '<p class="cite">' + esc(row.citation) + "</p>";
    if (row.excerpt) html += "<p>" + esc(row.excerpt) + "</p>";
    else if (row.edge === "silent") html += '<p class="silent">Silent quarter. No cite on this object.</p>';
    else if (row.edge === "expired") html += '<p class="silent">Expired. Completeness is unfeasible. Not a miss and not a withdrawal.</p>';
  }
  if (tree.coverage_summary) html += "<p><strong>Coverage.</strong> " + esc(tree.coverage_summary) + "</p>";
  html += "</details>";
  return html;
}

function renderTrees(trees) {
  const host = document.getElementById("trees");
  const bucket = document.getElementById("list-bucket")?.value || ALL;
  const groupBy = document.getElementById("list-group")?.value || "bucket";
  const groupSel = select("list-group", ["bucket", "company", "period"], groupBy, "Group by");
  host.innerHTML = "<h2>Trees</h2><p class='cap'>Bucket is the claim theme. Seed dimension is the novelty label of that sentence. All trees start collapsed; SLIPPED trees are flagged in the title.</p>" +
    "<p class='cap'>" + esc(EXPIRE_CAPTION) + "</p>" +
    '<div class="controls">' + select("list-bucket", DESK.bucket_filter_choices, bucket, "Bucket") +
    "&nbsp;&nbsp;" + groupSel + "</div><div id='tree-list'></div>";
  const listed = filterTreesToBucket(trees, bucket);
  const list = document.getElementById("tree-list");
  if (!listed.length) { list.innerHTML = '<p class="empty">No trees in this bucket.</p>'; }
  else {
    let html = "";
    if (groupBy === "company") {
      const byTicker = {};
      for (const tree of listed) {
        const t = String(tree.ticker || "").toUpperCase();
        if (!byTicker[t]) byTicker[t] = [];
        byTicker[t].push(tree);
      }
      for (const ticker of Object.keys(byTicker).sort()) {
        const coListed = byTicker[ticker];
        html += "<h3>" + esc(labelOf(ticker)) + " — " + esc(String(coListed.length)) + " tree(s)</h3>";
        for (const [key, group] of groupTreesByBucket(coListed)) {
          html += "<h4 style='margin:8px 0 4px'>" + esc(bucketLabel(key)) + "</h4>";
          for (const tree of group) html += buildTreeDetailsHtml(tree);
        }
      }
    } else if (groupBy === "period") {
      // Group by seed fiscal period, newest first
      const byPeriod = {};
      for (const tree of listed) {
        const p = (tree.seed || {}).fiscal_period || "";
        if (!byPeriod[p]) byPeriod[p] = [];
        byPeriod[p].push(tree);
      }
      const sortedPeriods = Object.keys(byPeriod).sort((a, b) => b.localeCompare(a));
      for (const period of sortedPeriods) {
        html += "<h3>Seeded " + esc(period || "—") + " (" + esc(String(byPeriod[period].length)) + ")</h3>";
        for (const tree of byPeriod[period]) html += buildTreeDetailsHtml(tree);
      }
    } else {
      // Default: group by bucket
      for (const [key, group] of groupTreesByBucket(listed)) {
        html += "<h3>" + esc(bucketLabel(key)) + "</h3>";
        for (const tree of group) html += buildTreeDetailsHtml(tree);
      }
    }
    list.innerHTML = html;
  }
  document.getElementById("list-bucket").onchange = () => renderTrees(trees);
  const groupEl = document.getElementById("list-group");
  if (groupEl) groupEl.onchange = () => renderTrees(trees);
}
function renderManagementRegimes(filter) {
  const host = document.getElementById("management-regimes");
  const sidecar = DESK.regimes;
  if (!sidecar) { host.innerHTML = ""; return; }
  const names = bookNames(filter.bookId);
  const regimes = sidecar.regimes || [];
  let regimeRates = {};
  let transferLedger = [];
  for (const name of names) {
    const bookBlock = (sidecar.books || {})[name] || {};
    regimeRates = Object.assign(regimeRates, bookBlock.regime_rates || {});
    transferLedger = transferLedger.concat(bookBlock.transfer_ledger || []);
  }
  if (filter.visible.length) {
    const allow = new Set(filter.visible);
    const kept = {};
    for (const [regimeId, data] of Object.entries(regimeRates)) {
      const meta = regimes.find(r => r.regime_id === regimeId) || {};
      if (allow.has(String(meta.ticker || "").toUpperCase())) kept[regimeId] = data;
    }
    regimeRates = kept;
    transferLedger = transferLedger.filter(e => allow.has(String(e.ticker || "").toUpperCase()));
  }

  // Current-regime rates table
  const rateRows = [];
  for (const [regimeId, data] of Object.entries(regimeRates)) {
    const counts = data.known_delivered_counts || {};
    const kd = counts.known_delivered_rate != null ? (counts.known_delivered_rate * 100).toFixed(0) + "%" : "—";
    const ss = counts.settled_share != null ? (counts.settled_share * 100).toFixed(0) + "%" : "—";
    const regimeMeta = regimes.find(r => r.regime_id === regimeId) || {};
    rateRows.push([
      esc(regimeMeta.ticker || ""),
      esc(regimeMeta.named_person || regimeId),
      esc(regimeMeta.start_fiscal || ""),
      esc(regimeMeta.end_fiscal || "present"),
      esc(String(data.n_trees || 0)),
      esc(kd),
      esc(ss),
    ]);
  }
  rateRows.sort((a, b) => a[0].localeCompare(b[0]));

  let html = "<h2>Management Regimes</h2>";
  html += "<p class='cap'>" + esc(sidecar.caption || "") + "</p>";

  if (rateRows.length) {
    html += "<h3>Current-regime accountability rates</h3>";
    html += table(
      ["Ticker", "CEO", "From", "To", "Trees", "KD rate", "Settled %"],
      rateRows
    );
  }

  // Transfer ledger — exclude prior_closed (already closed before the transition)
  const filteredLedger = transferLedger.filter(e => e.transfer_kind !== "prior_closed");
  if (filteredLedger.length) {
    const kindLabels = {
      "inherited_adopted": "Adopted by new regime",
      "inherited_closed_by_successor": "Closed by successor",
      "inherited_overdue": "Inherited — overdue",
      "inherited_ignored": "Inherited — ignored",
    };
    html += "<h3>Cite-transfer ledger</h3>";
    html += "<p class='cap'>Trees that were seeded under one CEO and were open at a regime transition. ";
    html += "<em>Inherited — overdue</em>: open at transition with a past-due clock. ";
    html += "<em>Inherited — ignored</em>: open, clock not yet due. ";
    html += "<em>Adopted</em>: new regime posted a non-silent cite. ";
    html += "<em>Closed by successor</em>: new regime provided the terminal node. ";
    html += "Trees closed before the transition are excluded.</p>";
    const ledgerRows = filteredLedger.map(e => [
      esc(e.ticker || ""),
      esc(e.title || ""),
      esc(kindLabels[e.transfer_kind] || e.transfer_kind || ""),
      esc(e.seed_regime_person || e.seed_regime || ""),
      esc(e.seed_fiscal || ""),
      esc(e.transition_fiscal || ""),
      esc(e.clock || "—"),
      esc(e.delivery || "—"),
    ]);
    html += table(
      ["Ticker", "Title", "Transfer kind", "Seeded under", "Seed fiscal", "Transition", "Clock", "Delivery"],
      ledgerRows
    );
  } else {
    html += "<p class='cap'>No inherited (open-at-transition) trees in this filter.</p>";
  }

  host.innerHTML = html;
}

function confidenceBadge(conf) {
  const colors = { high: "#5cb85c", medium: "#f0ad4e", low: "#d9534f" };
  const c = String(conf || "").toLowerCase();
  const bg = colors[c] || "#666";
  return '<span style="background:' + bg + ';color:#111;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:600;">' + esc(conf || "—") + '</span>';
}
function edgeBadge(edge) {
  const colors = { delivered: "#5cb85c", hit: "#5cb85c", missed: "#d9534f", expired: "#f0ad4e", none: "#888" };
  const c = String(edge || "").toLowerCase();
  const bg = colors[c] || "#888";
  return '<span style="background:' + bg + ';color:#111;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:600;">' + esc(edge || "—") + '</span>';
}
function citeBadge(verified) {
  if (verified === null || verified === undefined) return '<span class="muted">—</span>';
  return verified
    ? '<span style="color:#5cb85c;font-weight:600" title="Excerpt found verbatim in source">✓</span>'
    : '<span style="color:#d9534f;font-weight:600" title="LLM paraphrased — re-cite from novelty_view before typing">✗ paraphrased</span>';
}

function renderSeedCandidates(filter) {
  const host = document.getElementById("seed-candidates");
  const data = DESK.seed_candidates;
  if (!data) {
    host.innerHTML = "<h2>Seed Candidates</h2><p class='cap'>No seed candidate file found. Run <code>python scripts/_desk_seed_batch.py</code> to generate LLM-proposed seeds.</p>";
    return;
  }
  const byTicker = data.candidates_by_ticker || {};
  const priority = new Set(data.priority_tickers || []);
  const allow = new Set((filter && filter.visible) || []);
  const allTickers = Object.keys(byTicker).filter(t => !allow.size || allow.has(String(t).toUpperCase()));
  const ordered = [
    ...allTickers.filter(t => priority.has(t)),
    ...allTickers.filter(t => !priority.has(t)).sort(),
  ];
  let html = "<h2>Seed Candidates</h2>";
  html += "<p class='cap'>LLM-proposed tree seeds from " + esc(String(data.n_cue_rows_reviewed || 0)) +
    " uncovered cue rows across " + esc(String(data.n_tickers_scanned || 0)) + " tickers. " +
    "Do not auto-insert. Human review required before typing into catalog files.</p>";
  html += "<p class='cap'><strong>" + esc(String(data.n_proposed_seeds || 0)) + "</strong> proposed seeds · " +
    esc(String(data.n_excerpt_unverified || 0)) + " with paraphrased excerpts (✗ — re-cite before typing) · " +
    "Generated " + esc((data.generated_at || "").slice(0, 10)) +
    (data.complete === false ? " · <span style='color:var(--warn)'>PARTIAL RUN</span>" : "") + "</p>";
  if (!ordered.length) {
    html += "<p class='empty'>No candidate file found. Run scripts/_desk_seed_batch.py to generate.</p>";
    host.innerHTML = html;
    return;
  }
  for (const ticker of ordered) {
    const cands = byTicker[ticker] || [];
    if (!cands.length) continue;
    const isPriority = priority.has(ticker);
    const summaryLabel = esc(labelOf(ticker)) + (isPriority ? " <span style='color:#c4b48a;font-size:11px'>[regime-transition]</span>" : "") +
      " — " + esc(String(cands.length)) + " candidate" + (cands.length === 1 ? "" : "s");
    html += "<details style='margin-bottom:6px'><summary style='cursor:pointer;font-weight:600;padding:4px 0'>" + summaryLabel + "</summary>";
    html += "<table><thead><tr>";
    html += "<th>Conf</th><th>Cite</th><th>Kind</th><th>Bucket</th><th>Title</th><th>Fiscal</th><th>Clock</th><th>Excerpt</th><th>Rationale</th><th>Seed</th>";
    html += "</tr></thead><tbody>";
    for (const cand of cands) {
      const seed = cand.seed || {};
      html += "<tr>";
      html += "<td>" + confidenceBadge(cand.confidence) + "</td>";
      html += "<td>" + citeBadge(cand.excerpt_verified) + "</td>";
      html += "<td>" + esc(cand.kind || "") + "</td>";
      html += "<td>" + esc(DESK.bucket_labels[cand.bucket] || cand.bucket || "") + "</td>";
      html += "<td>" + esc(cand.title || "") + "</td>";
      html += "<td>" + esc(seed.fiscal_period || "") + "</td>";
      html += "<td>" + esc(seed.clock || "—") + "</td>";
      html += "<td style='max-width:300px'>" + esc((seed.excerpt || "").slice(0, 200)) + "…</td>";
      html += "<td style='max-width:200px'>" + esc(cand.rationale || "") + "</td>";
      const py = esc(cand.proposed_seed_py || "");
      html += "<td><details><summary style='cursor:pointer;color:var(--accent)'>dict</summary><pre style='font-size:11px;margin:4px 0;white-space:pre-wrap;max-width:420px'>" + py + "</pre></details></td>";
      html += "</tr>";
    }
    html += "</tbody></table></details>";
  }
  host.innerHTML = html;
}

function tierBadge(t) {
  if (t === null || t === undefined) return "<span class='tier' title='no retrieval'>—</span>";
  const n = Number(t);
  const cls = n >= 4 ? "t" + n : (n === 3 ? "t3" : "");
  const label = {0: "T0 exact", 1: "T1 alias", 2: "T2 co-occur", 3: "T3 widened", 4: "T4 Haiku triage", 5: "T5 Haiku+Sonnet"}[n] || ("T" + n);
  return "<span class='tier " + cls + "' title='" + esc(label) + "'>" + esc(String(n)) + "</span>";
}

function usd(x) {
  if (x === null || x === undefined || x === "") return "—";
  const n = Number(x);
  return isNaN(n) ? "—" : "$" + n.toFixed(n < 0.1 ? 4 : 2);
}

function budgetHeader(data) {
  const b = data.budget || {};
  const cov = data.coverage || {};
  const tiers = data.tier_counts || {};
  const tierStr = Object.keys(tiers).length
    ? Object.entries(tiers).map(([k, v]) => "T" + k + ":" + v).join(" · ") : "—";
  let html = "<div class='budget'>";
  html += "<span>Run: <b>" + (data.plan_mode ? "PLAN (no API calls)" : "live") + "</b></span>";
  html += "<span>Evidence: <b>" + esc(data.evidence_source ? "transcripts_raw" : "novelty_view") + "</b></span>";
  html += "<span>Sonnet spend: <b>" + usd(b.sonnet_spent_usd) + "</b></span>";
  html += "<span>Fallback budget: <b>" + usd(b.fallback_spent_usd) + " / " + usd(b.fallback_allowed_usd) + "</b>" +
    (b.fallback_trees ? " (" + esc(String(b.fallback_trees)) + " trees" + (b.refused_trees ? ", " + esc(String(b.refused_trees)) + " refused" : "") + ")" : "") + "</span>";
  html += "<span>Paid calls: <b>" + esc(String(b.n_paid_calls || 0)) + "</b></span>";
  html += "<span>Tiers: <b>" + esc(tierStr) + "</b></span>";
  if (cov.window_quarters !== undefined) {
    html += "<span>Clock-window transcripts: <b>" + esc(String(cov.window_present || 0)) + "/" + esc(String(cov.window_quarters || 0)) + "</b> present</span>";
  }
  html += "</div>";
  return html;
}

const REASON_HELP = {
  no_evidence_retrieved: "Tiers 0–3 searched every present clock-window transcript and found nothing. Widen anchors/context in the catalog match block, or re-run with --fallback-budget-usd.",
  numeric_target_no_strict_match: "All anchors are numbers; strict numeric matching found nothing. Add a non-numeric anchor (product/program name) to the match block.",
  transcript_missing: "A clock-window transcript is not in transcripts_raw. Back-fill it (scripts/_desk_transcript_backfill.py) before judging.",
  fallback_budget_exhausted: "Paid triage was needed but the run budget could not cover it.",
  no_clock_open_goal: "Open goal with no clock: Tier 3 searched all post-seed quarters with zero hits; nothing principled to buy.",
  no_transcripts_indexed: "No indexed transcripts exist for this ticker.",
  llm_low_confidence: "Sonnet proposed a terminal at low confidence or quoted text not verbatim in the evidence.",
  llm_failed: "The LLM call errored or returned malformed JSON.",
  expired_guard: "Sonnet proposed expired but the clock is still open or the window has gaps — downgraded to none.",
};

function renderNeedsReview(filter) {
  const host = document.getElementById("needs-review");
  const data = DESK.terminal_candidates;
  if (!data || !Array.isArray(data.needs_review)) { host.innerHTML = ""; return; }
  const allow = new Set((filter && filter.visible) || []);
  const items = data.needs_review.filter(it => !allow.size || allow.has(String(it.ticker || "").toUpperCase()));
  if (!items.length) {
    host.innerHTML = "<details open><summary style='cursor:pointer;font-weight:600'><span class='review-badge'>Needs Review — 0</span></summary><p class='cap'>Every open tree either has retrieved evidence or a verdict. Nothing is parked.</p></details>";
    return;
  }
  const reasons = data.needs_review_reasons || {};
  let innerHtml = "<div class='review-banner'>";
  innerHtml += "<p class='cap'>These are parked, not closed. Each row says why and what would unblock it. " +
    Object.entries(reasons).map(([k, v]) => "<span class='reason'>" + esc(k) + "</span>×" + esc(String(v))).join(" · ") + "</p>";
  innerHtml += "<table><thead><tr><th>Reason</th><th>Company</th><th>Tree</th><th>Kind</th><th>Seed</th><th>Clock</th><th>Window present</th><th>Anchors tried</th><th>Detail</th><th>Unblock</th></tr></thead><tbody>";
  for (const it of items) {
    const missing = it.transcripts_missing || [];
    const winN = (it.clock_window || []).length;
    innerHtml += "<tr>";
    innerHtml += "<td><span class='reason'>" + esc(it.reason || "") + "</span>" + (it.expired_eligible ? "<br><span class='cite'>expired-eligible</span>" : "") + "</td>";
    innerHtml += "<td>" + esc(labelOf(it.ticker)) + "</td>";
    innerHtml += "<td>" + esc(it.title || it.tree_id || "") + "<br><span class='cite'>" + esc(it.tree_id || "") + "</span></td>";
    innerHtml += "<td>" + esc(it.kind || "") + "</td>";
    innerHtml += "<td>" + esc(it.seed_fiscal || "") + "</td>";
    innerHtml += "<td>" + esc(it.clock || "—") + "</td>";
    innerHtml += "<td>" + (winN ? esc(String(it.transcripts_present || 0)) + "/" + esc(String(winN)) : "—") +
      (missing.length ? "<br><span class='silent'>" + esc(missing.join(", ")) + "</span>" : "") + "</td>";
    innerHtml += "<td style='max-width:200px'>" + esc((it.anchors_tried || []).join(", ")) + "</td>";
    innerHtml += "<td style='max-width:260px'>" + esc(it.detail || "") + "</td>";
    innerHtml += "<td style='max-width:280px' class='cite'>" + esc(REASON_HELP[it.reason] || "") + "</td>";
    innerHtml += "</tr>";
  }
  innerHtml += "</tbody></table></div>";
  // Start open — needs action
  host.innerHTML = "<details open><summary style='cursor:pointer;font-weight:600;padding:4px 0'>" +
    "<span class='review-badge'>Needs Review — " + esc(String(items.length)) + " open tree" + (items.length === 1 ? "" : "s") + " could not be resolved automatically</span>" +
    "</summary>" + innerHtml + "</details>";
}

function renderTerminalCandidates(filter) {
  const host = document.getElementById("terminal-candidates");
  const data = DESK.terminal_candidates;
  if (!data) { host.innerHTML = ""; return; }
  const allow = new Set((filter && filter.visible) || []);
  const candidates = (data.candidates || []).filter(c => !allow.size || allow.has(String(c.ticker || "").toUpperCase()));
  const retrievalFirst = !!data.evidence_source;
  const tcCount = candidates.length;
  const partial = data.complete === false ? " · <span style='color:var(--warn)'>PARTIAL RUN</span>" : "";
  let innerHtml = "<p class='cap'>" + (retrievalFirst ? "Retrieval-first terminal verdicts (raw-transcript evidence, Sonnet judgment) for " : "LLM-proposed terminal verdicts for ") +
    esc(String(data.n_open_trees_scored || 0)) +
    " open trees. Do not auto-insert. Human review required before typing nodes into catalog files.</p>";
  if (retrievalFirst) innerHtml += budgetHeader(data);
  innerHtml += "<p class='cap'><strong>" + esc(String(data.n_actionable || 0)) + "</strong> actionable (not none, &ge; medium confidence) · " +
    esc(String(data.n_excerpt_unverified || 0)) + " scored verdicts quote text not found in " + (retrievalFirst ? "the retrieved evidence" : "novelty_view") + " (&#10007;) · " +
    "Generated " + esc((data.generated_at || "").slice(0, 10)) +
    (data.complete === false ? " · <span style='color:var(--warn)'>PARTIAL RUN</span>" : "") + "</p>";
  let html;
  if (!candidates.length) {
    innerHtml += "<p class='empty'>No candidate file found. Run scripts/_desk_terminal_candidates.py to generate.</p>";
    html = "<details><summary style='cursor:pointer;font-weight:600;padding:4px 0'>Terminal Candidates (0)</summary>" + innerHtml + "</details>";
    host.innerHTML = html;
    return;
  }
  // Group by book
  const byBook = {};
  for (const c of candidates) {
    const bk = c.book || "unknown";
    if (!byBook[bk]) byBook[bk] = [];
    byBook[bk].push(c);
  }
  for (const [book, rows] of Object.entries(byBook)) {
    innerHtml += "<h3>" + esc(book) + "</h3>";
    innerHtml += "<table><thead><tr>";
    innerHtml += "<th>Edge</th><th>Conf</th><th>Cite</th><th>Company</th><th>Title</th><th>Kind</th><th>Seed fiscal</th><th>Proposed fiscal</th>";
    if (retrievalFirst) innerHtml += "<th>Tier</th><th>Paragraphs</th><th>Cost</th>";
    else innerHtml += "<th>Evidence q</th>";
    innerHtml += "<th>Reasoning</th><th>Node</th>";
    innerHtml += "</tr></thead><tbody>";
    for (const cand of rows) {
      const r = cand.retrieval || {};
      innerHtml += "<tr>";
      innerHtml += "<td>" + edgeBadge(cand.proposed_edge) + (cand.source === "retrieval" ? "<br><span class='cite'>no LLM</span>" : "") + "</td>";
      innerHtml += "<td>" + confidenceBadge(cand.confidence) + "</td>";
      innerHtml += "<td>" + citeBadge(cand.excerpt_verified) + "</td>";
      innerHtml += "<td>" + esc(labelOf(cand.ticker)) + "</td>";
      innerHtml += "<td>" + esc(cand.title || "") + (cand.guard ? "<br><span class='silent'>" + esc(cand.guard) + "</span>" : "") + "</td>";
      innerHtml += "<td>" + esc(cand.kind || "") + "</td>";
      innerHtml += "<td>" + esc(cand.seed_fiscal || "") + "</td>";
      innerHtml += "<td>" + esc(cand.proposed_fiscal || "—") + "</td>";
      if (retrievalFirst) {
        const missing = r.window_missing || [];
        innerHtml += "<td>" + tierBadge(r.tier) + "</td>";
        innerHtml += "<td title='" + esc("searched " + (r.quarters_searched || []).length + " quarters; " + (r.n_hits_total || 0) + " sentence hits before cap") + "'>" +
          esc(String(cand.n_evidence_excerpts || 0)) + "<br><span class='cite'>" + esc((r.quarters_searched || []).length + " q") +
          (missing.length ? " · <span class='silent'>" + esc(missing.length + " missing") + "</span>" : "") + "</span></td>";
        const tri = r.triage || {};
        innerHtml += "<td>" + usd(r.usd !== undefined && r.usd !== null ? r.usd : r.est_usd) +
          (tri.usd || tri.est_usd ? "<br><span class='cite'>+triage " + usd(tri.usd || tri.est_usd) + "</span>" : "") +
          (cand.plan ? "<br><span class='cite'>est.</span>" : "") + "</td>";
      } else {
        innerHtml += "<td>" + esc(String(cand.n_evidence_excerpts || 0)) + "</td>";
      }
      innerHtml += "<td style='max-width:260px'>" + esc((cand.reasoning || "").slice(0, 220)) + "</td>";
      const py = esc(cand.proposed_node_py || "");
      innerHtml += "<td><details><summary style='cursor:pointer;color:var(--accent)'>node</summary><pre style='font-size:11px;margin:4px 0;white-space:pre-wrap;max-width:420px'>" + py + "</pre></details></td>";
      innerHtml += "</tr>";
    }
    innerHtml += "</tbody></table>";
  }
  // Collapsed by default — requires deliberate review before typing nodes
  host.innerHTML = "<details><summary style='cursor:pointer;font-weight:600;padding:4px 0'>Terminal Candidates (" +
    esc(String(tcCount)) + ")" + partial + " — expand to review</summary>" + innerHtml + "</details>";
}

function boot() {
  document.getElementById("book-controls").innerHTML =
    select("book", DESK.book_order, DESK.default_book, "Book") +
    '<div><label for="custom-list">Custom list</label>' +
    '<input type="search" id="custom-list" placeholder="CRWV, NVDA" /></div>' +
    '<div><label for="companies">Companies</label>' +
    '<select id="companies" multiple size="6"></select></div>';
  document.getElementById("book").onchange = () => { rebuildCompanySelect(); render(); };
  document.getElementById("custom-list").onchange = () => { rebuildCompanySelect(); render(); };
  document.getElementById("custom-list").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); rebuildCompanySelect(); render(); }
  });
  document.getElementById("companies").onchange = render;
  rebuildCompanySelect();
  render();
}
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
