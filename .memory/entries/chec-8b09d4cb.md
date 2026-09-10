---
id: chec-8b09d4cb
type: checkpoint
project: earnings-call-summarizer
parent_id: deci-79367e4b
title: DDOG + LITE Independent case study onboarded
node_label: DDOG + LITE Independent case study onboarded
tags: onboard,independent,ddog,lite,case-study
status: active
open_threads: 2
success: 'null'
files: ''
session_id: sess-270c207b
created_at: '2026-09-09T17:48:01.350774+00:00'
updated_at: '2026-09-09T19:15:04.777338+00:00'
results: '[{"metric": "ddog_earnings_transcripts", "value": 28, "split": "DDOG", "window":
  "FY2019-Q3-through-FY2026-Q2", "source": "data/case_study_pull/inventory.json"},
  {"metric": "ddog_conference_transcripts", "value": 37, "split": "DDOG", "window":
  "2019-through-2026-09-08", "source": "data/conf_transcripts/DDOG"}, {"metric": "ddog_overlay_trees",
  "value": 8, "split": "DDOG desk_hc_v2", "criterion": "7 confirmed, 1 provisional",
  "source": "data/desk_catalog_overlay/hc.json after FY2026-Q2 onboard"}, {"metric":
  "lite_earnings_transcripts", "value": 31, "split": "LITE", "window": "FY2019-Q1-through-FY2026-Q4",
  "source": "inventory.json"}, {"metric": "lite_conference_transcripts", "value":
  26, "split": "LITE", "window": "2022-03-08-through-2026-08-27", "source": "data/conf_transcripts/LITE"},
  {"metric": "lite_overlay_trees_confirmed", "value": 6, "split": "LITE desk_hc_v2",
  "window": "FY2026-Q4 onboard", "criterion": "8 proposed, 2 recite", "source": "onboard
  desk_autopilot step"}]'
---
Independent case study for the 10 AM talk is on disk.

DDOG (Datadog, ISIN US23804L1035, companyId 6106): first transcript 2019-11-12. 28 earnings + 37 conference transcripts. FY onboard FY2026-Q2 completed with narrative + PIT quant (28 quarters, 1904 measure rows). Feature panel 32 rows. Overlay 8 trees (7 confirmed, 1 provisional). XLK Rank IC not rewritten. History parquet includes DDOG (7516 then 7750 after LITE).

LITE (Lumentum, ISIN US55024U1097, companyId 6193): first transcript 2018-11-01 (no transcripts FY2016-2018). 31 earnings + 26 conference transcripts. Missing FY2021-Q2 in Quartr. FY onboard FY2026-Q4 completed. Extractor 45 quarters / 3060 rows. Feature panel 232 rows. Overlay 6 confirmed seeds (8 proposed, 2 recite). 26 conferences ingested.

Both `--research-sector independent`, industry_group=tech. Delivery on first-seed trees is unresolved — do not quote the auto-brief 0%.

One-pager: Desktop/Research Presentations/Roz_Independent_Case_Study_DDOG_LITE_2026-09-09.docx. Slide 5/7 paste: documents/260910_slide57_paste.md.
