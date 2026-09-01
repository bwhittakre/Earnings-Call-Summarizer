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
  if (DESK.bucket_labels[opt]) return DESK.bucket_labels[opt];
  if (DESK.labels[opt]) return DESK.labels[opt];
  return opt;
}
function select(id, options, selected, labels) {
  return '<label for="' + id + '">' + esc(labels || id) + '</label><select id="' + id + '">' +
    options.map(opt => '<option value="' + esc(opt) + '"' + (opt === selected ? " selected" : "") + '>' +
      esc(optionLabel(opt)) +
      "</option>").join("") + "</select>";
}
function currentBook() {
  return DESK.books[document.getElementById("book").value] || DESK.books[DESK.default_book];
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
  const book = currentBook();
  const trees = book.trees || [];
  const deliver = (book.deliver_rates || {}).book || {};
  const hits = (book.hit_rates || {}).book || {};
  const conversion = book.conversion || {};
  const windowText = (book.window && book.window.length)
    ? book.window[0] + "–" + book.window[book.window.length - 1]
    : "operational, no gold window";
  document.getElementById("book-caption").textContent = book.caption || "";
  document.getElementById("book-meta").textContent =
    "Stamp " + (book.generated_at || "—") + " · " + (book.split || "") +
    " · calendar " + (book.calendar || "") + " · window " + windowText +
    ". Sector filter all does not retune xlk_tech.";
  document.getElementById("rates").innerHTML =
    '<div class="card"><h2>Deliver rate</h2><p class="cap">' + esc(scoredRateCaption(deliver.n_scoreable, "promises")) +
    '</p><div class="metric">' + esc(formatRate(deliver.deliver_rate)) + '</div><p class="cap">' +
    esc((deliver.delivered || 0) + " delivered / " + (deliver.n_scoreable || 0) + " scored") + "</p></div>" +
    '<div class="card"><h2>Hit rate</h2><p class="cap">' + esc(scoredRateCaption(hits.n_scoreable, "goals")) +
    '</p><div class="metric">' + esc(formatRate(hits.hit_rate)) + '</div><p class="cap">' +
    esc((hits.hit || 0) + " hit / " + (hits.n_scoreable || 0) + " scored") + "</p></div>";
  document.getElementById("conversion").innerHTML =
    "<h2>Became a promise</h2><p class='cap'>" + esc(conversionCaption(conversion)) +
    "</p><div class='metric'>" + esc(formatRate(conversion.harden_rate)) +
    "</div><p class='cap'>" + esc((conversion.n_became_promise || 0) + " became a promise / " +
    (conversion.n_goals || 0) + " goals. Not desk_trust. Same tree stays open until the promise closes.") + "</p>";

  const known = book.known_delivered || {};
  document.getElementById("known-delivered").innerHTML =
    "<h2>Known-delivered</h2>" +
    "<p class='cap'>This is what we know has been delivered. Aged trees we cannot settle sit in the denominator.</p>" +
    "<p class='cap'>" + esc(knownDeliveredCaption(known)) +
    "</p><div class='metric'>" + esc(formatRate(known.known_delivered_rate)) +
    "</div><p class='cap'>" + esc((known.n_confirmed || 0) + " confirmed / " +
    (known.n_aged || 0) + " aged · settled share " + formatRate(known.settled_share) +
    " · " + (known.n_unknown || 0) + " unknown. Not desk_trust.") + "</p>";

  renderTransparency(book);
  renderQuant(book);
  renderManagementRegimes(book.book_id);

  const cred = document.getElementById("credibility");
  if (book.book_id === "nvda_gold_v2" && DESK.metrics) {
    const rows = (DESK.metrics.rows || []).filter(r => r.desk_trust_n || r.desk_ambition_n);
    cred.innerHTML = "<h2>Trailing credibility</h2><p class='cap'>Point-in-time expanding rates on management_confidence. A quarter only sees terminals already cited. Null is an em dash.</p>" +
      table(["company", "fiscal_period", "trust", "trust_n", "ambition", "ambition_n"],
        rows.map(r => [esc(labelOf(r.ticker)), esc(r.fiscal_period), esc(formatRate(r.desk_trust)),
          esc(r.desk_trust_n), esc(formatRate(r.desk_ambition)), esc(r.desk_ambition_n)]));
  } else cred.innerHTML = "";

  const latest = book.latest;
  const board = clockBoard(trees, latest);
  let clockHtml = "<h2>Due and slipped</h2><p class='cap'>As of " + esc(latest || "—") +
    ". Open clocks on typed trees. Slipped here is a typed silent plus a due clock, not missed. " +
    "The neglect ledger above scores later calls that did not take up a prior claim. " +
    "Open trees with no clock are someday wants, not due.</p>";
  const clockRows = [...board.slipped, ...board.due];
  if (clockRows.length) {
    clockHtml += table(["bucket", "company", "claim", "kind", "clock"],
      clockRows.map(r => [esc(r.slipped ? "slipped" : "due"), esc(labelOf(r.ticker)), esc(r.title), esc(r.kind), esc(r.clock || "—")]));
  }
  if (board.open_no_clock.length) {
    clockHtml += "<p class='cap'>" + board.open_no_clock.length + " open trees have no clock (soft someday wants).</p>";
    clockHtml += table(["claim", "kind", "state"],
      board.open_no_clock.map(r => [esc(r.title), esc(r.kind), esc(r.state)]));
  }
  document.getElementById("clocks").innerHTML = clockHtml;

  renderHorizon(book, trees);
  renderQuotes(book);
  renderUncovered(book);
  renderTrees(trees);
}
function renderTransparency(book) {
  const host = document.getElementById("transparency");
  const payload = DESK.transparency;
  if (!payload) {
    host.innerHTML = "<h2>Management transparency</h2><p class='cap'>Rebuild the sidecar with python scripts/_desk_transparency_v2.py. This is not desk_trust.</p>";
    return;
  }
  const block = ((payload.books || {})[book.book_id] || {});
  const counts = block.book || {};
  const companies = block.by_company || [];
  const ledger = block.ledger || [];
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
function renderQuant(book) {
  const host = document.getElementById("quant");
  const payload = DESK.quant;
  let html = "<h2>Quant cross-check</h2><p class='cap'>" + esc(EXPIRE_CAPTION) + "</p>" +
    "<p class='cap'>Clocked trees check at the clock. Unclocked trees wait four silent quarters, then stop at expire or seed+8Q. A missing actual is expired, not a miss. Not desk_trust.</p>";
  if (!payload) {
    html += "<p class='cap'>Rebuild the sidecar with python scripts/_desk_quant_v2.py. This is not desk_trust.</p>";
    host.innerHTML = html;
    return;
  }
  const block = ((payload.books || {})[book.book_id] || {});
  const rows = block.rows || [];
  html += "<p class='cap'>" + esc(payload.caption || "") + "</p>" +
    "<p class='cap'>As of " + esc(block.as_of || book.latest || "—") +
    ". Binding, clock vs unclocked cap, last actual, verdict, next check, stop fiscal.</p>";
  if (!rows.length) {
    html += "<p class='cap'>No expire or quant bindings on this book.</p>";
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
function renderHorizon(book, trees) {
  const host = document.getElementById("horizon");
  const span = fiscalSpan(book.span[0], book.span[1]);
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
  const events = filterHorizonEvents((book.horizon_events || []).filter(e => ids.has(e.tree_id)), {
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
    .forEach(id => document.getElementById(id).onchange = () => renderHorizon(book, trees));
}
function renderQuotes(book) {
  const host = document.getElementById("quotes");
  const rows = book.quotes || [];
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
  host.querySelectorAll("input").forEach(i => i.onchange = () => renderQuotes(book));
}
function renderUncovered(book) {
  const queue = book.queue || {};
  const missed = queue.missed || [];
  const host = document.getElementById("uncovered");
  if (!missed.length) { host.innerHTML = ""; return; }
  const gold = queue.gold || {};
  host.innerHTML = "<h2>Uncovered cues</h2><p class='cap'>Seedable promise/goal cues in novelty_view that are not yet on a typed tree. Do not auto-seed. Gold 20Q recall stays locked.</p>" +
    "<p class='cap'>Full-history missed " + esc(queue.n_missed) + " / " + esc(queue.n_seedable) +
    " · gold recall " + esc(gold.recall) + "</p>" +
    table(["company", "fiscal_period", "class", "dimension", "excerpt"],
      missed.map(r => [esc(labelOf(r.ticker)), esc(r.fiscal_period), esc(r.class), esc(r.dimension), esc(r.excerpt)]));
}
function renderTrees(trees) {
  const host = document.getElementById("trees");
  const bucket = document.getElementById("list-bucket")?.value || ALL;
  host.innerHTML = "<h2>Trees</h2><p class='cap'>Bucket is the claim theme. Seed dimension is the novelty label of that sentence.</p>" +
    "<p class='cap'>" + esc(EXPIRE_CAPTION) + "</p>" +
    '<div class="controls">' + select("list-bucket", DESK.bucket_filter_choices, bucket, "Bucket") + "</div><div id='tree-list'></div>";
  const listed = filterTreesToBucket(trees, bucket);
  const list = document.getElementById("tree-list");
  if (!listed.length) { list.innerHTML = '<p class="empty">No trees in this bucket.</p>'; }
  else {
    let html = "";
    for (const [key, group] of groupTreesByBucket(listed)) {
      html += "<h3>" + esc(bucketLabel(key)) + "</h3>";
      for (const tree of group) {
        const scoring = tree.current_kind || tree.kind || "";
        const outcome = scoring === "promise" ? tree.delivery : tree.goal_outcome;
        const title = labelOf(tree.ticker) + " " + (tree.title || "") + " · " + treeKindLabel(tree) + " · " +
          (tree.state || "") + " / " + (outcome || "");
        html += '<details class="tree"' + (tree.slipped ? " open" : "") + "><summary>" + esc(title) + "</summary>";
        html += '<p class="cite">' + esc(tree.tree_id) + " · " + esc(tree.beat_id) + " · " +
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
      }
    }
    list.innerHTML = html;
  }
  document.getElementById("list-bucket").onchange = () => renderTrees(trees);
}
function renderManagementRegimes(book) {
  const host = document.getElementById("management-regimes");
  const sidecar = DESK.regimes;
  if (!sidecar) { host.innerHTML = ""; return; }
  const bookBlock = (sidecar.books || {})[book] || {};
  const regimes = sidecar.regimes || [];
  const regimeRates = bookBlock.regime_rates || {};
  const transferLedger = bookBlock.transfer_ledger || [];

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

  // Transfer ledger
  if (transferLedger.length) {
    const kindLabels = {
      "prior_closed": "Closed before transition",
      "inherited_adopted": "Adopted by new regime",
      "inherited_closed_by_successor": "Closed by successor",
      "inherited_overdue": "Inherited — overdue",
      "inherited_ignored": "Inherited — ignored",
    };
    html += "<h3>Cite-transfer ledger</h3>";
    html += "<p class='cap'>Trees that were seeded under one CEO and outlived a regime transition. ";
    html += "<em>Inherited — overdue</em>: open at transition with a past-due clock. ";
    html += "<em>Inherited — ignored</em>: open, clock not yet due. ";
    html += "<em>Adopted</em>: new regime posted a non-silent cite. ";
    html += "<em>Closed by successor</em>: new regime provided the terminal node.</p>";
    const ledgerRows = transferLedger.map(e => [
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
    html += "<p class='cap'>No regime-crossing trees in this book.</p>";
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

function renderSeedCandidates() {
  const host = document.getElementById("seed-candidates");
  const data = DESK.seed_candidates;
  if (!data) { host.innerHTML = ""; return; }
  const byTicker = data.candidates_by_ticker || {};
  const priority = new Set(data.priority_tickers || []);
  // Tickers: priority first, then alphabetical
  const allTickers = Object.keys(byTicker);
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
    html += "<h3>" + esc(labelOf(ticker)) + (isPriority ? " <span style='color:#c4b48a;font-size:11px'>[regime-transition]</span>" : "") + "</h3>";
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
    html += "</tbody></table>";
  }
  host.innerHTML = html;
}

function renderTerminalCandidates() {
  const host = document.getElementById("terminal-candidates");
  const data = DESK.terminal_candidates;
  if (!data) { host.innerHTML = ""; return; }
  const candidates = data.candidates || [];
  let html = "<h2>Terminal Candidates</h2>";
  html += "<p class='cap'>LLM-proposed terminal verdicts for " + esc(String(data.n_open_trees_scored || 0)) +
    " open trees. Do not auto-insert. Human review required before typing nodes into catalog files.</p>";
  html += "<p class='cap'><strong>" + esc(String(data.n_actionable || 0)) + "</strong> actionable (not none, ≥ medium confidence) · " +
    esc(String(data.n_excerpt_unverified || 0)) + " scored verdicts quote text not found in novelty_view (✗) · " +
    "Generated " + esc((data.generated_at || "").slice(0, 10)) +
    (data.complete === false ? " · <span style='color:var(--warn)'>PARTIAL RUN</span>" : "") + "</p>";
  if (!candidates.length) {
    html += "<p class='empty'>No candidate file found. Run scripts/_desk_terminal_candidates.py to generate.</p>";
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
    html += "<h3>" + esc(book) + "</h3>";
    html += "<table><thead><tr>";
    html += "<th>Edge</th><th>Conf</th><th>Cite</th><th>Company</th><th>Title</th><th>Kind</th><th>Seed fiscal</th><th>Proposed fiscal</th><th>Evidence q</th><th>Reasoning</th><th>Node</th>";
    html += "</tr></thead><tbody>";
    for (const cand of rows) {
      html += "<tr>";
      html += "<td>" + edgeBadge(cand.proposed_edge) + "</td>";
      html += "<td>" + confidenceBadge(cand.confidence) + "</td>";
      html += "<td>" + citeBadge(cand.excerpt_verified) + "</td>";
      html += "<td>" + esc(labelOf(cand.ticker)) + "</td>";
      html += "<td>" + esc(cand.title || "") + "</td>";
      html += "<td>" + esc(cand.kind || "") + "</td>";
      html += "<td>" + esc(cand.seed_fiscal || "") + "</td>";
      html += "<td>" + esc(cand.proposed_fiscal || "—") + "</td>";
      html += "<td>" + esc(String(cand.n_evidence_excerpts || 0)) + "</td>";
      html += "<td style='max-width:260px'>" + esc((cand.reasoning || "").slice(0, 220)) + "</td>";
      const py = esc(cand.proposed_node_py || "");
      html += "<td><details><summary style='cursor:pointer;color:var(--accent)'>node</summary><pre style='font-size:11px;margin:4px 0;white-space:pre-wrap;max-width:420px'>" + py + "</pre></details></td>";
      html += "</tr>";
    }
    html += "</tbody></table>";
  }
  host.innerHTML = html;
}

function boot() {
  document.getElementById("book-controls").innerHTML =
    select("book", DESK.book_order, DESK.default_book, "Book");
  document.getElementById("book").onchange = render;
  renderSeedCandidates();
  renderTerminalCandidates();
  render();
}
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
