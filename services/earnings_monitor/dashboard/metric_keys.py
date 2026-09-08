"""Collapsible metric key / legend renderer for every Roz dashboard page.

Usage:
    from .metric_keys import render_page_key
    render_page_key(st, "overview")          # top of render_overview
    render_page_key(st, "claims_desk")       # top of 4_Claims_Trees.py
    render_page_key(st, "regimes")           # top of 5_Management_Regimes.py
    render_page_key(st, "post_call_brief")   # top of 6_Post_Call_Brief.py
    render_page_key(st, "company_history")   # top of render_company_history
"""
from __future__ import annotations

from typing import Any


# ── Key definitions ──────────────────────────────────────────────────────────

_SCORECARD_QUADRANTS = """
| Quadrant | Delivery | Transparency | Interpretation |
|---|---|---|---|
| Credible & Committed | High (≥50%) | High (≥0.3) | Delivering and openly discussing commitments — best quadrant |
| Aspirational | Low (<50%) | High (≥0.3) | Talking openly but hasn't delivered yet |
| Quietly Delivering | High (≥50%) | Low (<0.3) | Results without much public commitment; watch for fade |
| Retreating | Low (<50%) | Low (<0.3) | Missing goals and going silent — most cautionary |
"""

_CLOCK_SEMANTICS = """
| Status | Meaning |
|---|---|
| `open` | Promise is active and within its expected horizon |
| `due` | Horizon reached; not yet resolved |
| `slipped` | Horizon passed without resolution — counted as failed in that expiration quarter |
| `delivered` | Closed with a confirmed outcome |
| `failed` | Explicitly closed as unmet |
"""

_PAGES: dict[str, str] = {
    "overview": f"""
| Metric | Definition | Source |
|---|---|---|
| `narrative_level` | AI-scored forward-looking tone of the earnings call (−3 to +3) | `narrative_scorer.py` |
| `narrative_change` | Δ narrative level vs prior quarter | Derived |
| `quant_z` | Surprise z-score: (actual − consensus) / σ, clipped to ±2 for charts | `quant_metrics.py` |
| `surprise_quant_gap` | Narrative surprise minus quant z — positive = talk > numbers | Derived |
| `divergences` | Count of dimension-level narrative / quant divergences | `dimension_scorer.py` |
| `deliver_rate` | Fraction of scored open trees resolved as delivered | Claims desk |
    | `transparency_score` | Fraction of open goals management discussed this call (0=silent, 1=fully addressed) | `_desk_call_scorecard.py` |

### Scorecard quadrants
{_SCORECARD_QUADRANTS}
""",

    "company_history": f"""
| Metric | Definition | Source |
|---|---|---|
| `fiscal_period` | Quarter label (e.g. FY2024Q3) | Roz overlay |
| `delivery_score` | Per-call percentage of open goals delivered (scored vs expiry cohort) | Scorecard sidecar |
| `narrative_level` | Forward-looking tone (−3 to +3) | Narrative scorer |
| `narrative_change` | Δ vs prior quarter | Derived |
| `quant_z` | EPS/revenue surprise z-score | Quant metrics |
| `surprise_quant_gap` | Narrative tone minus quant surprise — positive = talks better than numbers | Derived |
| `divergences` | Dimension-level narrative / quant divergences | Dimension scorer |
| `dimensions` | Number of business dimensions covered | Dimension scorer |
| `quant_ok` | False if quant consensus was too thin for a reliable z-score | Quant QA |
| `quant_flags` | Specific quant quality issues (e.g. suppressed member, near-zero consensus) | Quant QA |
""",

    "claims_desk": f"""
| Metric | Definition | Source |
|---|---|---|
| `deliver_rate` | Delivered / scoreable seeds for this company/book | `_desk_seed_batch.py` |
| `delivered` | Count of trees closed as delivered | Claims desk |
| `scored` | Count of scoreable trees (those with a terminal attempt) | Claims desk |
| `materiality` | Importance weight assigned to a seed (1–5); higher = more weight in deliver rate | Seed overlay |
    | `transparency_score` | Fraction of open goals management discussed this call (0=silent, 1=fully addressed) | `_desk_call_scorecard.py` |
| `delivery_score` | Fraction of open goals resolved as delivered in the call's expiry cohort | Scorecard sidecar |
| `desk_trust` | Aggregate seed quality signal (proportion high-confidence seeds) | Seed overlay |
| `n_never_touched` | Goals seeded but never mentioned in any subsequent call | Scorecard sidecar |
| `n_open_stale` | Goals open and untouched for >4 quarters | Scorecard sidecar |

### Clock status
{_CLOCK_SEMANTICS}

### Scorecard quadrants
{_SCORECARD_QUADRANTS}
""",

    "regimes": """
| Metric | Definition | Source |
|---|---|---|
| `regime` | CEO tenure: name + start date | `config/management_regimes.json` |
| `transfer_kind` | How a tree crossed a CEO transition: `inherited` (open at handoff), `opened_after` (started in new regime) | Regime sidecar |
| `cite_count` | Number of transcript citations under this regime | Regime sidecar |
| `regime_deliver_rate` | Deliver rate for trees attributed to this regime | Regime sidecar |

**Transfer Ledger** shows only trees that were *inherited* across a CEO change (prior-regime trees that were still open when the new CEO took over). Trees closed before the transition are excluded.
""",

    "post_call_brief": f"""
| Metric | Definition | Source |
|---|---|---|
| `delivery_score` | Fraction of open goals resolved as delivered in the expiry cohort for this call | Scorecard sidecar |
    | `transparency_score` | Fraction of open goals management discussed this call (0=silent, 1=fully addressed) | `_desk_call_scorecard.py` |
| `n_never_touched` | Goals seeded but never re-mentioned across any subsequent call | Scorecard sidecar |
| `n_open_stale` | Goals open and silent for >4 quarters | Scorecard sidecar |
| `regime` | Sitting CEO at call date | `config/management_regimes.json` |
| `deliver_rate` | Full-book deliver rate for this company | Claims desk |
| `materiality` | Importance weight on a specific promise (1–5) | Seed overlay |

### Scorecard quadrants
{_SCORECARD_QUADRANTS}

### Clock status
{_CLOCK_SEMANTICS}
""",
}


# ── Public API ────────────────────────────────────────────────────────────────

def render_page_key(st: Any, page: str) -> None:
    """Render a collapsible "Key & Definitions" expander at the top of a page.

    Args:
        st: The Streamlit module (passed in so this file has no direct `import streamlit`).
        page: One of "overview", "company_history", "claims_desk",
              "regimes", "post_call_brief".
    """
    content = _PAGES.get(page)
    if not content:
        return
    with st.expander("📖  Key & Definitions", expanded=False):
        st.markdown(content)
