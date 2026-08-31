"""Hand-typed healthcare first seeds. Not NVIDIA gold. Not tech ops.

Each tree is a leftover seedable cue typed from novelty_view. Walk may add
restated or silent. Delivered, hit, and missed are not invented here.
"""
from __future__ import annotations

HC_TREES: tuple[dict[str, object], ...] = (
    {
        "tree_id": "lly-dividend-december",
        "ticker": "LLY",
        "kind": "promise",
        "beat_id": "dividend-restore",
        "title": "Return to annual dividend increases beginning in December",
        "objects": ("dividend",),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2016-Q4",
            "excerpt": (
                "we plan to return to annual dividend increases to our shareholders "
                "beginning in December this year and to return excess cash via share "
                "repurchases."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2017-Q4",
                "edge": "restated",
                "excerpt": (
                    "we announced an 8% increase in the dividend, reflecting "
                    "our confidence in the continued growth prospects of the "
                    "company."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
                "coverage_summary": (
                    "First later dividend-increase cite is FY2017-Q4. "
                    "Not a December 2016 delivery."
                ),
            },
        ),
    },
    {
        "tree_id": "unh-medexpress-75",
        "ticker": "UNH",
        "kind": "promise",
        "beat_id": "medexpress-ramp",
        "title": "Ramp MedExpress startups to about 75 in 2017",
        "objects": ("MedExpress",),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "Today, we have about 175 MedExpress urgent care centers, we have "
                "been doing about 30 startups a year. I think we'll ramp that up in "
                "2017 to about 75."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "jnj-guselkumab-file",
        "ticker": "JNJ",
        "kind": "promise",
        "beat_id": "guselkumab-pso",
        "title": "File guselkumab for psoriasis this year",
        "objects": ("guselkumab",),
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2016-Q4",
            "excerpt": (
                "guselkumab is a first-in-class selective anti-IL-23 monoclonal "
                "antibody that demonstrated significant efficacy versus placebo and "
                "superiority compared with the anti-tumor necrosis factor adalimumab "
                "in moderate to severe plaque psoriasis... We plan to file for "
                "psoriasis this year and advance guselkumab into phase III for "
                "patients with psoriatic arthritis."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "abbv-humira-ip-2022",
        "ticker": "ABBV",
        "kind": "goal",
        "beat_id": "humira-ip",
        "title": "HUMIRA U.S. IP protection until 2022",
        "objects": ("HUMIRA", "2022"),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2022-Q4",
            "excerpt": (
                "We remain committed to the position that we took back in 2015 that "
                "we believe our portfolio of IP will protect HUMIRA within the U.S. "
                "until 2022."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "mrk-dividend-15",
        "ticker": "MRK",
        "kind": "promise",
        "beat_id": "dividend-hike",
        "title": "Raise the quarterly dividend 15% beginning in Q1 2019",
        "objects": ("dividend", "15%"),
        "seed": {
            "fiscal_period": "FY2018-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q1",
            "excerpt": (
                "Today, we announce that we will increase our quarterly dividend by "
                "15%, or by $0.07 to $0.55 per share, beginning in the first quarter "
                "of 2019."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "tmo-2019-guidance-january",
        "ticker": "TMO",
        "kind": "promise",
        "beat_id": "january-guidance",
        "title": "Give 2019 guidance in late January",
        "objects": ("2019 guidance",),
        "seed": {
            "fiscal_period": "FY2018-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q1",
            "excerpt": (
                "We don't see any storm clouds on the horizon as I think about 2019. "
                "Obviously, we'll give you 2019 guidance in late January. At least "
                "sitting here right now, the world looks very positive."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "abt-libre-1m-patients",
        "ticker": "ABT",
        "kind": "promise",
        "beat_id": "libre-1m",
        "title": "More than 1 million patients worldwide by year-end",
        "objects": ("1 million patients",),
        "seed": {
            "fiscal_period": "FY2018-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2018-Q4",
            "excerpt": (
                "we'll go out at the end of the year with more than 1 million "
                "patients worldwide... If you take the sensors, numbers of patients, "
                "whatever, and how many days of testing you get out of that, we're "
                "already well above 90% globally, and there's nothing to compare to."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "dhr-phenomenex-return",
        "ticker": "DHR",
        "kind": "promise",
        "beat_id": "phenomenex-roi",
        "title": "Double-digit return on Phenomenex in less than five years",
        "objects": ("Phenomenex",),
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2021-Q3",
            "excerpt": (
                "Phenomenex is 100% consumables, a high-margin business in an "
                "attractive mid-single-digit growth industry that is adjacent to "
                "where SCIEX participates. We expect to achieve a double-digit "
                "return on our investment in less than five years"
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "pfe-trazimera-launch",
        "ticker": "PFE",
        "kind": "promise",
        "beat_id": "trazimera",
        "title": "Launch Trazimera next month",
        "objects": ("Trazimera",),
        "seed": {
            "fiscal_period": "FY2019-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2020-Q1",
            "excerpt": (
                "Last week, we announced the launches of Zirabev and Ruxience in the "
                "U.S. market. Next month we expect to launch Trazimera. All three "
                "products will be available at a substantially discounted price "
                "compared with their originator products."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "amgn-wclc-lung",
        "ticker": "AMGN",
        "kind": "promise",
        "beat_id": "wclc-update",
        "title": "Update lung-cancer progress at WCLC in early September",
        "objects": ("World Conference on Lung Cancer",),
        "seed": {
            "fiscal_period": "FY2019-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q3",
            "excerpt": (
                "We will also begin enrollment of lung cancer patients in the coming "
                "days in the potentially registration-enabling phase II monotherapy "
                "portion of the program and will provide an update of our progress "
                "in lung cancer at the 2019 World Conference on Lung Cancer in "
                "early September."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "isrg-davinci-x",
        "ticker": "ISRG",
        "kind": "promise",
        "beat_id": "davinci-x",
        "title": "Launch the da Vinci X upgrade over the next several quarters",
        "objects": ("da Vinci X",),
        "seed": {
            "fiscal_period": "FY2017-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "Over the next several quarters, we plan to launch a new technology "
                "upgrade to Si Named da Vinci X, that enables a compelling entry "
                "point to our advanced technologies. da Vinci Xi will remain our "
                "flagship, and we will provide customers with logical upgrade paths "
                "from more affordable entry-level systems like Si and X to Si and SP."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2017-Q2",
                "edge": "delivered",
                "excerpt": (
                    "Of the 166 second quarter systems, 11 were X systems... "
                    "During the quarter, the first clinical experience on "
                    "da Vinci X occurred in Germany. Initial procedures "
                    "include urology and gynecology with strong early "
                    "utilization."
                ),
                "dimension": "competitive_position",
                "status": "composite",
                "coverage_summary": (
                    "Next quarter treated da Vinci X as placed systems "
                    "and first clinical use."
                ),
                "delivery_basis": (
                    "FY2017-Q2 cite says 11 of 166 systems were X and "
                    "first clinical experience on da Vinci X occurred in "
                    "Germany, inside the FY2017-Q4 clock."
                ),
            },
        ),
    },
    {
        "tree_id": "syk-knee-aaos-2017",
        "ticker": "SYK",
        "kind": "promise",
        "beat_id": "knee-aaos",
        "title": "Full commercial launch of the total knee at 2017 AAOS",
        "objects": ("AAOS", "total knee"),
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q1",
            "excerpt": (
                "Since the start of the limited market release for the total knee, "
                "over 200 cases have been performed, and we have been pleased with "
                "the results to date. We are targeting the 2017 AAOS meeting to "
                "move into the full commercial launch."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "gild-zuma2-file",
        "ticker": "GILD",
        "kind": "promise",
        "beat_id": "zuma-2",
        "title": "File KTE-X19 for mantle cell lymphoma by the end of 2019",
        "objects": ("ZUMA-2", "KTE-X19"),
        "seed": {
            "fiscal_period": "FY2019-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q4",
            "excerpt": (
                "I'm also pleased to share that we plan to announce top-line "
                "results of ZUMA-2, a registrational trial of KTE-X19 cell therapy "
                "in patients with relapsed/refractory mantle cell lymphoma. Pending "
                "positive results, we expect to file for U.S. regulatory approval "
                "of KTE-X19 in patients with relapsed/refractory mantle cell "
                "lymphoma for this indication by the end of 2019."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "vrtx-nda-mid-2019",
        "ticker": "VRTX",
        "kind": "promise",
        "beat_id": "triple-nda",
        "title": "Submit a new drug application no later than mid-2019",
        "objects": ("new drug application", "mid-2019"),
        "seed": {
            "fiscal_period": "FY2018-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q2",
            "excerpt": (
                "Based on anticipated completion of enrollment for both programs, "
                "we expect to submit a new drug application no later than mid-2019."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "mdt-aspiration-25",
        "ticker": "MDT",
        "kind": "goal",
        "beat_id": "aspiration-share",
        "title": "Reach 25% of the aspiration market by fiscal year-end",
        "objects": ("aspiration", "25%"),
        "seed": {
            "fiscal_period": "FY2019-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2020-Q4",
            "excerpt": (
                "We estimate that we're somewhere about 15% of this market already. "
                "Well ahead of our plans, this aspiration segment, well ahead of "
                "our plans. We see ourselves getting to 25% by the end of the "
                "fiscal year. We think we'll eventually get to 50% of this "
                "aspiration market."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "bmy-cobenfy-seven-p3",
        "ticker": "BMY",
        "kind": "promise",
        "beat_id": "cobenfy-pivotal",
        "title": "Start seven COBENFY phase 3 studies by mid-year",
        "objects": ("COBENFY",),
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q3",
            "excerpt": (
                "we plan to initiate several new pivotal studies this year, "
                "including seven phase 3 studies for COBENFY across three "
                "indications: Alzheimer's agitation, Alzheimer's cognition "
                "impairment, and bipolar I, all expected to be underway by mid-year."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "regn-aflibercept-8mg-bla",
        "ticker": "REGN",
        "kind": "promise",
        "beat_id": "aflibercept-8mg",
        "title": "Submit aflibercept 8 mg pivotal data in a single BLA this year",
        "objects": ("aflibercept 8-milligram", "BLA"),
        "seed": {
            "fiscal_period": "FY2022-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2022-Q4",
            "excerpt": (
                "We plan to submit the aflibercept 8-milligram pivotal data to the "
                "FDA under a single BLA at the end of this year and have decided "
                "to use a previously granted priority review voucher to expedite "
                "the FDA review process. Pre-launch planning is already underway, "
                "with a potential FDA approval by late August 2023."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "ci-ma-growth-10",
        "ticker": "CI",
        "kind": "goal",
        "beat_id": "ma-10",
        "title": "Medicare Advantage customer growth of at least 10% in 2020",
        "objects": ("Medicare Advantage", "10%"),
        "seed": {
            "fiscal_period": "FY2019-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2020-Q4",
            "excerpt": (
                "Together, all this fuels our geographic and product expansion "
                "plans for 2020 and gives us confidence we will deliver Medicare "
                "Advantage customer growth of at least 10% in 2020."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "elv-pos-rebates-2020",
        "ticker": "ELV",
        "kind": "promise",
        "beat_id": "pos-rebates",
        "title": "Move commercial risk-based business to point-of-sale rebates in 2020",
        "objects": ("point-of-sale rebates",),
        "seed": {
            "fiscal_period": "FY2019-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2020-Q1",
            "excerpt": (
                "In 2020, we will move to providing point-of-sale rebates in our "
                "commercial risk-based business, we are prepared to do the same in "
                "our Medicare business."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "bsx-lotus-edge-launch",
        "ticker": "BSX",
        "kind": "promise",
        "beat_id": "lotus-edge",
        "title": "Limited Lotus Edge release in March Europe and U.S. early Q2",
        "objects": ("Lotus Edge",),
        "seed": {
            "fiscal_period": "FY2018-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2019-Q2",
            "excerpt": (
                "Turning to our Lotus Edge TAVR platform, we'll begin a limited "
                "release in March in Europe, and in the U.S., pending FDA approval, "
                "we anticipate initiating a controlled launch in early Q2."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
)
