#!/usr/bin/env bash
# earnings-scraper environment setup.
#
# Only needed for the FUTURE Snowflake -> inbox puller (scripts/pull_to_inbox.py).
# The manual inbox workflow (drop files in inbox/, let the coordinator crunch
# them) needs none of this.
#
# Usage:  source scripts/env_setup.sh

# Snowflake connection (same account/key as the sibling Freischutz repo).
export SNOWFLAKE_ACCOUNT="${SNOWFLAKE_ACCOUNT:-CKJIEDY-JBC56909}"
# key-pair JWT auth resolves the user by LOGIN_NAME:
export SNOWFLAKE_USER="${SNOWFLAKE_USER:-NHIRT@CASSIUSCAP.COM}"
export SNOWFLAKE_WAREHOUSE="${SNOWFLAKE_WAREHOUSE:-INTERN_WH}"
export SNOWFLAKE_ROLE="${SNOWFLAKE_ROLE:-INTERN}"
export SNOWFLAKE_DATABASE="${SNOWFLAKE_DATABASE:-}"
export SNOWFLAKE_SCHEMA="${SNOWFLAKE_SCHEMA:-PUBLIC}"

# Resolve repo root whether sourced from bash or zsh.
SCRIPT_SRC="${BASH_SOURCE[0]:-${(%):-%x}}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SRC")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

export SNOWFLAKE_PRIVATE_KEY_PATH="${SNOWFLAKE_PRIVATE_KEY_PATH:-$REPO_ROOT/secrets/snowflake_key.p8}"
export PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}"

# LSEG StreetEvents Transcripts share — fill in once provisioned (see config.py).
export EARNINGS_LSEG_TRANSCRIPT_DB="${EARNINGS_LSEG_TRANSCRIPT_DB:-}"

# Transcript fetcher (scripts/fetch_transcripts.py). Get a free ROIC.ai key at
# https://roic.ai and export it (or put it in .env). Stored under secrets/ by
# convention if you prefer a file: export ROIC_API_KEY="$(cat "$REPO_ROOT/secrets/roic_api")"
export ROIC_API_KEY="${ROIC_API_KEY:-}"
export SEC_USER_AGENT="${SEC_USER_AGENT:-earnings-scraper (contact: nhirt@cassiuscap.com)}"

# Anthropic key for headless extraction (stream driver="claude"). The Anthropic
# SDK reads it from the env, so load it from secrets/anthropic_api if it isn't
# already exported. (Only export when a value exists — never an empty string.)
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$REPO_ROOT/secrets/anthropic_api" ]; then
  export ANTHROPIC_API_KEY="$(cat "$REPO_ROOT/secrets/anthropic_api")"
fi

echo "[earnings-scraper] env loaded (account=$SNOWFLAKE_ACCOUNT, user=$SNOWFLAKE_USER, wh=$SNOWFLAKE_WAREHOUSE)"
