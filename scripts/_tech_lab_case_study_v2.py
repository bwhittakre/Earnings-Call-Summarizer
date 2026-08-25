"""Tech Lab v2: natural atlas + eight-chapter hypotheses vs named baselines.

Does not fit weights. Pre-registered in .memory/entries/expe-tech-lab-v2.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.company_lists import load_sector_companies  # noqa: E402
from services.earnings_monitor.dashboard.lab_store import (  # noqa: E402
    load_lab_store,
    save_lab_store,
    universe_key,
    upsert_recipe,
)
from services.earnings_monitor.dashboard.rank_ic_lab import (  # noqa: E402
    blend_company_period,
)
from services.earnings_monitor.dashboard.rank_ic_research import (  # noqa: E402
    _rank_ic_html,
    _spearman,
)
from services.earnings_monitor.dashboard.research_data import (  # noqa: E402
    load_rank_ic_bundle,
)
from services.earnings_monitor.dashboard.sectors import ALL_COMPANIES  # noqa: E402

LABEL = "asof"
HORIZON = "0_56"
ATLAS_UNIVERSES = (
    "all",
    "semis_cycle",
    "software_cloud",
    "designers",
    "equipment",
    "mega_inbook",
    "software_pure",
)
ATLAS_DIMENSIONS = (
    "demand",
    "margins",
    "earnings_power",
    "capital_allocation",
    "guidance",
    "management_confidence",
    "competitive_position",
    "macro_regulatory_risk",
)
ATLAS_SIGNALS = (
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "agrees_with_quant",
)

# role: primary counts toward chapter hold; ablation/control/reference do not.
HYPOTHESES: list[dict] = [
    # --- Ch1 share-shift (competitive_position; novelty exists) ---
    {
        "id": "C1_P_semis",
        "chapter": "share_shift",
        "role": "primary",
        "title": "Share-shift in the semi cycle",
        "story": "H4 should replicate where share actually moves: designers + equipment.",
        "universe": "semis_cycle",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_P_software",
        "chapter": "share_shift",
        "role": "primary",
        "title": "Share-shift in software",
        "story": "If H4 is a tech-book fact, it should also hold in duration software.",
        "universe": "software_cloud",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_P_designers",
        "chapter": "share_shift",
        "role": "primary",
        "title": "Share-shift among chip designers",
        "story": "The priced object in NVDA/AMD/AVGO/MU/ADI/TXN is who took share this quarter.",
        "universe": "designers",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_h4_all",
        "chapter": "share_shift",
        "role": "reference",
        "title": "H4 reference on the full book",
        "story": "v1 winner, locked. Not confirmatory.",
        "universe": "all",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_novelty_all",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Competitive novelty alone, full book",
        "story": "Is the H4 edge novelty, or does it need the change overlay?",
        "universe": "all",
        "dimension": "competitive_position",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_change_all",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Competitive change alone, full book",
        "story": "Sequential share-shift without the novelty tag.",
        "universe": "all",
        "dimension": "competitive_position",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_novelty_semis",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Competitive novelty alone, semis",
        "story": "Ablate the semi primary.",
        "universe": "semis_cycle",
        "dimension": "competitive_position",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_change_semis",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Competitive change alone, semis",
        "story": "Ablate the semi primary.",
        "universe": "semis_cycle",
        "dimension": "competitive_position",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_novelty_software",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Competitive novelty alone, software",
        "story": "Ablate the software primary.",
        "universe": "software_cloud",
        "dimension": "competitive_position",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_nov_level_all",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Novelty plus standing moat",
        "story": "Keep the moat and add novelty — the conservative H4 cousin.",
        "universe": "all",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "llm_level": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_equipment",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Share-shift in equipment",
        "story": "WFE share is a cycle tell, but the sleeve is only four names.",
        "universe": "equipment",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_mega",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Share-shift in mega-cap",
        "story": "AAPL/AMZN/MSFT/NVDA — thin cross-section, still min 3.",
        "universe": "mega_inbook",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C1_A_software_pure",
        "chapter": "share_shift",
        "role": "ablation",
        "title": "Share-shift in software without IBM",
        "story": "IBM may be a services residual in the software sleeve.",
        "universe": "software_pure",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    # --- Ch2 cheap talk (management_confidence) ---
    {
        "id": "C2_P_all",
        "chapter": "cheap_talk",
        "role": "primary",
        "title": "Confidence is the level, full book",
        "story": "Cheap talk is priced as the standing tone, not the delta.",
        "universe": "all",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "change_magnitude",
    },
    {
        "id": "C2_P_semis",
        "chapter": "cheap_talk",
        "role": "primary",
        "title": "Confidence is the level, semis",
        "story": "Same cheap-talk claim inside the cycle sleeve.",
        "universe": "semis_cycle",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "change_magnitude",
    },
    {
        "id": "C2_P_software",
        "chapter": "cheap_talk",
        "role": "primary",
        "title": "Confidence is the level, software",
        "story": "Duration software should be even more of a tone tape.",
        "universe": "software_cloud",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "change_magnitude",
    },
    {
        "id": "C2_A_h7_all",
        "chapter": "cheap_talk",
        "role": "reference",
        "title": "H7 reference: change overlay",
        "story": "v1 loser, locked. Not confirmatory.",
        "universe": "all",
        "dimension": "management_confidence",
        "mode": "blend",
        "weights": {"change_magnitude": 2, "llm_level": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C2_A_novelty_all",
        "chapter": "cheap_talk",
        "role": "ablation",
        "title": "Confidence novelty vs level",
        "story": "New language about conviction, not a change in the score.",
        "universe": "all",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C2_A_nov_level_all",
        "chapter": "cheap_talk",
        "role": "ablation",
        "title": "Confidence novelty plus level",
        "story": "The incremental-tell overlay that H3 wanted, on a dim that has novelty.",
        "universe": "all",
        "dimension": "management_confidence",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "llm_level": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C2_A_mega",
        "chapter": "cheap_talk",
        "role": "ablation",
        "title": "Confidence is the level, mega-cap",
        "story": "Mega-cap calls are a tone event.",
        "universe": "mega_inbook",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "change_magnitude",
    },
    {
        "id": "C2_A_designers",
        "chapter": "cheap_talk",
        "role": "ablation",
        "title": "Confidence is the level, designers",
        "story": "Designer calls are also a tone event — or they are a share event.",
        "universe": "designers",
        "dimension": "management_confidence",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "change_magnitude",
    },
    # --- Ch3 semi cycle ---
    {
        "id": "C3_P_demand_quant_vs_surprise",
        "chapter": "semi_cycle",
        "role": "primary",
        "title": "Semi demand is already in the print",
        "story": "Street demand quant should beat narrative surprise in the cycle sleeve.",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "surprise_magnitude",
    },
    {
        "id": "C3_P_margins_quant_vs_level",
        "chapter": "semi_cycle",
        "role": "primary",
        "title": "Semi margins are a print",
        "story": "Utilization / gross-margin prints should beat margin tone.",
        "universe": "semis_cycle",
        "dimension": "margins",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C3_P_eps_quant_vs_level",
        "chapter": "semi_cycle",
        "role": "primary",
        "title": "Semi earnings power is a print",
        "story": "Operating leverage in semis is in EPS, not the commentary.",
        "universe": "semis_cycle",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C3_A_h1",
        "chapter": "semi_cycle",
        "role": "reference",
        "title": "H1 reference: surprise plus change",
        "story": "v1 loser, locked.",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "blend",
        "weights": {"surprise_magnitude": 2, "change_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C3_A_demand_level_vs_quant",
        "chapter": "semi_cycle",
        "role": "ablation",
        "title": "Semi demand tone vs print",
        "story": "Flip of the primary — does tone ever beat the print here?",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C3_A_demand_change_vs_quant",
        "chapter": "semi_cycle",
        "role": "ablation",
        "title": "Semi demand change vs print",
        "story": "Sequential demand change as the cycle tell.",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C3_A_demand_level_plus_quant",
        "chapter": "semi_cycle",
        "role": "ablation",
        "title": "Semi demand tone plus print",
        "story": "Does adding tone to the print help?",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "llm_level": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C3_A_guidance_level_vs_surprise",
        "chapter": "semi_cycle",
        "role": "ablation",
        "title": "Semi guidance tone vs surprise",
        "story": "Outlook tone versus the surprise in that tone.",
        "universe": "semis_cycle",
        "dimension": "guidance",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "surprise_magnitude",
    },
    {
        "id": "C3_A_eps_surprise_vs_quant",
        "chapter": "semi_cycle",
        "role": "ablation",
        "title": "Semi EPS surprise vs print",
        "story": "Narrative earnings surprise against the z-print.",
        "universe": "semis_cycle",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"surprise_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    # --- Ch4 software duration ---
    {
        "id": "C4_P_guidance_level_vs_surprise",
        "chapter": "software_duration",
        "role": "primary",
        "title": "Software guidance is the standing outlook",
        "story": "Duration tape: the level of next-year tone, not the surprise in it.",
        "universe": "software_cloud",
        "dimension": "guidance",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "surprise_magnitude",
    },
    {
        "id": "C4_P_demand_quant_vs_level",
        "chapter": "software_duration",
        "role": "primary",
        "title": "Software demand is still a print",
        "story": "Even in software, current-quarter demand is in the number.",
        "universe": "software_cloud",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C4_A_h2",
        "chapter": "software_duration",
        "role": "reference",
        "title": "H2 reference: level plus surprise",
        "story": "v1 loser (revision was empty). Not confirmatory.",
        "universe": "software_cloud",
        "dimension": "guidance",
        "mode": "blend",
        "weights": {"llm_level": 1, "surprise_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C4_A_guidance_change_vs_level",
        "chapter": "software_duration",
        "role": "ablation",
        "title": "Software guidance change vs tone",
        "story": "Sequential outlook change as the duration tell.",
        "universe": "software_cloud",
        "dimension": "guidance",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C4_A_guidance_pure",
        "chapter": "software_duration",
        "role": "ablation",
        "title": "Software-pure guidance level vs surprise",
        "story": "Drop IBM from the software sleeve.",
        "universe": "software_pure",
        "dimension": "guidance",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "surprise_magnitude",
    },
    {
        "id": "C4_A_margins_level_vs_quant",
        "chapter": "software_duration",
        "role": "ablation",
        "title": "Software margin tone vs print",
        "story": "v1 H5 quant was terrible — is tone the less-bad object?",
        "universe": "software_cloud",
        "dimension": "margins",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C4_A_margins_agrees_vs_quant",
        "chapter": "software_duration",
        "role": "ablation",
        "title": "Software margin agreement vs print",
        "story": "Confirmation alone, without mixing in tone.",
        "universe": "software_cloud",
        "dimension": "margins",
        "mode": "natural",
        "weights": {"agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C4_A_h5",
        "chapter": "software_duration",
        "role": "reference",
        "title": "H5 reference: agrees plus level",
        "story": "v1 less-bad negative. Not confirmatory.",
        "universe": "software_cloud",
        "dimension": "margins",
        "mode": "blend",
        "weights": {"agrees_with_quant": 2, "llm_level": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C4_A_eps_quant_vs_level",
        "chapter": "software_duration",
        "role": "ablation",
        "title": "Software EPS print vs tone",
        "story": "Earnings-power print in the duration sleeve.",
        "universe": "software_cloud",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    # --- Ch5 investment cycle (no novelty on this dim) ---
    {
        "id": "C5_P_change_vs_level",
        "chapter": "investment_cycle",
        "role": "primary",
        "title": "AI capex is a change in spend, not the run-rate",
        "story": "H3 novelty was absent. The incremental tell has to be change.",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_P_surprise_vs_level",
        "chapter": "investment_cycle",
        "role": "primary",
        "title": "AI capex is a spend surprise",
        "story": "The other incremental object: surprise versus run-rate tone.",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"surprise_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_quant_vs_level",
        "chapter": "investment_cycle",
        "role": "ablation",
        "title": "Capex print vs tone, full book",
        "story": "Is the investment cycle already in the capex z?",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_change_semis",
        "chapter": "investment_cycle",
        "role": "ablation",
        "title": "Capex change vs tone, semis",
        "story": "Foundry / WFE spend commentary in the cycle sleeve.",
        "universe": "semis_cycle",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_change_mega",
        "chapter": "investment_cycle",
        "role": "ablation",
        "title": "Capex change vs tone, mega-cap",
        "story": "The hyperscaler spend tape is four names.",
        "universe": "mega_inbook",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_change_plus_level",
        "chapter": "investment_cycle",
        "role": "ablation",
        "title": "Capex change plus run-rate",
        "story": "Blend version of the primary.",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "blend",
        "weights": {"change_magnitude": 2, "llm_level": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_quant_plus_level",
        "chapter": "investment_cycle",
        "role": "ablation",
        "title": "Capex print plus tone",
        "story": "Does mixing the print with tone help?",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "llm_level": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C5_A_h3",
        "chapter": "investment_cycle",
        "role": "reference",
        "title": "H3 reference: novelty plus level",
        "story": "v1 no-op (novelty absent). Not confirmatory.",
        "universe": "all",
        "dimension": "capital_allocation",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "llm_level": 1},
        "baseline": "llm_level",
    },
    # --- Ch6 regulatory residual ---
    {
        "id": "C6_P_novelty_vs_level",
        "chapter": "regulatory",
        "role": "primary",
        "title": "New export-control language, not the standing risk tone",
        "story": "H6 blended novelty with level and lost. Novelty alone is the residual.",
        "universe": "semis_cycle",
        "dimension": "macro_regulatory_risk",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C6_P_change_vs_level",
        "chapter": "regulatory",
        "role": "primary",
        "title": "Export-control change, not the standing tone",
        "story": "The other residual: a change in scored risk.",
        "universe": "semis_cycle",
        "dimension": "macro_regulatory_risk",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C6_A_h6",
        "chapter": "regulatory",
        "role": "reference",
        "title": "H6 reference: level plus novelty",
        "story": "v1 loser, locked.",
        "universe": "semis_cycle",
        "dimension": "macro_regulatory_risk",
        "mode": "blend",
        "weights": {"llm_level": 1, "narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C6_A_novelty_all",
        "chapter": "regulatory",
        "role": "ablation",
        "title": "Regulatory novelty vs level, full book",
        "story": "Is the residual a semi fact or a book fact?",
        "universe": "all",
        "dimension": "macro_regulatory_risk",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C6_A_novelty_designers",
        "chapter": "regulatory",
        "role": "ablation",
        "title": "Regulatory novelty vs level, designers",
        "story": "Export rules hit designers first.",
        "universe": "designers",
        "dimension": "macro_regulatory_risk",
        "mode": "natural",
        "weights": {"narrative_novelty": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C6_A_nov_change_semis",
        "chapter": "regulatory",
        "role": "ablation",
        "title": "Regulatory novelty plus change, semis",
        "story": "H4-shaped recipe on the risk dimension.",
        "universe": "semis_cycle",
        "dimension": "macro_regulatory_risk",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    # --- Ch7 earnings power (untouched in v1) ---
    {
        "id": "C7_P_quant_vs_level",
        "chapter": "earnings_power",
        "role": "primary",
        "title": "Earnings power is the print",
        "story": "Bottom-line z should beat earnings-power tone on the full book.",
        "universe": "all",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C7_A_surprise_vs_quant",
        "chapter": "earnings_power",
        "role": "ablation",
        "title": "EPS narrative surprise vs print",
        "story": "Is there residual in the surprise once the print is known?",
        "universe": "all",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"surprise_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C7_A_change_vs_level",
        "chapter": "earnings_power",
        "role": "ablation",
        "title": "EPS change vs tone",
        "story": "Sequential earnings-power change.",
        "universe": "all",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C7_A_agrees_plus_quant",
        "chapter": "earnings_power",
        "role": "control",
        "title": "EPS confirmation plus print",
        "story": "H8-shaped control on earnings power.",
        "universe": "all",
        "dimension": "earnings_power",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C7_A_quant_software",
        "chapter": "earnings_power",
        "role": "ablation",
        "title": "Software EPS print vs tone",
        "story": "Same primary inside the duration sleeve.",
        "universe": "software_cloud",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C7_A_quant_semis",
        "chapter": "earnings_power",
        "role": "ablation",
        "title": "Semi EPS print vs tone (ablation)",
        "story": "Duplicates C3_P_eps for the earnings-power chapter read.",
        "universe": "semis_cycle",
        "dimension": "earnings_power",
        "mode": "natural",
        "weights": {"quant_z_pit": 1},
        "baseline": "llm_level",
    },
    # --- Ch8 equipment cycle ---
    {
        "id": "C8_P_demand_surprise_vs_quant",
        "chapter": "equipment_cycle",
        "role": "primary",
        "title": "WFE demand surprise beats the print",
        "story": "Equipment is booked on incremental demand, not the already-printed run-rate.",
        "universe": "equipment",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"surprise_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C8_A_demand_change_vs_quant",
        "chapter": "equipment_cycle",
        "role": "ablation",
        "title": "WFE demand change vs print",
        "story": "Sequential bookings change as the WFE tell.",
        "universe": "equipment",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C8_A_demand_level_vs_quant",
        "chapter": "equipment_cycle",
        "role": "ablation",
        "title": "WFE demand tone vs print",
        "story": "Standing demand tone in a four-name sleeve.",
        "universe": "equipment",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"llm_level": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "C8_A_share_shift",
        "chapter": "equipment_cycle",
        "role": "ablation",
        "title": "WFE share-shift vs moat",
        "story": "Same H4 recipe on equipment.",
        "universe": "equipment",
        "dimension": "competitive_position",
        "mode": "blend",
        "weights": {"narrative_novelty": 2, "change_magnitude": 1},
        "baseline": "llm_level",
    },
    {
        "id": "C8_A_capex_change",
        "chapter": "equipment_cycle",
        "role": "ablation",
        "title": "WFE customers' spend change vs tone",
        "story": "Equipment names talking about customer capex.",
        "universe": "equipment",
        "dimension": "capital_allocation",
        "mode": "natural",
        "weights": {"change_magnitude": 1},
        "baseline": "llm_level",
    },
    # --- Extra controls (do not count) ---
    {
        "id": "CTRL_demand_confirm_all",
        "chapter": "controls",
        "role": "control",
        "title": "H8 reference: demand confirmation",
        "story": "v1 control, locked.",
        "universe": "all",
        "dimension": "demand",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "CTRL_demand_confirm_semis",
        "chapter": "controls",
        "role": "control",
        "title": "Demand confirmation, semis",
        "story": "If confirmation helped anywhere it would be here.",
        "universe": "semis_cycle",
        "dimension": "demand",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "CTRL_demand_confirm_software",
        "chapter": "controls",
        "role": "control",
        "title": "Demand confirmation, software",
        "story": "Confirmation control in the duration sleeve.",
        "universe": "software_cloud",
        "dimension": "demand",
        "mode": "blend",
        "weights": {"quant_z_pit": 1, "agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
    {
        "id": "CTRL_demand_agrees_vs_quant",
        "chapter": "controls",
        "role": "control",
        "title": "Demand agreement alone vs print",
        "story": "Agreement without mixing the print back in.",
        "universe": "all",
        "dimension": "demand",
        "mode": "natural",
        "weights": {"agrees_with_quant": 1},
        "baseline": "quant_z_pit",
    },
]


def _round(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _resolve_tickers(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    if universe in {"all", ALL_COMPANIES, ""}:
        return list(book)
    sector = [str(t).upper() for t in load_sector_companies(universe)]
    return [t for t in sector if t in have]


IndexKey = tuple[str, str, str]


def _finite(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _index_rows(rows, *, label: str, horizon: str) -> dict[IndexKey, dict[str, tuple[float, float]]]:
    """(dimension, signal, period) -> {ticker: (signal_mean, label_mean)}."""
    out: dict[IndexKey, dict[str, tuple[float, float]]] = {}
    for row in rows:
        if str(row.get("label_key") or row.get("label") or "") != label:
            continue
        if str(row.get("horizon") or "") != horizon:
            continue
        sx = _finite(row.get("signal_mean"))
        sy = _finite(row.get("label_mean"))
        if sx is None or sy is None:
            continue
        dimension = str(row.get("dimension") or "")
        signal = str(row.get("signal") or "")
        period = str(row.get("period") or "")
        ticker = str(row.get("ticker") or "").upper()
        if not dimension or not signal or not period or not ticker:
            continue
        bucket = out.setdefault((dimension, signal, period), {})
        bucket[ticker] = (sx, sy)
    return out


def _periods_of(index: dict[IndexKey, dict[str, tuple[float, float]]], dimension: str, signal: str) -> list[str]:
    return sorted({period for dim, sig, period in index if dim == dimension and sig == signal})


def _score_index(html, spearman, index, tickers, *, dimension, signal, periods=None):
    want = {str(t).upper() for t in tickers}
    if periods is None:
        periods = _periods_of(index, dimension, signal)
    ics: list[float | None] = []
    for period in periods:
        pairs = index.get((dimension, signal, period)) or {}
        xs: list[float] = []
        ys: list[float] = []
        for ticker in want:
            point = pairs.get(ticker)
            if point is None:
                continue
            xs.append(point[0])
            ys.append(point[1])
        ics.append(spearman(xs, ys))
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "rank_ic_ir": _round(stats.get("rank_ic_ir")),
        "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
        "n_periods": stats.get("n_periods"),
    }


def _candidate_signal(hyp: dict) -> str:
    weights = hyp["weights"]
    if hyp["mode"] == "blend":
        return "lab_blend"
    if len(weights) != 1:
        raise ValueError(f"{hyp['id']} natural mode needs exactly one weight")
    return next(iter(weights))


def _eval_hyp(html, spearman, index, rows, book, hyp: dict) -> dict:
    tickers = _resolve_tickers(str(hyp["universe"]), book)
    dimension = str(hyp["dimension"])
    baseline = str(hyp["baseline"])
    weights = {str(k): float(v) for k, v in dict(hyp["weights"]).items()}
    candidate = _candidate_signal(hyp)
    cand_index = index
    if hyp["mode"] == "blend":
        blended = blend_company_period(
            rows,
            tickers,
            label=LABEL,
            horizon=HORIZON,
            dimension=dimension,
            weights=weights,
            include_revision=False,
        )
        cand_index = _index_rows(blended, label=LABEL, horizon=HORIZON)
    overlap = sorted(
        set(_periods_of(cand_index, dimension, candidate))
        & set(_periods_of(index, dimension, baseline))
    )
    cand = _score_index(
        html,
        spearman,
        cand_index,
        tickers,
        dimension=dimension,
        signal=candidate,
        periods=overlap or None,
    )
    base = _score_index(
        html,
        spearman,
        index,
        tickers,
        dimension=dimension,
        signal=baseline,
        periods=overlap or None,
    )
    cand_ic = cand["rank_ic_mean"]
    base_ic = base["rank_ic_mean"]
    beats = cand_ic is not None and base_ic is not None and float(cand_ic) > float(base_ic)
    return {
        "id": hyp["id"],
        "chapter": hyp["chapter"],
        "role": hyp["role"],
        "title": hyp["title"],
        "story": hyp["story"],
        "universe": hyp["universe"],
        "tickers": tickers,
        "n_tickers": len(tickers),
        "dimension": dimension,
        "mode": hyp["mode"],
        "weights": weights,
        "candidate_signal": candidate,
        "baseline_signal": baseline,
        "overlap_n": len(overlap),
        "candidate": cand,
        "baseline": base,
        "beats_baseline": beats,
        "delta": None
        if cand_ic is None or base_ic is None
        else _round(float(cand_ic) - float(base_ic)),
    }


def _chapter_holds(beats: dict[str, bool]) -> dict[str, bool]:
    def on(hid: str) -> bool:
        return bool(beats.get(hid))

    return {
        "share_shift": sum(on(k) for k in ("C1_P_semis", "C1_P_software", "C1_P_designers")) >= 2,
        "cheap_talk": sum(on(k) for k in ("C2_P_all", "C2_P_semis", "C2_P_software")) >= 2,
        "semi_cycle": on("C3_P_demand_quant_vs_surprise")
        and (on("C3_P_margins_quant_vs_level") or on("C3_P_eps_quant_vs_level")),
        "software_duration": on("C4_P_guidance_level_vs_surprise")
        and on("C4_P_demand_quant_vs_level"),
        "investment_cycle": on("C5_P_change_vs_level") or on("C5_P_surprise_vs_level"),
        "regulatory": on("C6_P_novelty_vs_level") or on("C6_P_change_vs_level"),
        "earnings_power": on("C7_P_quant_vs_level"),
        "equipment_cycle": on("C8_P_demand_surprise_vs_quant"),
    }


def _atlas(html, spearman, index, book) -> list[dict]:
    out: list[dict] = []
    for universe in ATLAS_UNIVERSES:
        tickers = _resolve_tickers(universe, book)
        for dimension in ATLAS_DIMENSIONS:
            for signal in ATLAS_SIGNALS:
                periods = _periods_of(index, dimension, signal)
                if not periods:
                    continue
                stats = _score_index(
                    html,
                    spearman,
                    index,
                    tickers,
                    dimension=dimension,
                    signal=signal,
                    periods=periods,
                )
                if not stats["n_periods"]:
                    continue
                out.append(
                    {
                        "universe": universe,
                        "n_tickers": len(tickers),
                        "dimension": dimension,
                        "signal": signal,
                        **stats,
                    }
                )
    return out


def _dump_catalog() -> None:
    path = ROOT / "config" / "signal_packs" / "tech_lab_case_study_v2.yaml"
    payload = {
        "case_study_id": "tech_lab_v2",
        "label": LABEL,
        "horizon": HORIZON,
        "notes": (
            "Research catalog. Not production. Primaries are confirmatory; "
            "ablations/controls/references do not count toward chapter holds."
        ),
        "hypotheses": HYPOTHESES,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, width=88), encoding="utf-8")


def main() -> None:
    _dump_catalog()
    history = ROOT / "Structured Narrative" / "output"
    meta = json.loads(
        (history / "cross_company" / "json" / "narrative_signal_eval.json").read_text(
            encoding="utf-8"
        )
    )
    book = [str(t).upper() for t in (meta.get("tickers") or [])]
    rows = load_rank_ic_bundle(history_source=str(history)).company_period
    html = _rank_ic_html()
    spearman = _spearman()
    index = _index_rows(rows, label=LABEL, horizon=HORIZON)

    atlas = _atlas(html, spearman, index, book)
    results = [_eval_hyp(html, spearman, index, rows, book, hyp) for hyp in HYPOTHESES]
    beats = {row["id"]: bool(row["beats_baseline"]) for row in results}
    holds = _chapter_holds(beats)
    chapters_held = sum(1 for v in holds.values() if v)

    store = load_lab_store()
    for hyp, row in zip(HYPOTHESES, results):
        if hyp["role"] != "primary" or hyp["mode"] != "blend":
            continue
        ukey = universe_key(
            ALL_COMPANIES if hyp["universe"] == "all" else str(hyp["universe"]),
            row["tickers"],
        )
        upsert_recipe(
            store,
            name=str(hyp["title"]),
            universe_key_value=ukey,
            label=LABEL,
            horizon=HORIZON,
            dimension=str(hyp["dimension"]),
            weights=hyp["weights"],
            include_revision=False,
            recipe_id=str(hyp["id"]),
        )
    save_lab_store(store)

    payload = {
        "case_study_id": "tech_lab_v2",
        "generated_at": meta.get("generated_at"),
        "label": LABEL,
        "horizon": HORIZON,
        "n_tickers_book": len(book),
        "n_hypotheses": len(results),
        "n_primaries": sum(1 for h in HYPOTHESES if h["role"] == "primary"),
        "primary_beats": sum(
            1 for row in results if row["role"] == "primary" and row["beats_baseline"]
        ),
        "chapters_held": chapters_held,
        "chapters_n": len(holds),
        "case_study_pass": chapters_held >= 4,
        "chapter_holds": holds,
        "results": results,
        "atlas": atlas,
    }
    out = history / "cross_company" / "json" / "tech_lab_case_study_v2_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = {
        k: payload[k]
        for k in (
            "case_study_id",
            "generated_at",
            "n_hypotheses",
            "n_primaries",
            "primary_beats",
            "chapters_held",
            "chapters_n",
            "case_study_pass",
            "chapter_holds",
        )
    }
    summary["primaries"] = [
        {
            "id": row["id"],
            "beats": row["beats_baseline"],
            "candidate": row["candidate"]["rank_ic_mean"],
            "baseline": row["baseline"]["rank_ic_mean"],
            "delta": row["delta"],
            "n": row["overlap_n"],
        }
        for row in results
        if row["role"] == "primary"
    ]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
