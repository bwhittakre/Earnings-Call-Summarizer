"""Write 3 Sep weekly outline, script, and Claims Desk card."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Inches, Pt, RGBColor

DESK = Path(
    r"C:\Users\BobbyWhittaker\OneDrive - Cassius Capital\Desktop"
    r"\Research Presentations"
)
NAVY = RGBColor(0x1B, 0x2A, 0x4A)
MUTED = RGBColor(0x44, 0x44, 0x44)
INK = RGBColor(0x1A, 0x1A, 0x1A)


def style_doc(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(0.85)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.font.color.rgb = MUTED
    pf = style.paragraph_format
    pf.space_after = Pt(8)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE


def add_title(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = NAVY
    run.font.name = "Calibri"


def add_h(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = NAVY
    run.font.name = "Calibri"


def add_body(doc: Document, text: str, *, ink: bool = False) -> None:
    p = doc.add_paragraph(text)
    for run in p.runs:
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.font.color.rgb = INK if ink else MUTED


def add_quote(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.italic = True
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    run.font.color.rgb = INK


def write_outline() -> Path:
    doc = Document()
    style_doc(doc)
    add_title(doc, "Roz weekly outline — 3 September 2026")
    add_body(
        doc,
        "Coverage: 27 August talk through 31 August. Healthcare claims-desk "
        "onboard treated as complete by EOD 31 August. Rank IC book is "
        "unchanged: asof, generated_at=2026-08-17T17:28:40+00:00. v1 Claims "
        "Desk split asof-path-id-17aug-book-v1, same stamp. NVIDIA gold "
        "stamp 2026-08-27T18:02:00+00:00. Ops stamp 2026-08-31T14:18:00+00:00. "
        "Healthcare desk stamp 2026-08-31T14:45:00+00:00. Not a promotion. "
        "No holdout. No healthcare Rank IC. No production_v1.",
    )
    add_h(doc, "Through-line (~12 minutes)")
    add_body(
        doc,
        "Last Thursday: one typed promise with a follow-up cite. Kept is "
        "not delivered. The bar was Autodesk Flex. Book deliver rate 1 / 1 "
        "on the locked 17 Aug book. This week: the desk grew from a row "
        "to a tree, and from one Flex example to three books on Roz. "
        "NVIDIA gold is a 20-quarter tree book, deliver 6 / 7, hit 1 / 1, "
        "cue recall 1.0. Tech and healthcare are on the same desk as "
        "first-seed books, not scored gold. Next: tighten the pull so a "
        "seedable claim is tracked until drop or completion, then deepen "
        "four names. The room picks among four refine options.",
    )
    add_h(doc, "1. Same Rank IC book (30 seconds)")
    add_body(
        doc,
        "Term-structure wow from 27 Aug still stands. Do not re-teach it. "
        "One sentence: same 17 Aug asof book, not a promotion, 0_56 is "
        "still not the typical quarter. Then move.",
    )
    add_h(doc, "2. The new object — a tree, not a row")
    add_body(
        doc,
        "v1 was one row: type, clock, state, cite, follow-up. v2 is a "
        "tree. One seed cite starts it. Later quarters are edges: "
        "restated, evolved, deferred, silent, delivered, missed, "
        "abandoned. Goals are a sibling type: hit, missed, still-want, "
        "dropped. Harden-to-promise is an edge, not a second seed. "
        "Walk may add restated or silent. Walk does not invent delivered, "
        "hit, or missed. The proposer lists leftover candidates only. "
        "It never auto-inserts a tree.",
    )
    add_h(doc, "3. Three books on Claims Trees")
    add_body(
        doc,
        "Roz page is Claims Trees at localhost:8501 — not the locked v1 "
        "Claims Desk page. Book select: nvda_gold_v2, desk_ops_v2, "
        "desk_hc_v2. Sector filter still applies after the book. "
        "v1 Claims Desk remains the Flex bar on the 17 Aug book.",
    )
    add_body(
        doc,
        "NVIDIA gold — desk_trees_v2.json, stamp 2026-08-27T18:02:00+00:00, "
        "split nvda-gold-20q-fy2022q2-fy2027q1, window FY2022-Q2 through "
        "FY2027-Q1, 33 trees, 24 promises, 9 goals. Cue recall 1.0 on "
        "18 / 18 seedable cues. Deliver 6 / 7 (85.7%). The one miss is "
        "H20 at FY2026-Q3. Hit 1 / 1. Full-history split on the same "
        "catalog is deliver 9 / 10, hit 1 / 1. v1 Flex kept + delivered "
        "still passes.",
    )
    add_body(
        doc,
        "Tech ops — desk_trees_ops_v2.json, stamp 2026-08-31T14:18:00+00:00, "
        "split tech-ops-novelty-present. 24 tech names with novelty_view. "
        "NVDA stays on gold. 23 first-seed trees across 22 tickers. "
        "APH has no first seed (Brexit watchfulness, COVID rhetoric, "
        "withdrawn guidance). Deliver — and hit — because zero typed "
        "closes. That is not a 0% keep rate.",
    )
    add_body(
        doc,
        "Healthcare — desk_trees_hc_v2.json, stamp 2026-08-31T14:45:00+00:00, "
        "split hc-ops-novelty-present. All 20 healthcare large-cap names "
        "are on the claims desk as of EOD 31 August. 20 first-seed trees, "
        "one per name. Deliver — and hit —. Not a Rank IC. Not mixed "
        "into gold. production_v1 frozen.",
    )
    add_h(doc, "4. What the page can do now")
    add_body(
        doc,
        "Due and slipped board. Slipped = silent plus a due clock, not "
        "missed on the tree. Open trees with no clock are someday wants.",
    )
    add_body(
        doc,
        "Quote table: seed / change / close, filterable, excerpt from "
        "novelty_view. Silent edges are omitted.",
    )
    add_body(
        doc,
        "Horizon keep rate: quarterly and cumulative. Cohort is due this "
        "quarter. Slipped counts as a miss for this series only. Tree "
        "delivery stays unresolved. Clock-length filter 1Q / 2Q / 4Q / all. "
        "Names are horizon_quarter_* and horizon_cum_*. Not desk_trust / "
        "desk_ambition. Those stay on the locked NVIDIA sidecar.",
    )
    add_h(doc, "5. Tighten the pull — immediate next")
    add_body(
        doc,
        "The desk now holds 44 names. The pull does not. NVIDIA gold "
        "covered 31 / 31 seedable cues. Ops leftover cover is 22 / 632 "
        "(3.5%). Healthcare leftover cover is 20 / 660 (3.0%). Cognizant, "
        "Lilly, Pfizer, UnitedHealth still dump 40–48 leftovers each. "
        "Those are not 1,250 missing trees. Most are guidance, rhetoric, "
        "or “we will not comment further.”",
        ink=True,
    )
    add_body(
        doc,
        "Tighten the reject / guidance net so a leftover list is a short "
        "typed worklist. Every sentence that survives as seedable gets a "
        "tree and is tracked until a typed terminal: delivered, missed, "
        "hit, dropped, or abandoned. Walk still does not invent those "
        "terminals. The proposer still does not auto-insert. Nothing "
        "seedable slips through as an untracked leftover.",
    )
    add_h(doc, "6. Four options for what to refine next")
    add_body(
        doc,
        "A — Honest desk. Stop presenting ops and healthcare as scored "
        "books. Hide or footnote em-dash deliver / hit. Hide NVIDIA-only "
        "trailing credibility on the other books. Couple Book to Sector "
        "so healthcare is not empty behind xlk_tech. Cheap. Should ride "
        "with whatever else we pick.",
    )
    add_body(
        doc,
        "B — Tighten the pull. The leftover cull above. This is the "
        "operational bar: nothing seedable slips through, and every "
        "accepted claim is tracked until drop or completion.",
    )
    add_body(
        doc,
        "C — Depth cohort. Walk and type closes on MSFT, CRM, LLY, ISRG. "
        "Cite-only. Staged 31 August and paused. First candidate is "
        "Intuitive da Vinci X (FY2017-Q2: 11 X systems and first clinical "
        "use, inside the FY2017-Q4 clock). Salesforce $20B is a hit "
        "candidate at FY2021-Q4, not at the FY2021-Q1 guide. Lilly’s "
        "December 2016 dividend clock has no novelty cite through "
        "FY2017-Q2. Microsoft BUILD briefing has no novelty cite in the "
        "clock window — do not invent delivered.",
    )
    add_body(
        doc,
        "D — Deploy polish. Shareable HTML for walked names. Roz "
        "recreate-on-compose so a stale container cannot hide books. "
        "Image bake when the pip hash block clears. Looks finished. "
        "Still zero scored closes outside NVIDIA if done alone.",
    )
    add_body(
        doc,
        "Recommendation to the room: B then C. A rides along. D last. "
        "Do not type another first seed on every leftover name.",
        ink=True,
    )
    add_h(doc, "7. Do not say")
    add_body(
        doc,
        "“Ops keep-rate is 0%.” “Healthcare keep-rate is 0%.” "
        "Healthcare Rank IC. “All twenty healthcare names are scored "
        "gold.” Kept means delivered. Horizon slip-miss means the tree "
        "is missed. Path ID as the verdict. The remaining 125. A new "
        "LLM. transcripts_raw. Healthcare or ops trees written into "
        "desk_trees_v2.json. Promotion of production_v1. Depth cohort "
        "already closed. Autodesk Flex undone.",
    )
    add_h(doc, "8. Order")
    add_body(
        doc,
        "Same Rank IC book / not a promotion → tree not row → three "
        "books and gold 6 / 7 → tech and healthcare first seeds → "
        "quotes, horizon, slipped ≠ missed → tighten the pull → four "
        "options, recommend B then C → questions.",
    )
    dest = DESK / "Roz_Weekly_Presentation_Outline_2026-09-03.docx"
    doc.save(dest)
    return dest


def write_script() -> Path:
    doc = Document()
    style_doc(doc)
    add_title(doc, "Roz weekly script — 3 September 2026")
    add_body(
        doc,
        "Read this. Do not invent a healthcare Rank IC. Do not call "
        "first-seed books scored.",
    )
    add_h(doc, "Open")
    add_body(
        doc,
        "Same Rank IC book as 27 August. asof, generated at 17 August "
        "2026, 17:28:40 UTC. I am not promoting anything. Last Thursday "
        "I showed you one typed promise with a follow-up cite. Autodesk "
        "Flex. Kept is not delivered. That bar is still green. This week "
        "is the claims desk since then.",
    )
    add_h(doc, "From a row to a tree")
    add_body(
        doc,
        "A Rank IC ranks a quarter. The v1 desk asked whether one object "
        "came back next quarter. That is not enough. We now start a tree "
        "from one seed cite. Later quarters are edges. They restated it, "
        "changed it, went silent, or closed it. Goals are a sibling type: "
        "hit, still-want, dropped. The walker may mark silent or restated. "
        "It is not allowed to invent delivered, hit, or missed. The "
        "proposer can point at leftover sentences. It cannot insert a tree.",
    )
    add_h(doc, "Three books, one page")
    add_body(
        doc,
        "In Roz, open Claims Trees. Not the old Claims Desk page. You "
        "will see a Book control. NVIDIA gold. Tech ops. Healthcare. "
        "They are separate files on purpose. Healthcare does not go into "
        "the NVIDIA gold file. Tech ops does not rewrite gold.",
    )
    add_body(
        doc,
        "NVIDIA gold is locked. Twenty consecutive scored fiscal "
        "quarters, FY2022 Q2 through FY2027 Q1. Stamp 27 August, 18:02 "
        "UTC. Thirty-three trees. Cue recall is one hundred percent on "
        "eighteen seedable cues. Deliver rate is six over seven. The one "
        "miss is H20 in FY2026 Q3. Goal hit rate is one over one. On the "
        "longer full-history split, deliver is nine over ten. Flex on the "
        "v1 book is still kept and delivered. Path ID is still not the "
        "verdict.",
    )
    add_body(
        doc,
        "Tech ops is the twenty-four names that already have a novelty "
        "view. NVIDIA stays on gold. The other twenty-three got a first "
        "seed where one existed. Twenty-three trees, twenty-two tickers. "
        "Amphenol has no first seed yet, and that is correct: the leftovers "
        "are watchfulness and withdrawn guidance. Deliver rate on this book "
        "is an em dash. Zero typed closes. That is not zero percent.",
    )
    add_body(
        doc,
        "Healthcare is on the desk as of end of day 31 August. All twenty "
        "large-cap names. Twenty first-seed trees, one each. Same rule: "
        "em dash, not zero. This is not a healthcare Rank IC. The 17 August "
        "tech book was not rewritten. production_v1 is frozen.",
    )
    add_h(doc, "What you can see on the page")
    add_body(
        doc,
        "Due and slipped. Slipped means the clock is due and the later "
        "quarter was silent. That is not a miss on the tree. A miss is a "
        "typed close with a cite.",
    )
    add_body(
        doc,
        "A quote table: the seed sentence, later changes, and closes. You "
        "can filter those. Silent quarters are not quotes.",
    )
    add_body(
        doc,
        "A horizon keep rate, quarterly and cumulative. The cohort is "
        "claims due that quarter. If it slipped, the horizon series counts "
        "a miss. The tree itself stays unresolved until someone types a "
        "close. That series is not desk trust and not desk ambition. Those "
        "two stay on the locked NVIDIA sidecar.",
    )
    add_h(doc, "Tighten the pull")
    add_body(
        doc,
        "This is the operational hole. NVIDIA gold covered every seedable "
        "cue. Tech leftovers are six hundred ten after twenty-two covered "
        "cues, out of six hundred thirty-two seedable. Healthcare is six "
        "hundred forty leftover out of six hundred sixty. Cognizant, Lilly, "
        "Pfizer, UnitedHealth still dump the mid-forties. I am not going "
        "to type twelve hundred trees. Most of those sentences are "
        "guidance or “we will not comment further.”",
    )
    add_body(
        doc,
        "The next bar is: tighten what we pull, so a leftover list is a "
        "short worklist. Anything that survives as a real promise or goal "
        "gets a tree. That tree stays open until a typed drop or a typed "
        "completion. The walker does not invent the ending. The proposer "
        "does not insert the start. Nothing seedable sits in a dump and "
        "quietly ages out.",
    )
    add_h(doc, "Four options")
    add_body(
        doc,
        "I want a decision on what we refine next. Four options.",
    )
    add_body(
        doc,
        "A. Honest desk. Stop showing an em dash next to gold’s eighty-six "
        "percent as if tech and healthcare already have a keep rate. Couple "
        "the book picker to the sector filter. Cheap. Should ride along.",
    )
    add_body(
        doc,
        "B. Tighten the pull. The leftover cull I just described. This is "
        "the one that keeps claims from slipping through.",
    )
    add_body(
        doc,
        "C. Depth. Four names, not forty-four. Microsoft, Salesforce, Lilly, "
        "Intuitive. Walk them and type closes from cites only. We staged "
        "that on 31 August and paused it. Intuitive is the first file: da "
        "Vinci X, systems and clinical use in the next quarter, inside the "
        "clock. Salesforce over twenty billion is a later hit candidate, "
        "not the COVID-year guide. Lilly and Microsoft do not yet have a "
        "clock-window cite that closes them. I will not invent those.",
    )
    add_body(
        doc,
        "D. Deploy polish. Shareable HTML, keep Roz from going stale, bake "
        "the image when the hash block clears. That makes the page look "
        "finished. It does not create a scored name outside NVIDIA.",
    )
    add_body(
        doc,
        "My recommendation is B, then C. A comes for free. D last. I will "
        "not spend the next pass adding a first seed to every leftover name.",
    )
    add_h(doc, "Close")
    add_body(
        doc,
        "If you want to see it: Roz, Claims Trees, Book. Gold first, then "
        "ops, then healthcare. Flex is still on the old Claims Desk page "
        "if you want the 27 August bar. Questions.",
    )
    dest = DESK / "Roz_Weekly_Presentation_Script_2026-09-03.docx"
    doc.save(dest)
    return dest


def write_card() -> Path:
    doc = Document()
    style_doc(doc)
    add_title(doc, "Claims Desk — talking card — 3 September 2026")
    add_body(
        doc,
        "v1 locked book generated_at=2026-08-17T17:28:40+00:00, split "
        "asof-path-id-17aug-book-v1. Demo v1: http://localhost:8501/Claims_Desk. "
        "v2 demo: http://localhost:8501 → Claims Trees. "
        "Gold stamp 2026-08-27T18:02:00+00:00. "
        "Ops stamp 2026-08-31T14:18:00+00:00. "
        "Healthcare stamp 2026-08-31T14:45:00+00:00.",
    )
    add_h(doc, "Say these definitions once")
    add_body(
        doc,
        "Tree — one seed cite, then edges. Not a one-row follow-up. "
        "Walk may add restated or silent. Walk does not invent delivered, "
        "hit, or missed.",
        ink=True,
    )
    add_body(
        doc,
        "Promise vs goal — delivered / missed / abandoned versus hit / "
        "missed / still-want / dropped. Harden-to-promise is an edge.",
        ink=True,
    )
    add_body(
        doc,
        "Kept (v1) — the same object came back. Not delivered.",
        ink=True,
    )
    add_body(
        doc,
        "Slipped — silent plus a due clock. Not missed on the tree. "
        "Horizon series may count it as a miss. Tree delivery stays "
        "unresolved.",
        ink=True,
    )
    add_body(
        doc,
        "Deliver / hit rate — scored terminals only. Unresolved is an "
        "em dash, not 0%.",
        ink=True,
    )
    add_h(doc, "Quote these")
    add_body(
        doc,
        "v1 Flex bar unchanged: ADSK FY2022-Q2 launch, FY2022-Q3 live "
        "usage mix. Kept and delivered. Path ID miss. Path ID is not "
        "the verdict. Book deliver 1 / 1 on the 17 Aug book.",
    )
    add_body(
        doc,
        "NVIDIA gold: 33 trees (24 promises, 9 goals). Cue recall 1.0 "
        "on 18 / 18. Deliver 6 / 7 (H20 miss FY2026-Q3). Hit 1 / 1. "
        "Window FY2022-Q2–FY2027-Q1. Full-history deliver 9 / 10.",
    )
    add_body(
        doc,
        "Tech ops: 24 names scanned, 23 trees, 22 tickers, APH none. "
        "Deliver — / —. Leftover cover 22 / 632.",
    )
    add_body(
        doc,
        "Healthcare: 20 / 20 names onboarded EOD 31 August. 20 first-seed "
        "trees. Deliver — / —. Leftover cover 20 / 660. Not a Rank IC.",
    )
    add_h(doc, "Flex — still the v1 bar")
    add_body(doc, "Seed — ADSK FY2022-Q2 · novelty_view · competitive_position · verbatim")
    add_quote(
        doc,
        "At the end of September, we will launch a new pay-as-you-go "
        "consumption model, called Flex. It matches the customer's cost "
        "with their usage.",
    )
    add_body(doc, "Follow-up — ADSK FY2022-Q3 · novelty_view · competitive_position · composite")
    add_quote(
        doc,
        "One of the things we're seeing with Flex is exactly what we "
        "expected to see. We're seeing a large percent of Flex business "
        "coming in is net new.",
    )
    add_h(doc, "Gold miss — why 6 / 7")
    add_body(
        doc,
        "H20 harden-from-China-want. Clock FY2026-Q3. Typed missed. "
        "That is the only scored gold miss on the 20Q window. Do not "
        "round this to 100%.",
    )
    add_h(doc, "Four options (recommend B then C)")
    add_body(doc, "A — Honest desk. Em-dash rates, Book coupled to Sector.")
    add_body(
        doc,
        "B — Tighten the pull. Reject / guidance net. Seedable claims "
        "tracked until drop or completion. No auto-insert.",
    )
    add_body(
        doc,
        "C — Depth: MSFT, CRM, LLY, ISRG. Paused. First file ISRG da Vinci X.",
    )
    add_body(doc, "D — Deploy polish last. HTML, Roz recreate, image bake.")
    add_h(doc, "Do not say")
    add_body(
        doc,
        "Ops or healthcare keep-rate 0%. Healthcare Rank IC. All twenty "
        "healthcare names are gold. Kept means delivered. Horizon slip "
        "means the tree missed. Path ID as the desk verdict. The remaining "
        "125. A new LLM. transcripts_raw. Mixing books. production_v1. "
        "Depth already done. Flex undone.",
    )
    dest = DESK / "Roz_Claims_Desk_Talking_Card_2026-09-03.docx"
    doc.save(dest)
    return dest


def main() -> int:
    DESK.mkdir(parents=True, exist_ok=True)
    paths = [write_outline(), write_script(), write_card()]
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
