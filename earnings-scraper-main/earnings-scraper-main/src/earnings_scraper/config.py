"""Configuration + environment resolution.

Credentials come from environment variables (see ``scripts/env_setup.sh`` and
``.env.example``). Nothing here is required for the manual inbox workflow; these
settings only feed the future Snowflake -> inbox puller.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_secret_file(name: str) -> str:
    """Read a trimmed credential from ``secrets/<name>`` (empty if absent).

    Mirrors the repo convention for ``cursor_api`` / ``zotero_api``: a key can
    live either in an environment variable or as a one-line file under secrets/.
    """
    try:
        return (REPO_ROOT / "secrets" / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

# ---- Local folders ----
INBOX_DIR = Path(os.environ.get("EARNINGS_INBOX", REPO_ROOT / "inbox"))
PROCESSED_DIR = Path(os.environ.get("EARNINGS_PROCESSED", REPO_ROOT / "inbox" / "_processed"))

# ---- Snowflake connection (future puller; mirrors the proven Freischutz setup) ----
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER", "")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "INTERN_WH")
SNOWFLAKE_ROLE = os.environ.get("SNOWFLAKE_ROLE", "INTERN")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "")
SNOWFLAKE_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC")
SNOWFLAKE_PRIVATE_KEY_PATH = os.environ.get(
    "SNOWFLAKE_PRIVATE_KEY_PATH",
    str(REPO_ROOT / "secrets" / "snowflake_key.p8"),
)

# ---- LSEG StreetEvents Transcripts & Briefs share ----
# PLACEHOLDER: fill in once the share is provisioned to the account. The current
# entitlement (probed 2026-07-08) has NO transcript share — only estimates/factor
# data (A770_RA, A822, MSCI). Update these when the transcript share lands.
LSEG_TRANSCRIPT_DB = os.environ.get("EARNINGS_LSEG_TRANSCRIPT_DB", "")
LSEG_TRANSCRIPT_SCHEMA = os.environ.get("EARNINGS_LSEG_TRANSCRIPT_SCHEMA", "DBO")

# ---- ROIC.ai earnings-call transcripts (primary fetcher) ----
# Free tier: 5 requests/minute, 2 years of history, all public companies.
# Docs: https://www.roic.ai/api/docs/earnings-calls  (key = ``apikey`` query param)
# Key resolves from $ROIC_API_KEY, falling back to the secrets/roic_api file.
ROIC_API_KEY = os.environ.get("ROIC_API_KEY", "") or _read_secret_file("roic_api")
ROIC_BASE_URL = os.environ.get("ROIC_BASE_URL", "https://api.roic.ai/v2")
# Seconds to space between ROIC requests to stay under the free-tier 5 req/min
# cap (60 / 5 = 12s; 13s gives a small safety margin). Set to 0 to disable.
ROIC_MIN_REQUEST_INTERVAL = float(os.environ.get("ROIC_MIN_REQUEST_INTERVAL", "13"))

# ---- SEC EDGAR fallback ----
# EDGAR requires a descriptive User-Agent that identifies the requester with a
# contact email (see https://www.sec.gov/os/webmaster-faq#developers). Override
# SEC_USER_AGENT with your own contact before running against SEC at any volume.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "earnings-scraper (contact: nhirt@cassiuscap.com)",
)

# ---- Anthropic API (headless extraction via stream driver="claude") ----
# The Anthropic SDK reads ANTHROPIC_API_KEY from the environment. Resolve it from
# the env var, falling back to the secrets/anthropic_api file, and export it back
# into the environment so the stream/anthropic SDK picks it up whenever this
# package is imported before the driver runs.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "") or _read_secret_file("anthropic_api")
if ANTHROPIC_API_KEY and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
