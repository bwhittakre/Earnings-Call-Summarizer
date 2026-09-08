"""
Generates canvases/call-scorecard.canvas.tsx with embedded scorecard data.
"""
import json, pathlib

SCORECARD = pathlib.Path(
    r"C:\Users\BobbyWhittaker\OneDrive - Cassius Capital\Desktop\Earnings Call Summarizer"
    r"\data\desk_call_scorecard_v1.json"
)
OUT = pathlib.Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\canvases\call-scorecard.canvas.tsx"
)

data = json.loads(SCORECARD.read_text("utf-8"))
compact = json.dumps(data["entries"], separators=(",", ":")).replace("`", "\\`")

CANVAS = r"""import {
  useState, useMemo, CSSProperties,
  Card, CardHeader, CardBody,
  Grid, Row, Stack, Spacer, Divider,
  H1, Text, Pill, Stat,
  useHostTheme,
} from "cursor/canvas";

// ── embedded data ──────────────────────────────────────────────────────────
const RAW_ENTRIES: Entry[] = JSON.parse(`""" + compact + r"""`);

// ── types ──────────────────────────────────────────────────────────────────
interface Entry {
  ticker: string;
  fiscal_period: string;
  book_id: string;
  delivery_score: number | null;
  n_confirmed: number;
  n_failed: number;
  n_withdrawn: number;
  n_aged: number;
  engagement_score: number;
  n_restated: number;
  n_new_seeds: number;
  n_deferred: number;
  n_dropped: number;
  n_silent: number;
  open_trees_at_call: number;
  n_never_touched: number;
  n_open_stale: number;
  pct_never_touched: number;
}

// ── helpers ──────────────────────────────────────────────────────────────────
function fiscalKey(fp: string): number {
  const [y, q] = fp.split("-");
  return parseInt(y.slice(2)) * 10 + parseInt(q.slice(1));
}

const BOOK_LABEL: Record<string, string> = {
  nvda_gold_v2: "NVDA",
  desk_ops_v2: "Tech/Ops",
  desk_hc_v2: "Healthcare",
};

function quadrantLabel(e: Entry): string {
  const d = e.delivery_score ?? 0;
  const eng = e.engagement_score;
  if (d >= 0.5 && eng >= 0) return "Credible & Committed";
  if (d >= 0.5 && eng < 0)  return "Quietly Delivering";
  if (d < 0.5  && eng >= 0) return "Aspirational";
  return "Retreating";
}

// ── QuadrantPlot (SVG) ────────────────────────────────────────────────────────
interface PlotProps {
  entries: Entry[];
  selected: Entry | null;
  onSelect: (e: Entry) => void;
  connectDots?: boolean;
}

function QuadrantPlot({ entries, selected, onSelect, connectDots }: PlotProps) {
  const { tokens, palette } = useHostTheme();
  const W = 440, H = 370, PAD = 44;
  const innerW = W - PAD * 2, innerH = H - PAD * 2;
  const midX = PAD + innerW / 2;
  const midY = PAD + innerH / 2;

  // map delivery (0-1) and engagement (-1 to 1) to SVG coords
  const sx = (e: Entry) => PAD + (e.delivery_score ?? 0) * innerW;
  const sy = (e: Entry) => PAD + (1 - (e.engagement_score + 1) / 2) * innerH;

  const sorted = connectDots
    ? [...entries].sort((a, b) => fiscalKey(a.fiscal_period) - fiscalKey(b.fiscal_period))
    : entries;

  // quadrant tint colors from category palette
  const c = tokens.category;

  return (
    <svg width={W} height={H} style={{ display: "block", overflow: "visible" }}>
      {/* quadrant backgrounds */}
      <rect x={PAD} y={PAD} width={innerW / 2} height={innerH / 2} fill={c.green} opacity={0.08} />
      <rect x={midX} y={PAD} width={innerW / 2} height={innerH / 2} fill={c.blue} opacity={0.08} />
      <rect x={PAD} y={midY} width={innerW / 2} height={innerH / 2} fill={c.yellow} opacity={0.08} />
      <rect x={midX} y={midY} width={innerW / 2} height={innerH / 2} fill={c.red} opacity={0.08} />

      {/* axis lines */}
      <line x1={PAD} y1={midY} x2={PAD + innerW} y2={midY}
        stroke={tokens.stroke.secondary} strokeWidth={1} strokeDasharray="4 3" />
      <line x1={midX} y1={PAD} x2={midX} y2={PAD + innerH}
        stroke={tokens.stroke.secondary} strokeWidth={1} strokeDasharray="4 3" />

      {/* quadrant labels */}
      {([
        ["Credible &\nCommitted", PAD + 6, PAD + 12, "start", c.green],
        ["Aspirational", midX + 6, PAD + 12, "start", c.blue],
        ["Quietly\nDelivering", PAD + 6, midY + 14, "start", c.yellow],
        ["Retreating", midX + 6, midY + 14, "start", c.red],
      ] as [string, number, number, string, string][]).map(([label, x, y, anchor, col], i) => (
        <text key={i} x={x} y={y} fontSize={9} fill={col} fillOpacity={0.8}
          textAnchor={anchor as "start"} style={{ pointerEvents: "none" }}>
          {label.split("\n").map((l, j) => (
            <tspan key={j} x={x} dy={j === 0 ? 0 : 11}>{l}</tspan>
          ))}
        </text>
      ))}

      {/* trajectory line */}
      {connectDots && sorted.length > 1 && (
        <polyline
          points={sorted.map(e => `${sx(e)},${sy(e)}`).join(" ")}
          fill="none"
          stroke={tokens.accent.primary}
          strokeWidth={1.5}
          strokeOpacity={0.45}
          strokeDasharray="5 3"
        />
      )}

      {/* dots */}
      {sorted.map((e, i) => {
        const isSelected =
          selected?.ticker === e.ticker && selected?.fiscal_period === e.fiscal_period;
        const q = quadrantLabel(e);
        const dotColor =
          q === "Credible & Committed" ? c.green :
          q === "Aspirational"         ? c.blue  :
          q === "Quietly Delivering"   ? c.yellow :
          c.red;
        const r = 5 + e.pct_never_touched * 3;
        return (
          <g key={i} style={{ cursor: "pointer" }} onClick={() => onSelect(e)}>
            {e.pct_never_touched > 0.3 && (
              <circle cx={sx(e)} cy={sy(e)} r={r + 3.5}
                fill="none" stroke={c.orange} strokeWidth={1} opacity={0.5} />
            )}
            <circle
              cx={sx(e)} cy={sy(e)} r={r}
              fill={dotColor} opacity={isSelected ? 1 : 0.72}
              stroke={isSelected ? tokens.text.primary : "none"}
              strokeWidth={isSelected ? 1.5 : 0}
            />
            {connectDots && (
              <text x={sx(e) + r + 3} y={sy(e) - 3}
                fontSize={8} fill={tokens.text.tertiary}
                style={{ pointerEvents: "none" }}>
                {e.fiscal_period.replace("FY", "").replace("-", "/")}
              </text>
            )}
          </g>
        );
      })}

      {/* axis labels */}
      <text x={PAD + innerW / 2} y={H - 6} textAnchor="middle"
        fontSize={10} fill={tokens.text.tertiary}>
        Delivery score (rolling cumulative, 0 → 100%)
      </text>
      <text x={10} y={PAD + innerH / 2} textAnchor="middle"
        fontSize={10} fill={tokens.text.tertiary}
        transform={`rotate(-90, 10, ${PAD + innerH / 2})`}>
        Engagement score
      </text>

      {/* X tick labels */}
      {[0, 0.25, 0.5, 0.75, 1].map(v => (
        <text key={v} x={PAD + v * innerW} y={PAD + innerH + 14}
          textAnchor="middle" fontSize={8} fill={tokens.text.tertiary}>
          {(v * 100).toFixed(0)}%
        </text>
      ))}
    </svg>
  );
}

// ── GoalHealthBar ──────────────────────────────────────────────────────────────
function GoalHealthBar({ entry }: { entry: Entry | null }) {
  const { tokens } = useHostTheme();
  if (!entry || entry.open_trees_at_call === 0) return null;

  const open = entry.open_trees_at_call;
  const ntPct = Math.round(entry.pct_never_touched * 100);
  const stalePct = Math.round((entry.n_open_stale / open) * 100);
  const touchedPct = 100 - ntPct;

  const barColor =
    ntPct > 60 ? tokens.category.red :
    ntPct > 30 ? tokens.category.orange :
    tokens.category.green;

  const ntTone: "danger" | "warning" | "success" =
    ntPct > 60 ? "danger" : ntPct > 30 ? "warning" : "success";
  const staleTone: "warning" | "info" =
    stalePct > 50 ? "warning" : "info";

  return (
    <Stack gap={6}>
      <Row gap={20} style={{ flexWrap: "wrap" as const }}>
        <Stat label="Open goals" value={String(open)} />
        <Stat
          label="Never touched"
          value={`${entry.n_never_touched} (${ntPct}%)`}
          tone={ntTone}
        />
        <Stat
          label="Stale > 4 qtrs"
          value={`${entry.n_open_stale} (${stalePct}%)`}
          tone={staleTone}
        />
        <Stat
          label="Touched ≥ once"
          value={`${open - entry.n_never_touched} (${touchedPct}%)`}
        />
      </Row>
      <div style={{ height: 6, borderRadius: 3, background: tokens.fill.secondary, overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: `${touchedPct}%`,
          background: barColor,
          borderRadius: 3,
          transition: "width 0.3s ease",
        }} />
      </div>
      <Text tone="tertiary" size="small">
        Goal engagement health — bar shows % of open commitments touched at least once.
        Orange ring = high share of ghost (never-followed-up) commitments.
        Source: Claims Desk books.
      </Text>
    </Stack>
  );
}

// ── BreakdownCard ─────────────────────────────────────────────────────────────
function BreakdownCard({ entry }: { entry: Entry }) {
  const ntPct = Math.round(entry.pct_never_touched * 100);
  const d = entry.delivery_score;
  const e = entry.engagement_score;

  const dTone: "success" | "warning" | "danger" =
    d !== null && d >= 0.5 ? "success" : d !== null && d < 0.35 ? "danger" : "warning";
  const engTone: "success" | "danger" = e >= 0 ? "success" : "danger";
  const ntTone: "danger" | "warning" | "success" =
    ntPct > 60 ? "danger" : ntPct > 30 ? "warning" : "success";

  return (
    <Card>
      <CardHeader trailing={
        <Pill size="sm" active>{quadrantLabel(entry)}</Pill>
      }>
        {entry.ticker} · {entry.fiscal_period}
      </CardHeader>
      <CardBody>
        <Stack gap={12}>
          <Row gap={16} style={{ flexWrap: "wrap" as const }}>
            <Stat label="Delivery" value={d !== null ? `${(d * 100).toFixed(0)}%` : "—"} tone={dTone} />
            <Stat label="Engagement" value={e.toFixed(2)} tone={engTone} />
            <Stat label="Delivered / failed" value={`${entry.n_confirmed} / ${entry.n_failed}`} />
            <Stat label="Open trees" value={String(entry.open_trees_at_call)} />
          </Row>
          <Divider />
          <Row gap={16} style={{ flexWrap: "wrap" as const }}>
            <Stat label="New seeds" value={String(entry.n_new_seeds)} />
            <Stat label="Restated" value={String(entry.n_restated)} />
            <Stat label="Deferred" value={String(entry.n_deferred)} />
            <Stat label="Dropped" value={String(entry.n_dropped)} />
            <Stat label="Silent" value={String(entry.n_silent)} />
          </Row>
          <Divider />
          <Row gap={16} style={{ flexWrap: "wrap" as const }}>
            <Stat label="Never touched" value={`${entry.n_never_touched} (${ntPct}%)`} tone={ntTone} />
            <Stat label="Stale > 4 qtrs" value={String(entry.n_open_stale)} />
          </Row>
          <Text tone="secondary" size="small">
            {BOOK_LABEL[entry.book_id] ?? entry.book_id}
          </Text>
        </Stack>
      </CardBody>
    </Card>
  );
}

// ── BookPills ─────────────────────────────────────────────────────────────────
function BookPills({
  books, active, onSelect,
}: { books: string[]; active: string; onSelect: (b: string) => void }) {
  return (
    <Row gap={6}>
      <Text weight="medium">Book:</Text>
      {books.map(b => (
        <span key={b}>
          <Pill active={b === active} size="sm" onClick={() => onSelect(b)}>
            {BOOK_LABEL[b] ?? b}
          </Pill>
        </span>
      ))}
    </Row>
  );
}

// ── Company Timeline View ─────────────────────────────────────────────────────
function CompanyTimelineView({ entries }: { entries: Entry[] }) {
  const books = useMemo(() => [...new Set(entries.map(e => e.book_id))].sort(), [entries]);
  const [book, setBook] = useState(books[0] ?? "");
  const [selected, setSelected] = useState<Entry | null>(null);
  const { tokens } = useHostTheme();

  const tickers = useMemo(
    () => [...new Set(entries.filter(e => e.book_id === book).map(e => e.ticker))].sort(),
    [entries, book]
  );
  const [ticker, setTicker] = useState(tickers[0] ?? "");

  const filtered = useMemo(
    () => entries
      .filter(e => e.book_id === book && e.ticker === ticker)
      .sort((a, b) => fiscalKey(a.fiscal_period) - fiscalKey(b.fiscal_period)),
    [entries, book, ticker]
  );

  function handleBook(b: string) {
    setBook(b);
    const first = entries.filter(e => e.book_id === b).map(e => e.ticker).sort()[0] ?? "";
    setTicker(first);
    setSelected(null);
  }

  return (
    <Stack gap={16}>
      <Row gap={16} style={{ flexWrap: "wrap" as const }}>
        <BookPills books={books} active={book} onSelect={handleBook} />
        <Spacer />
        <Row gap={6} style={{ flexWrap: "wrap" as const }}>
          <Text weight="medium">Ticker:</Text>
          {tickers.map(t => (
            <span key={t}>
              <Pill active={t === ticker} size="sm"
                onClick={() => { setTicker(t); setSelected(null); }}>
                {t}
              </Pill>
            </span>
          ))}
        </Row>
      </Row>

      {filtered.length === 0 ? (
        <Text tone="tertiary">No data for this selection.</Text>
      ) : (
        <Grid columns={selected ? "auto 320px" : "1fr"} gap={16}>
          <Stack gap={12}>
            <QuadrantPlot entries={filtered} selected={selected}
              onSelect={e => setSelected(prev =>
                prev?.ticker === e.ticker && prev?.fiscal_period === e.fiscal_period ? null : e
              )}
              connectDots
            />
            <GoalHealthBar entry={selected ?? filtered[filtered.length - 1]} />
          </Stack>
          {selected && <BreakdownCard entry={selected} />}
        </Grid>
      )}
    </Stack>
  );
}

// ── Period Snapshot View ──────────────────────────────────────────────────────
function PeriodSnapshotView({ entries }: { entries: Entry[] }) {
  const books = useMemo(() => [...new Set(entries.map(e => e.book_id))].sort(), [entries]);
  const [book, setBook] = useState(books[0] ?? "");
  const [selected, setSelected] = useState<Entry | null>(null);
  const { tokens } = useHostTheme();

  const periodsForBook = useMemo(
    () => [...new Set(entries.filter(e => e.book_id === book).map(e => e.fiscal_period))]
      .sort((a, b) => fiscalKey(a) - fiscalKey(b)),
    [entries, book]
  );
  const [period, setPeriod] = useState(periodsForBook[periodsForBook.length - 1] ?? "");

  // last 8 quarters for this book
  const recentPeriods = periodsForBook.slice(-8);

  const filtered = useMemo(
    () => entries.filter(e => e.book_id === book && e.fiscal_period === period),
    [entries, book, period]
  );

  function handleBook(b: string) {
    setBook(b);
    const ps = [...new Set(entries.filter(e => e.book_id === b).map(e => e.fiscal_period))]
      .sort((a, c) => fiscalKey(a) - fiscalKey(c));
    setPeriod(ps[ps.length - 1] ?? "");
    setSelected(null);
  }

  return (
    <Stack gap={16}>
      <Row gap={16} style={{ flexWrap: "wrap" as const }}>
        <BookPills books={books} active={book} onSelect={handleBook} />
        <Spacer />
        <Row gap={6} style={{ flexWrap: "wrap" as const }}>
          <Text weight="medium">Period:</Text>
          {recentPeriods.map(p => (
            <span key={p}>
              <Pill active={p === period} size="sm"
                onClick={() => { setPeriod(p); setSelected(null); }}>
                {p.replace("FY", "")}
              </Pill>
            </span>
          ))}
        </Row>
      </Row>

      {filtered.length === 0 ? (
        <Text tone="tertiary">No data for this selection.</Text>
      ) : (
        <Grid columns={selected ? "auto 320px" : "1fr"} gap={16}>
          <Stack gap={12}>
            <QuadrantPlot entries={filtered} selected={selected}
              onSelect={e => setSelected(prev =>
                prev?.ticker === e.ticker && prev?.fiscal_period === e.fiscal_period ? null : e
              )}
            />
            <GoalHealthBar entry={selected} />
          </Stack>
          {selected && <BreakdownCard entry={selected} />}
        </Grid>
      )}
    </Stack>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function CallScorecard() {
  const [view, setView] = useState<"timeline" | "snapshot">("timeline");
  const { tokens } = useHostTheme();

  return (
    <Stack gap={20} style={{ padding: 24 }}>
      <Row gap={12}>
        <Stack gap={2}>
          <H1>Call Scorecard</H1>
          <Text tone="tertiary" size="small">
            X-axis: rolling delivery rate · Y-axis: engagement score ·
            Orange ring = high share of never-followed-up commitments
          </Text>
        </Stack>
        <Spacer />
        <Row gap={6}>
          <Pill active={view === "timeline"} size="sm" onClick={() => setView("timeline")}>
            Company Timeline
          </Pill>
          <Pill active={view === "snapshot"} size="sm" onClick={() => setView("snapshot")}>
            Period Snapshot
          </Pill>
        </Row>
      </Row>

      <Divider />

      {view === "timeline"
        ? <CompanyTimelineView entries={RAW_ENTRIES} />
        : <PeriodSnapshotView entries={RAW_ENTRIES} />
      }
    </Stack>
  );
}
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(CANVAS, encoding="utf-8")
print(f"Wrote {OUT}")
print(f"  Size: {OUT.stat().st_size:,} bytes")
