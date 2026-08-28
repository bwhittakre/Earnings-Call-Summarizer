"""Hand-typed NVIDIA gold trees. Copied from novelty_view only.

Window FY2022-Q2 through FY2027-Q1. No transcripts_raw. No new LLM.
"""
from __future__ import annotations

GROK_SEED = (
    "we recently entered into a nonexclusive licensing "
    "agreement with Grok for its low latency inference "
    "technology and welcome the team of brilliant engineers "
    "to NVIDIA. As we did with Mellanox, we will extend "
    "NVIDIA's architecture with Grok's innovations to "
    "enable new levels of AI infrastructure performance "
    "and value."
)
SPECTRUM_X_AVAIL_SEED = (
    "Our new Spectrum-X end-to-end Ethernet offering with "
    "technologies, purpose built for AI, will be available in Q1 "
    "next year. With support from leading OEMs, including Dell, "
    "HPE and Lenovo. Spectrum-X can achieve 1.6x higher networking "
    "performance for AI communication compared to traditional "
    "Ethernet offerings."
)
SOVEREIGN_SEED = (
    "From nothing the previous year, we believe Sovereign AI "
    "revenue can approach the high single-digit billions this year."
)
CHINA_WANT_SEED = (
    "We continue to advocate for the US government to approve "
    "Blackwell for China. Our products are designed and sold for "
    "beneficial commercial use, and every license sale we make will "
    "benefit the US economy, the US leadership, in highly competitive "
    "markets. We want to win the hearts of every developer. America's "
    "AI technology stack can be the world's standard if we race and "
    "compete globally."
)
SPECTRUM_X_ANNOUNCE_SEED = (
    "There's a new segment in the middle where the Cloud is becoming "
    "a generative AI cloud... At COMPUTEX, we're going to announce a "
    "major product line for this segment, which is Ethernet focused "
    "generative AI application type of clouds."
)
THREE_CHIP_SEED = (
    "Our 20-year architectural license to Arm's IP allows us the full "
    "breadth and flexibility of options across technologies and markets. "
    "We will deliver on our 3-chip strategy across CPUs, GPUs and DPUs."
)
GRACE_SEED = (
    "At GTC, we announced our first data center CPU, NVIDIA Grace, "
    "targeted at processing massive next generation AI models with "
    "trillions of parameters. The arm-based processor will enable "
    "10x the performance and energy efficiency of today's fastest "
    "servers. With Grace, NVIDIA has a three-chip strategy with GPU, "
    "DPU and now CPU."
)
XAVIER_SEED = (
    "We also announced a single-chip AI supercomputer called Xavier "
    "with over 7 billion transistors. Xavier incorporates our next GPU "
    "architecture, a custom CPU design, and a new computer vision "
    "accelerator. Xavier will deliver performance equivalent to today's "
    "full DRIVE PX 2 board and its two Parker SoCs and two Pascal GPUs, "
    "while only consuming a fraction of the energy."
)
TRILLION_DC_SEED = (
    "We are at the beginning of our journey to modernize a $1 trillion "
    "dollars' worth of data centers from general-purpose computing to "
    "accelerated computing."
)

NVDA_TREES: tuple[dict[str, object], ...] = (
    {
        "tree_id": "nvda-drive-px2-ship-eoy",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "drive-px2",
        "title": "Ship autonomous vehicles / DRIVE PX 2 by year-end",
        "objects": ("DRIVE PX 2", "autonomous vehicles"),
        "seed": {
            "fiscal_period": "FY2017-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2017-Q4",
            "excerpt": (
                "We'll ship autonomous vehicles by the end of this year. "
                "I understand that we're three years ahead of other "
                "people's schedules. However, we also know that DRIVE "
                "PX 2 is the most advanced autonomous computing car "
                "computer in the world today"
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2017-Q2",
                "edge": "delivered",
                "excerpt": (
                    "We have started to ship our DRIVE PX 2 automotive "
                    "supercomputer to the 80-plus companies using both "
                    "our hardware and DriveWorks software to develop "
                    "autonomous driving technologies."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Next quarter treated DRIVE PX 2 as shipping to "
                    "named customers."
                ),
                "delivery_basis": (
                    "FY2017-Q2 cite says NVIDIA has started to ship "
                    "DRIVE PX 2."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-xavier-single-chip",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "xavier",
        "title": "Xavier delivers DRIVE PX 2-class performance on one chip",
        "objects": ("Xavier", "DRIVE PX 2"),
        "seed": {
            "fiscal_period": "FY2017-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": XAVIER_SEED,
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2017-Q4",
                "edge": "restated",
                "excerpt": (
                    "Our next generation, the processor is called Xavier. "
                    "We announced that recently. Xavier basically takes "
                    "four processors and shrink it into one. And so we'll "
                    "be able to achieve Level 4 with one processor."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
        ),
        "coverage_summary": (
            "Announce-time capability. No later shipping cite in novelty_view."
        ),
    },
    {
        "tree_id": "nvda-volvo-l2-early-2020s",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "xavier",
        "title": "Volvo DRIVE AGX Xavier production in the early 2020s",
        "objects": ("Volvo", "DRIVE AGX Xavier"),
        "parent_tree_id": "nvda-xavier-single-chip",
        "parent_seed_excerpt": XAVIER_SEED,
        "seed": {
            "fiscal_period": "FY2019-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2022-Q1",
            "excerpt": (
                "Volvo Cars selected NVIDIA's DRIVE AGX Xavier "
                "next-generation -- for next-generation Volvo Cars. The "
                "initial production release slated for the early 2020s "
                "will deliver Level 2+ assisted driving features...This "
                "is our first Level 2 mass-market car design win."
            ),
            "dimension": "competitive_position",
            "status": "composite",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q1",
                "edge": "evolved",
                "excerpt": (
                    "Our automotive design win pipeline now exceeds 8 "
                    "billion through fiscal 2027. Most recently, Volvo "
                    "Cars announced that it will use NVIDIA DRIVE Orin "
                    "building on our next great momentum with some of "
                    "the largest automakers including Mercedes Benz, "
                    "SAIC and Hyundai Motor Group."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Early-2020s clock met a next-chip Volvo cite, not "
                    "Xavier production delivery."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-gfn-telecom-launch",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "geforce-now",
        "title": "Launch GeForce NOW with SoftBank and LG UPlus this year",
        "objects": ("GeForce NOW", "GFN"),
        "seed": {
            "fiscal_period": "FY2020-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2020-Q4",
            "excerpt": (
                "we announced the GeForce NOW alliance expanding GFN "
                "through partnerships with the global telecom providers, "
                "SoftBank in Japan and LG UPlus in South Korea will be "
                "among the first to launch GFN later this year. NVIDIA, "
                "we'll develop the software and manage the service and "
                "share the subscription revenue with alliance partners."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2020-Q4",
                "edge": "delivered",
                "excerpt": (
                    "Last week, we launched our GeForce NOW cloud gaming "
                    "service. Powered by GeForce, GeForce NOW is the first "
                    "cloud gaming service to deliver ray trace games. It's "
                    "also the only open platform, so gamers can enjoy the "
                    "games they already have."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Launch cite covers the GFN service. Named telecom "
                    "partners are not restated."
                ),
                "delivery_basis": (
                    "FY2020-Q4 cite says NVIDIA launched GeForce NOW."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-arm-ai-hpc-stack",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "arm-software",
        "title": "NVIDIA AI and HPC software available to ARM by next year-end",
        "objects": ("ARM", "HPC software"),
        "seed": {
            "fiscal_period": "FY2020-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2021-Q4",
            "excerpt": (
                "we announced that by next year's end, we will make "
                "available to the ARM ecosystem NVIDIA's full stack of "
                "AI and HPC software, which accelerates more than 600 "
                "HPC applications and all AI frameworks. With this "
                "announcement, NVIDIA will accelerate all major CPU "
                "architectures, including x86, POWER and ARM."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2021-Q4",
                "edge": "silent",
                "clock": "FY2021-Q4",
            },
        ),
        "coverage_summary": "Slipped, not missed. No availability cite.",
    },
    {
        "tree_id": "nvda-every-query-accelerated",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "every-query",
        "title": "Every Internet query accelerated someday",
        "objects": ("every query", "natural language"),
        "seed": {
            "fiscal_period": "FY2020-Q4",
            "clock": None,
            "excerpt": (
                "I believe that every query on the Internet will be "
                "accelerated someday. And at the very core of it most -- "
                "almost all queries will have some natural language "
                "understanding component to it."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
        "coverage_summary": "Soft someday want. No clock.",
    },
    {
        "tree_id": "nvda-mercedes-2024-sdv",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "mercedes",
        "title": "Mercedes software-defined fleet starting in 2024",
        "objects": ("Mercedes", "DRIVE AGX"),
        "seed": {
            "fiscal_period": "FY2021-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q1",
            "excerpt": (
                "In June, we announced a landmark partnership with "
                "Mercedes-Benz, which starting in 2024 will launch "
                "software-defined intelligent vehicles across an entire "
                "fleet in using end-to-end NVIDIA technology. Mercedes "
                "will utilize NVIDIA's full technology stack, including "
                "the DRIVE AGX computer, DRIVE AV autonomous driving "
                "software and NVIDIA's AI infrastructure spanning from "
                "the core to the cloud."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q1",
                "edge": "restated",
                "clock": "FY2025-Q1",
                "excerpt": (
                    "Our automotive design win pipeline now exceeds 8 "
                    "billion through fiscal 2027. Most recently, Volvo "
                    "Cars announced that it will use NVIDIA DRIVE Orin "
                    "building on our next great momentum with some of "
                    "the largest automakers including Mercedes Benz, "
                    "SAIC and Hyundai Motor Group."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q1",
                "edge": "silent",
                "clock": "FY2025-Q1",
            },
        ),
        "coverage_summary": "Slipped, not missed. No 2024 launch cite.",
    },
    {
        "tree_id": "nvda-every-server-dpu",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "every-server",
        "title": "Every server will have a DPU someday",
        "objects": ("DPU", "every single server"),
        "seed": {
            "fiscal_period": "FY2021-Q3",
            "clock": None,
            "excerpt": (
                "I believe therefore that every single server in the "
                "world will have a DPU inside someday, just because we "
                "care so much about security and just because we care "
                "so much about throughput and TCO."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
        "coverage_summary": (
            "Soft someday want. Sibling of the later GPU-accelerated "
            "every-server goal, not the same object."
        ),
    },
    {
        "tree_id": "nvda-bluefield-oem",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "bluefield",
        "title": "BlueField-2 integrated into major OEM enterprise servers",
        "objects": ("BlueField", "BlueField-2"),
        "seed": {
            "fiscal_period": "FY2021-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We believe that over time DPUs will ship a millions of "
                "servers, unlocking a $10 billion total addressable "
                "market. BlueField-2 is sampling now with major "
                "hyperscale customers and will be integrated into the "
                "enterprise server offerings of major OEMs."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q1",
                "edge": "restated",
                "excerpt": (
                    "And then we expect next year to have meaningful, "
                    "if not significant revenues contribution from "
                    "BlueField, and this is going to be a really large "
                    "growth market for us. You can tell, I'm excited "
                    "about this."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2024-Q2",
                "edge": "delivered",
                "excerpt": (
                    "BlueField, as all of you know, is a project really "
                    "dear to my heart, and it's off to just a tremendous "
                    "start. I think it's a home run."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
                "coverage_summary": (
                    "Home-run cite treats BlueField as a live product "
                    "line, not a TAM."
                ),
                "delivery_basis": (
                    "FY2024-Q2 cite treats BlueField as off to a "
                    "tremendous start / home run."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-arm-general-ecosystem",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "arm-ecosystem",
        "title": "Create a broad general ARM ecosystem",
        "objects": ("ARM", "ecosystem"),
        "seed": {
            "fiscal_period": "FY2021-Q4",
            "clock": None,
            "excerpt": "we would love to build around the own processor and invest in building a great ecosystem around it. And so that all the world's peripherals and all the world's applications can work and – work on any one of the CPUs that we know today. And I want to start – we're going to start with high-performance computing...we've got to energize it with all of the ecosystem support. It can't just be on vertical applications, but we want to create a broad general ARM ecosystem.",
            "dimension": "competitive_position",
            "status": "composite",
        },
        "nodes": (),
        "coverage_summary": "Soft ecosystem want. No clock.",
    },
    {
        "tree_id": "nvda-grace-announce",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "three-chip",
        "title": "Announce Grace and the three-chip CPU / GPU / DPU stack",
        "objects": ("Grace", "three-chip"),
        "seed": {
            "fiscal_period": "FY2022-Q1",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": GRACE_SEED,
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2027-Q2",
                "edge": "silent",
                "clock": None,
            },
        ),
        "coverage_summary": (
            "Announce-time parent of the gold-window 3-chip delivery tree. "
            "FY2027-Q2 Grace Blackwell cite is not this announce."
        ),
    },
    {
        "tree_id": "nvda-omniverse-avatar-five-year",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "omniverse",
        "title": "Omniverse Avatar in retail within five years",
        "objects": ("Omniverse Avatar", "Omniverse"),
        "seed": {
            "fiscal_period": "FY2022-Q3",
            "clock": "FY2027-Q3",
            "excerpt": (
                "I believe Omniverse Avatar will be in drive-thrus and "
                "restaurants, fast food restaurants, check out with restaurants, "
                "in retail stores, all over the world within less than five years."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
        "coverage_summary": (
            "Soft five-year want. Clock sits after the gold window."
        ),
    },
    {
        "tree_id": "nvda-every-server-ai",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "every-server",
        "title": "Every server running AI / GPU-accelerated",
        "objects": ("every single server", "AI software"),
        "seed": {
            "fiscal_period": "FY2022-Q3",
            "clock": None,
            "excerpt": (
                "Every single server will be GPU accelerated some day. "
                "Today of all the clouds and all the enterprise, less "
                "than 10%. That kind of give you a sense of where you are."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q4",
                "edge": "restated",
                "excerpt": (
                    "There are some 20 million, 25 million servers that "
                    "are installed in the world today in enterprises, not "
                    "including clouds. We believe that every single server "
                    "in the future will be running AI software... There "
                    "are 40 million designers and creators around the "
                    "world. There are going to be hundreds of millions "
                    "of robots."
                ),
                "dimension": "competitive_position",
                "status": "anchored",
            },
        ),
        "coverage_summary": (
            "Soft someday want. No clock inside the gold window."
        ),
    },
    {
        "tree_id": "nvda-three-chip-strategy",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "three-chip",
        "title": "Deliver the 3-chip CPU / GPU / DPU strategy",
        "objects": ("3-chip", "Grace", "DPU"),
        "parent_tree_id": "nvda-grace-announce",
        "parent_seed_excerpt": GRACE_SEED,
        "seed": {
            "fiscal_period": "FY2022-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2023-Q2",
            "excerpt": THREE_CHIP_SEED,
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2023-Q1",
                "edge": "restated",
                "clock": "FY2023-Q2",
                "excerpt": (
                    "This week at COMPUTEX, we announced that dozens of "
                    "server models based on Grace will be brought to "
                    "market by the first wave of system builders, "
                    "including ASUS, Foxconn, Gigabyte, QCT, Supermicro "
                    "and Wiwynn."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2023-Q2",
                "edge": "delivered",
                "excerpt": (
                    "Grace is our first CPU. Top computer makers, "
                    "including Dell, HPE, Inspur, Lenovo and Supermicro "
                    "are adopting the new NVIDIA Grace CPU Superchip and "
                    "Grace Hopper Superchip to build the next generation "
                    "of supers."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "CPU leg entered the market with named OEM adoption. "
                    "GPU and DPU were already shipping."
                ),
                "delivery_basis": (
                    "FY2023-Q2 cite treats Grace Superchip as adopted "
                    "by major OEMs."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-opex-flat",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "opex",
        "title": "Keep operating expense relatively flat",
        "objects": ("operating expense",),
        "seed": {
            "fiscal_period": "FY2023-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2024-Q1",
            "excerpt": (
                "Sequentially, both GAAP and non-GAAP operating expense "
                "growth was in the single-digit percent, and we plan to "
                "keep it relatively flat at these levels over the "
                "coming quarters."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2023-Q4",
                "edge": "silent",
                "clock": "FY2024-Q1",
            },
            {
                "fiscal_period": "FY2024-Q1",
                "edge": "silent",
                "clock": "FY2024-Q1",
            },
        ),
        "coverage_summary": (
            "Coming-quarters clock came due with no later opex cite. "
            "Slipped, not missed."
        ),
    },
    {
        "tree_id": "nvda-spectrum-x-computex-announce",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "spectrum-x",
        "title": "Announce Ethernet AI product line at COMPUTEX",
        "objects": ("Spectrum-X", "Ethernet"),
        "seed": {
            "fiscal_period": "FY2024-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2024-Q2",
            "excerpt": SPECTRUM_X_ANNOUNCE_SEED,
            "dimension": "competitive_position",
            "status": "composite",
        },
        "nodes": (
            {
                "fiscal_period": "FY2024-Q2",
                "edge": "delivered",
                "excerpt": (
                    "we announced NVIDIA Spectrum-X, an accelerated "
                    "networking platform designed to optimize Ethernet "
                    "for AI workloads. Spectrum-X couples the Spectrum "
                    "or Ethernet switch with the BlueField-3 DPU, "
                    "achieving 1.5x better overall AI performance and "
                    "power efficiency versus traditional Ethernet."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "COMPUTEX-window cite treats Spectrum-X as announced."
                ),
                "delivery_basis": (
                    "FY2024-Q2 cite says NVIDIA announced Spectrum-X."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-spectrum-x-availability",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "spectrum-x",
        "title": "Spectrum-X available Q1 next year",
        "objects": ("Spectrum-X", "Spectrum X"),
        "parent_tree_id": "nvda-spectrum-x-computex-announce",
        "parent_seed_excerpt": SPECTRUM_X_ANNOUNCE_SEED,
        "seed": {
            "fiscal_period": "FY2024-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q1",
            "excerpt": SPECTRUM_X_AVAIL_SEED,
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2024-Q4",
                "edge": "restated",
                "clock": "FY2025-Q1",
                "excerpt": (
                    "We are now entering the ethernet networking space with "
                    "the launch of our new Spectrum-X end-to-end offering "
                    "designed for an AI-optimized networking for the data center."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q1",
                "edge": "delivered",
                "excerpt": (
                    "Spectrum-X is ramping in volume with multiple customers, "
                    "including a massive 100,000 GPU cluster. Spectrum-X opens "
                    "a brand-new market to NVIDIA networking and enables "
                    "Ethernet only data centers to accommodate large-scale AI."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Clock treated Spectrum-X as live volume, not a restated date."
                ),
                "delivery_basis": (
                    "FY2025-Q1 cite says Spectrum-X is ramping in volume "
                    "with a 100,000 GPU cluster."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-spectrum-x-multibillion",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "spectrum-x",
        "title": "Spectrum-X multibillion product line",
        "objects": ("Spectrum-X", "Spectrum X", "SpectrumX"),
        "parent_tree_id": "nvda-spectrum-x-availability",
        "parent_seed_excerpt": SPECTRUM_X_AVAIL_SEED,
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2026-Q1",
            "excerpt": (
                "We expect Spectrum-X to jump to a multibillion-dollar "
                "product line within a year."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2025-Q2",
                "edge": "restated",
                "excerpt": (
                    "Spectrum-X has broad market support from OEM and ODM "
                    "partners and is being adopted by CSPs, GPU cloud "
                    "providers, and enterprise, including X-AI to connect "
                    "the largest GPU compute cluster in the world."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q3",
                "edge": "restated",
                "excerpt": (
                    "NVIDIA Spectrum-X Ethernet for AI revenue increased "
                    "over 3 times year-on-year and our pipeline continues "
                    "to build with multiple CSPs and consumer Internet "
                    "companies planning large cluster deployments."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2026-Q1",
                "edge": "delivered",
                "excerpt": (
                    "Spectrum X posted strong sequential and year-on-year "
                    "growth and is now annualizing over $8 billion in revenue."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Within-a-year clock met: Spectrum-X annualizing over "
                    "$8 billion."
                ),
                "delivery_basis": (
                    "FY2026-Q1 cite prints an $8 billion annualized run rate."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-china-q4-decline",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "china-export",
        "title": "China / affected destinations decline in Q4",
        "objects": ("China",),
        "seed": {
            "fiscal_period": "FY2024-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2024-Q4",
            "excerpt": (
                "Our sales to China and other affected destinations derived "
                "from products that are now subject to licensing requirements "
                "have consistently contributed approximately 20% to 25% of "
                "Data Center revenue over the past few quarters. We expect "
                "that our sales to these destinations will decline "
                "significantly in the fourth quarter."
            ),
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2024-Q4",
                "edge": "delivered",
                "excerpt": (
                    "Although we have not received licenses from the U.S. "
                    "government to ship restricted products to China, we have "
                    "started shipping alternatives that don't require a license "
                    "for the China market. China represented a mid-single digit "
                    "percentage of our data center revenue in Q4."
                ),
                "dimension": "macro_regulatory_risk",
                "status": "verbatim",
                "coverage_summary": (
                    "Q4 print moved China from 20-25% of Data Center to "
                    "mid-single digits."
                ),
                "delivery_basis": (
                    "FY2024-Q4 cite reports mid-single-digit China mix "
                    "against the prior 20-25% run rate."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-dc-grow-through-2025",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "data-center",
        "title": "Data Center can grow through 2025",
        "objects": ("Data Center", "Blackwell"),
        "seed": {
            "fiscal_period": "FY2024-Q3",
            "clock": "FY2026-Q1",
            "excerpt": "Absolutely believe the Data Center can grow through 2025.",
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2026-Q1",
                "edge": "hit",
                "excerpt": (
                    "This is the start of a powerful new wave of growth. "
                    "Grace Blackwell is in full production. We're off to the "
                    "races. We now have multiple significant growth engines."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
                "coverage_summary": (
                    "FY2026-Q1 still described as a new growth wave with "
                    "Grace Blackwell in full production."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-dc-infra-doubling",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "data-center",
        "title": "Double the world's data-center installed base in five years",
        "objects": ("data center infrastructure",),
        "seed": {
            "fiscal_period": "FY2024-Q4",
            "clock": "FY2029-Q4",
            "excerpt": (
                "We believe these two trends will drive a doubling of the "
                "world's data center infrastructure installed base in the "
                "next five years and will represent an annual market "
                "opportunity in the hundreds of billions."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "nvda-blackwell-revenue-this-year",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "blackwell",
        "title": "A lot of Blackwell revenue this year",
        "objects": ("Blackwell",),
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q4",
            "excerpt": "We will see a lot of Blackwell revenue this year.",
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2025-Q2",
                "edge": "restated",
                "clock": "FY2025-Q4",
                "excerpt": (
                    "The change to the mask is complete. There were no "
                    "functional changes necessary. And so we're sampling "
                    "functional samples of Blackwell -- Grace Blackwell in "
                    "a variety of system configurations as we speak."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q3",
                "edge": "restated",
                "clock": "FY2025-Q4",
                "excerpt": (
                    "Blackwell demand is staggering and we are racing to "
                    "scale supply to meet the incredible demand customers "
                    "are placing on us."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q4",
                "edge": "delivered",
                "excerpt": (
                    "With Blackwell, it will be common for these clusters "
                    "to start with 100,000 GPUs or more. Shipments have "
                    "already started for multiple infrastructures of this size."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": (
                    "Year-end cite treats Blackwell as live shipments, "
                    "not a restated launch date."
                ),
                "delivery_basis": (
                    "FY2025-Q4 cite says shipments have already started "
                    "for multiple 100,000-GPU Blackwell infrastructures."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-sovereign-ai-this-year",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "sovereign-ai",
        "title": "Sovereign AI high-single-digit billions this year",
        "objects": ("Sovereign AI", "sovereign AI"),
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q4",
            "excerpt": SOVEREIGN_SEED,
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2025-Q2",
                "edge": "evolved",
                "clock": "FY2025-Q4",
                "objects": ("sovereign AI",),
                "excerpt": (
                    "We believe sovereign AI revenue will reach "
                    "low-double-digit billions this year."
                ),
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2025-Q3",
                "edge": "silent",
                "clock": "FY2025-Q4",
            },
            {
                "fiscal_period": "FY2025-Q4",
                "edge": "silent",
                "clock": "FY2025-Q4",
            },
        ),
    },
    {
        "tree_id": "nvda-ai-infra-3-4t",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "ai-infra",
        "title": "$3 to $4 trillion AI infrastructure by the end of the decade",
        "objects": ("AI infrastructure", "data centers"),
        "seed": {
            "fiscal_period": "FY2025-Q2",
            "clock": "FY2030-Q4",
            "excerpt": TRILLION_DC_SEED,
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2025-Q3",
                "edge": "restated",
                "clock": "FY2030-Q4",
                "excerpt": (
                    "I believe that there will be no digestion until we "
                    "modernize a trillion dollars with the data centers."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2026-Q2",
                "edge": "evolved",
                "clock": "FY2030-Q4",
                "excerpt": (
                    "We see $3 to $4 trillion in AI infrastructure spend by "
                    "the end of the decade. The scale and scope of these "
                    "build-outs present significant long-term growth "
                    "opportunities for NVIDIA Corporation."
                ),
                "dimension": "management_confidence",
                "status": "verbatim",
            },
        ),
    },
    {
        "tree_id": "nvda-record-next-year",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "record-year",
        "title": "Record-breaking next year",
        "objects": ("record-breaking year",),
        "seed": {
            "fiscal_period": "FY2026-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2027-Q4",
            "excerpt": (
                "This year is obviously a record-breaking year. I expect "
                "next year to be a record-breaking year."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (),
    },
    {
        "tree_id": "nvda-blackwell-china-access",
        "ticker": "NVDA",
        "kind": "goal",
        "beat_id": "china-export",
        "title": "Blackwell approved for China",
        "objects": ("Blackwell", "China"),
        "seed": {
            "fiscal_period": "FY2026-Q2",
            "clock": None,
            "excerpt": CHINA_WANT_SEED,
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "harden_to_tree_id": "nvda-h20-q3-ship",
        "nodes": (
            {
                "fiscal_period": "FY2026-Q3",
                "edge": "restated",
                "excerpt": (
                    "While we were disappointed in the current state, that "
                    "prevents us from shipping more competitive data center "
                    "compute products to China, we are committed to continued "
                    "engagement with the US and China governments. And will "
                    "continue to advocate for America's ability to compete "
                    "around the world."
                ),
                "dimension": "macro_regulatory_risk",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2026-Q4",
                "edge": "restated",
                "excerpt": (
                    "To sustain its leadership position in AI compute, America "
                    "must engage every developer and be the platform for choice "
                    "for every commercial business, including those in China. "
                    "We will continue to engage with the U.S. and China "
                    "government and advocate for America's ability to compete "
                    "around the world."
                ),
                "dimension": "macro_regulatory_risk",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2027-Q2",
                "edge": "silent",
                "clock": None,
            },
        ),
        "coverage_summary": (
            "FY2027-Q2 Grace Blackwell cite is not a China-access restatement."
        ),
    },
    {
        "tree_id": "nvda-h20-q3-ship",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "china-export",
        "title": "H20 $2 to $5 billion in Q3",
        "objects": ("H20", "H '20"),
        "parent_tree_id": "nvda-blackwell-china-access",
        "parent_seed_excerpt": CHINA_WANT_SEED,
        "seed": {
            "fiscal_period": "FY2026-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2026-Q3",
            "excerpt": (
                "If geopolitical issues reside, we should ship $2 to "
                "$5 billion in H20 revenue in Q3. And if we had more "
                "orders, we can bill more."
            ),
            "dimension": "macro_regulatory_risk",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2026-Q3",
                "edge": "missed",
                "excerpt": (
                    "H '20 sales were approximately $50 million. Sizable "
                    "purchase orders never materialized in the quarter due "
                    "to geopolitical issues and the increasingly competitive "
                    "market in China."
                ),
                "dimension": "macro_regulatory_risk",
                "status": "verbatim",
                "coverage_summary": (
                    "Q3 printed ~$50 million against a $2 to $5 billion clock."
                ),
                "delivery_basis": (
                    "FY2026-Q3 cite says sizable purchase orders never "
                    "materialized."
                ),
            },
        ),
    },
    {
        "tree_id": "nvda-aws-nvlink",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "nvlink",
        "title": "Enable AWS with NVLink",
        "objects": ("AWS", "NVLink"),
        "seed": {
            "fiscal_period": "FY2026-Q4",
            "claim_type": "forward_clock",
            "clock": "FY2027-Q4",
            "excerpt": (
                "In Q4, we announced that we will enable AWS with NVLink "
                "to integrate with their custom silicon."
            ),
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2027-Q1",
                "edge": "silent",
                "clock": "FY2027-Q4",
            },
        ),
    },
    {
        "tree_id": "nvda-fy26-shippable-compute",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "backlog",
        "title": "Additional compute shippable by fiscal year 2026",
        "objects": ("fiscal year '26", "shippable"),
        "seed": {
            "fiscal_period": "FY2026-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2026-Q4",
            "excerpt": (
                "The number will grow. And we will achieve, I'm sure, "
                "additional needs for compute that will be shippable "
                "by fiscal year '26."
            ),
            "dimension": "management_confidence",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2026-Q4",
                "edge": "silent",
                "clock": "FY2026-Q4",
            },
        ),
        "coverage_summary": (
            "FY26 clock came due with no later shippable cite. "
            "Slipped, not missed."
        ),
    },
    {
        "tree_id": "nvda-nvlink-fusion-partners",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "nvlink",
        "title": "Integrate Fujitsu, Intel, and Arm on NVLink Fusion",
        "objects": ("NVLink Fusion", "Fujitsu", "Fuzitsu"),
        "seed": {
            "fiscal_period": "FY2026-Q3",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": (
                "We announced a strategic collaboration with Suzuki in "
                "October where we will integrate Fuzitsu's CPUs and "
                "NVIDIA Corporation GPUs via NVLink Fusion... We also "
                "announced a collaboration with Intel to develop "
                "multiple generations of custom data center and PC "
                "products connecting NVIDIA Corporation and Intel's "
                "ecosystems using NVLink. This week at supercomputing "
                "25, Arm announced that it will be integrating NVLink "
                "IP for customers to build CPU SoCs that connect with "
                "NVIDIA Corporation."
            ),
            "dimension": "competitive_position",
            "status": "composite",
        },
        "nodes": (
            {
                "fiscal_period": "FY2026-Q4",
                "edge": "silent",
                "clock": None,
            },
            {
                "fiscal_period": "FY2027-Q1",
                "edge": "silent",
                "clock": None,
            },
        ),
        "coverage_summary": (
            "Dated partner integrations with no clock inside the window."
        ),
    },
    {
        "tree_id": "nvda-grok-architecture",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "grok",
        "title": "Extend NVIDIA architecture with Grok",
        "objects": ("Grok",),
        "seed": {
            "fiscal_period": "FY2026-Q4",
            "claim_type": "forward_clock",
            "clock": None,
            "excerpt": GROK_SEED,
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2027-Q1",
                "edge": "silent",
                "clock": None,
            },
            {
                "fiscal_period": "FY2027-Q2",
                "edge": "silent",
                "clock": None,
            },
        ),
        "coverage_summary": (
            "Open architecture-extend. Volume ship is the Groq 3 LPX child."
        ),
    },
    {
        "tree_id": "nvda-grok-3-lpx-volume",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "grok",
        "title": "Ship Groq 3 LPX in volume later this quarter",
        "objects": ("Groq 3 LPX", "Groq"),
        "parent_tree_id": "nvda-grok-architecture",
        "parent_seed_excerpt": GROK_SEED,
        "seed": {
            "fiscal_period": "FY2027-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2027-Q3",
            "excerpt": (
                "Groq 3 LPX, our first rack-scale LPU system, is in "
                "full production and already setting records, "
                "demonstrating nearly 4x the number of tokens per "
                "second against the next best alternative on our "
                "Artificial Analysis benchmark. We expect to ship "
                "Groq 3 LPX in volume later this quarter to early "
                "adopters."
            ),
            "dimension": "competitive_position",
            "status": "anchored",
        },
        "nodes": (),
        "coverage_summary": (
            "Clock sits in FY2027-Q3. Production is not volume shipment."
        ),
    },
    {
        "tree_id": "nvda-fcf-return-50",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "capital-return",
        "title": "Return roughly 50% of free cash flow this year",
        "objects": ("free cash flow", "shareholders"),
        "seed": {
            "fiscal_period": "FY2027-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2027-Q4",
            "excerpt": (
                "we are increasing our quarterly dividend from $0.01 "
                "to $0.20 per share... We are also announcing an $80 "
                "billion share repurchase authorization which is in "
                "addition to the $39 billion remaining on our current "
                "plan. As we indicated at GTC, we plan to return "
                "roughly 50% of free cash flow to shareholders this year."
            ),
            "dimension": "management_confidence",
            "status": "composite",
        },
        "nodes": (),
        "coverage_summary": (
            "This-year clock sits after the gold window."
        ),
    },
)
