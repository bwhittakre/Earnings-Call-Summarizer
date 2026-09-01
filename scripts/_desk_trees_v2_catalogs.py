"""Hand-typed operational first seeds. Not NVIDIA gold. Not auto-inserted.

Each tree is a leftover seedable cue typed from novelty_view. Walk may add
restated or silent. Delivered, hit, and missed are not invented here.
"""
from __future__ import annotations

OPS_TREES: tuple[dict[str, object], ...] = (
    {
        "tree_id": "adbe-device-co-op",
        "ticker": "ADBE",
        "kind": "promise",
        "beat_id": "device-co-op",
        "bucket": "competitive_position",
        "title": "Adobe Marketing Cloud Device Co-op identifies consumers across devices",
        "objects": ("Device Co-op", "Adobe Marketing Cloud Device Co-op"),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We unveiled the next generation Adobe Marketing Cloud, shared our "
                "Adobe Cloud platform roadmap and announced the Adobe Marketing Cloud "
                "Device Co-op, a network that will enable the world's biggest brands "
                "to work together to better identify consumers across digital devices."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "adsk-collections-launch",
        "ticker": "ADSK",
        "kind": "promise",
        "beat_id": "collections",
        "bucket": "competitive_position",
        "title": "Begin selling Collections next-generation suites",
        "objects": ("Collections",),
        "seed": {
            "fiscal_period": "FY2017-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q3",
            "excerpt": (
                "Another exciting factor about Q3 is that we'll begin selling what "
                "can be thought of as our next generation of suites called collections. "
                "We won't officially launch it with our customers until next week, but "
                "I'll give you a little preview. Collections will be the most convenient "
                "way for customers to access a wide selection of both our desktop "
                "software and our cloud services."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "crm-20b-next-goal",
        "ticker": "CRM",
        "kind": "goal",
        "beat_id": "twenty-billion",
        "bucket": "earnings_power",
        "title": "Next goal is $20 billion of revenue",
        "objects": ("$20 billion", "20 billion"),
        "seed": {
            "fiscal_period": "FY2017-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "we expect to deliver more than $10 billion in revenue in fiscal 2018. "
                "I think we initiated guidance at $10.15 billion at the high end of our "
                "range. And now, we are setting our sights on our next goal, $20 billion."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2018-Q2",
                "edge": "restated",
                "excerpt": (
                    "I'll tell you, we took our whole management team "
                    "offsite two weeks ago to lay out our plan for what "
                    "we call chapter three. Chapter one for us certainly "
                    "was zero to $1 billion...Now, we're in chapter "
                    "three, which is to go from $10 to $20 billion."
                ),
                "dimension": "management_confidence",
                "status": "composite",
                "coverage_summary": (
                    "Chapter three still frames the $20 billion goal as "
                    "ahead, $10 to $20 billion."
                ),
            },
            {
                "fiscal_period": "FY2021-Q4",
                "edge": "hit",
                "excerpt": (
                    "There's never been a software company over $20 billion "
                    "in revenue that is growing as fast as we are. And as "
                    "we shared at our Investor Day last year, our long-term "
                    "revenue target for the fiscal year 2026 is now $50 "
                    "billion or basically we're going to double the company "
                    "from where we are right now."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
                "coverage_summary": (
                    "FY2021-Q4 treats the company as already over $20 "
                    "billion in revenue and points at a new $50 billion "
                    "target."
                ),
                "delivery_basis": (
                    "FY2021-Q4 cite says Salesforce is over $20 billion "
                    "in revenue. FY2021-Q1 $20 billion guide is not the hit."
                ),
            },
        ),
    },
    {
        "tree_id": "ibm-promontory-watson",
        "ticker": "IBM",
        "kind": "promise",
        "beat_id": "promontory-watson",
        "bucket": "competitive_position",
        "title": "Train Watson on Promontory financial-regulation expertise",
        "objects": ("Promontory", "Watson"),
        "expire": "FY2018-Q3",
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We announced the acquisition of Promontory Financial Group, a leader "
                "in regulatory compliance and a risk management consulting. So just as "
                "we trained Watson on clinical research and medical guidelines to work "
                "with doctors treating cancer, we will apply the expertise of Promontory "
                "to train Watson to directly address escalating regulations, their risk "
                "management requirements in financial services."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2018-Q3",
                "edge": "expired",
                "excerpt": (
                    "Never followed up in a way we can settle. Completeness is "
                    "unfeasible. Not a miss and not a withdrawal."
                ),
            },
        ),
    },
    {
        "tree_id": "intu-turbotax-diy-growth",
        "ticker": "INTU",
        "kind": "goal",
        "beat_id": "turbotax-growth",
        "bucket": "demand",
        "title": "Tax simplification becomes a TurboTax growth catalyst",
        "objects": ("TurboTax",),
        "seed": {
            "fiscal_period": "FY2018-Q4",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "This change does introduce some trade down risk from our paid to our "
                "free offering but in aggregate, we believe tax simplification will be "
                "an overall catalyst for DIY category and TurboTax growth as more "
                "assisted customers choose to adopt digital solutions."
            ),
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "msft-build-analyst-briefing",
        "ticker": "MSFT",
        "kind": "promise",
        "beat_id": "build-briefing",
        "bucket": "management_confidence",
        "title": "Hold a financial analyst briefing at BUILD in May",
        "objects": ("BUILD", "financial analyst briefing"),
        "seed": {
            "fiscal_period": "FY2017-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "I'd like to announce that we will hold a financial analyst briefing "
                "for the investor community in conjunction with our BUILD Developer "
                "Conference in May here in Seattle."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "orcl-2b-cloud-sales",
        "ticker": "ORCL",
        "kind": "promise",
        "beat_id": "cloud-2b",
        "bucket": "demand",
        "title": "Book more than $2 billion in annual cloud sales this year",
        "objects": ("cloud sales",),
        "seed": {
            "fiscal_period": "FY2017-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "We will book more than $2 billion in annual cloud sales this year, "
                "much more than salesforce.com."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "aapl-net-cash-neutral",
        "ticker": "AAPL",
        "kind": "goal",
        "beat_id": "net-cash-neutral",
        "bucket": "capital_allocation",
        "title": "Become approximately net cash neutral over time",
        "objects": ("net cash neutral",),
        "seed": {
            "fiscal_period": "FY2018-Q1",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "Tax reform will allow us to pursue a more optimal capital structure "
                "for our company. Our current net cash position is $163 billion. And "
                "given the increased financial and operational flexibility from the "
                "access to our foreign cash, we are targeting to become approximately "
                "net cash neutral over time."
            ),
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "acn-the-new-number-one",
        "ticker": "ACN",
        "kind": "goal",
        "beat_id": "the-new",
        "bucket": "competitive_position",
        "title": "Be number one in each of The New five",
        "objects": ("The New",),
        "seed": {
            "fiscal_period": "FY2017-Q2",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "in our rotation to The New in interactive mobility edge cloud and "
                "security, we want not only to be the number one if you addition this "
                "all - this is where we go with our $8 billion in H1 only, but we want "
                "to be number one in each of the five."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "amd-radeon-pro-duo",
        "ticker": "AMD",
        "kind": "promise",
        "beat_id": "radeon-pro-duo",
        "bucket": "competitive_position",
        "title": "Launch Radeon Pro Duo VR platform at month-end",
        "objects": ("Radeon Pro Duo",),
        "seed": {
            "fiscal_period": "FY2016-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2016-Q1",
            "excerpt": (
                "I am proud to share that we plan to launch the industry's most "
                "powerful platform for VR creation and consumption at the end of this "
                "month when we introduce the $1,500 Radeon Pro Duo."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "amzn-prime-india",
        "ticker": "AMZN",
        "kind": "promise",
        "beat_id": "prime-india",
        "bucket": "demand",
        "title": "Prime India unlimited free one- and two-day delivery",
        "objects": ("Prime", "Prime Video"),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "You heard that we launched the Prime program this week, which will be "
                "a whole new experience for Indian customers. In hundreds of cities "
                "we'll now have unlimited free one-day and two-day delivery, and we "
                "also mentioned that Prime Video is coming there, both Indian and "
                "global content. We're also starting to see exclusive online sales "
                "partnerships. Recently, we've had partnerships with Motorola, Samsung, "
                "Lenovo on select phones."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "csco-luxtera-optics",
        "ticker": "CSCO",
        "kind": "promise",
        "beat_id": "luxtera",
        "bucket": "competitive_position",
        "title": "Integrate Luxtera optics instead of procuring them",
        "objects": ("Luxtera",),
        "seed": {
            "fiscal_period": "FY2019-Q2",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "Our acquisition of Luxtera will further augment our existing "
                "capability around silicon and optics, enabling our customers to build "
                "the fastest and most efficient networks...Instead of us having to go "
                "out and procure the optics, we'll be able to more tightly integrate them."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "adi-vescent-lidar",
        "ticker": "ADI",
        "kind": "promise",
        "beat_id": "vescent-lidar",
        "bucket": "competitive_position",
        "title": "Develop solid-state scanning LIDAR from Vescent",
        "objects": ("LIDAR", "Vescent"),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We also announced the acquisition of some exciting LIDAR technology "
                "from Vescent Photonics that will enable ADI to develop a true, "
                "solid-state scanning LIDAR system, complementing our existing "
                "radar-based ADAS offerings... it's a potentially beyond $1 billion "
                "semiconductor TAM for this thing for us."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "amat-double-packaging",
        "ticker": "AMAT",
        "kind": "promise",
        "beat_id": "packaging",
        "bucket": "demand",
        "title": "Double packaging revenues over the next 12 months",
        "objects": ("packaging", "advanced packaging"),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "I'm also pleased by the progress we're making in advanced packaging. "
                "We have some great new products and based on the positions we're "
                "winning, we expect to double our packaging revenues over the next "
                "12 months."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "ctsh-accelerate-acquisitions",
        "ticker": "CTSH",
        "kind": "promise",
        "beat_id": "acquire-2017",
        "bucket": "capital_allocation",
        "title": "Accelerate the acquisition pace in 2017",
        "objects": ("acquire companies",),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "we are intensifying our efforts to acquire companies, expanding our "
                "intellectual property, industry expertise, geographic reach, and "
                "platform and technology capabilities. We've recently ramped up this "
                "activity and we expect to accelerate the pace further in 2017"
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "mu-s600-seagate",
        "ticker": "MU",
        "kind": "promise",
        "beat_id": "s600",
        "bucket": "demand",
        "title": "Realize S600 Series revenue in Q3 volume production",
        "objects": ("S600", "Seagate"),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2016-Q3",
            "excerpt": (
                "within the cloud segment we had record DDR4 shipments increasing our "
                "market share with key hyper-scale customers in Asia Pacific... In our "
                "Enterprise SSD segment, we're starting to ship our S600 Series SaaS "
                "drive Micron's first product produced through our strategic partnership "
                "with Seagate. We expect to realize revenue from this new product line "
                "in Q3 as we move into volume production."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "tel-medical-500m",
        "ticker": "TEL",
        "kind": "promise",
        "beat_id": "medical-500",
        "bucket": "demand",
        "title": "Medical run-rate north of $500 million next year",
        "objects": ("Creganna", "AdvancedCath", "medical"),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "The medical business from a run rate right now, we sit there. Next "
                "year, it will be about $500 million, both on our legacy business, as "
                "well as what we've done with both Creganna and AdvancedCath. So, "
                "they'll be north of $500 million next year, Shawn, is where we'll "
                "be running."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "txn-capital-call-feb8",
        "ticker": "TXN",
        "kind": "promise",
        "beat_id": "capital-call",
        "bucket": "capital_allocation",
        "title": "Hold a capital-management strategy call on February 8",
        "objects": ("capital management",),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q1",
            "excerpt": (
                "We plan to hold a call to update our capital management strategy on "
                "February 8th at 10:00 AM Central time. Similar to what we've done in "
                "the past, Rafael and I will provide some insight into our strategy."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "opal-analyst-day-q3",
        "ticker": "OPAL",
        "kind": "promise",
        "beat_id": "analyst-day",
        "bucket": "capital_allocation",
        "title": "Host an analyst day in the third quarter",
        "objects": ("analyst day",),
        "seed": {
            "fiscal_period": "FY2024-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q3",
            "excerpt": (
                "We're going to host an analyst day. I'm looking over at Kazi here. "
                "He's been on the job for about a month. Maybe it'll be in the third "
                "quarter that we'll target it. We're going to do a much better job of "
                "explaining to folks what the free cash flow generation is at OPAL "
                "Fuels and what the flexibilities we have to create, enhance, unlock "
                "shareholder value with that discretionary free cash flow."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "avgo-day2-one-erp",
        "ticker": "AVGO",
        "kind": "promise",
        "beat_id": "day2-erp",
        "bucket": "margins",
        "title": "Run one ERP after day-2 integration at the end of November",
        "objects": ("day 2", "ERP"),
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q1",
            "excerpt": (
                "After the end of November, which is our day 2, what we call day 2 "
                "where we integrate two systems into one, one database, one ERP "
                "system. We expect to run only one system that will be a step down "
                "in terms of our headcount requirements, in terms of our support "
                "costs and obviously, an improvement in our operating cost structure "
                "significantly."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "avgo-45-op-margin",
        "ticker": "AVGO",
        "kind": "goal",
        "beat_id": "forty-five-margin",
        "bucket": "margins",
        "title": "Long-term operating margin target of 45%",
        "objects": ("45%", "operating margin"),
        "seed": {
            "fiscal_period": "FY2016-Q4",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We are raising our long-term operating margin target to 45%, a "
                "significant increase from our prior model. We expect to drive to "
                "this long-term target through a combination of the full realization "
                "of material cost synergies and operating leverage on a larger scale."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "lrcx-klx-approvals-mid2016",
        "ticker": "LRCX",
        "kind": "promise",
        "beat_id": "klx-approvals",
        "bucket": "macro_regulatory_risk",
        "title": "Secure approvals to complete the transaction in mid-2016",
        "objects": ("approvals", "mid-2016"),
        "seed": {
            "fiscal_period": "FY2016-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2016-Q4",
            "excerpt": (
                "We remain confident that we can secure approvals to complete the "
                "transaction in mid-2016."
            ),
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "strw-150-160-spend",
        "ticker": "STRW",
        "kind": "goal",
        "beat_id": "spend-bogey",
        "bucket": "capital_allocation",
        "title": "Break a $150 to $160 million annual spend bogey",
        "objects": ("$150 to $160 million",),
        "expire": "FY2027-Q3",
        "quant": {
            "measure": None,
            "op": "between",
            "threshold": [150, 160],
            "unit": "million",
            "cadence": "annual",
            "silence_quarters": 4,
            "unclocked_cap_quarters": 8,
        },
        "coverage_summary": (
            "IBES Capex (22) prints 0–88 and is not this REIT spend bogey. "
            "No invented measure. Runner stays pending until FY2027-Q3."
        ),
        "seed": {
            "fiscal_period": "FY2025-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "Our bogey that we're trying to break is $150 to $160 million spent "
                "a year. As we get bigger, we want to spend more obviously, but we "
                "do our deals exactly the same way."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "adi-wireless-bms-deploy",
        "ticker": "ADI",
        "kind": "goal",
        "beat_id": "wireless-bms",
        "bucket": "competitive_position",
        "title": "Wireless BMS becomes a large share of BMS revenue",
        "objects": ("wireless BMS", "wireless platform", "wireless solution"),
        "seed": {
            "fiscal_period": "FY2023-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "Currently, our wireless BMS is designed in at four OEMs, and we "
                "expect another large OEM to adopt it in the coming quarters. Given "
                "this momentum and the cutting-edge value proposition, we believe "
                "the wireless platform will represent a large portion of our BMS "
                "revenue by the end of the decade."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2023-Q4",
                "edge": "harden-to-promise",
                "clock": "FY2026-Q4",
                "excerpt": (
                    "Last quarter, we secured our fifth customer, a top 10 EV OEM. "
                    "We'll begin to deploy our wireless solution in their next-gen "
                    "EVs in 2026."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Same object. Want for wireless BMS share became a dated "
                    "deploy will. Clock is calendar 2026, scored as FY2026-Q4. "
                    "Not delivered."
                ),
            },
        ),
    },
)
