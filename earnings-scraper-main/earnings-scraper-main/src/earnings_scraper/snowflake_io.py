"""Snowflake connection + query execution (key-pair JWT auth).

Lifted from the proven ``Freischutz`` setup. Only used by the future
``scripts/pull_to_inbox.py`` puller; the manual inbox workflow never touches it.

Reaching ``*.snowflakecomputing.com`` requires network access that the default
Cursor sandbox does not grant — run the puller in a normal terminal, or invoke
the agent's shell with elevated network permission.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from . import config


def _load_private_key(path: str) -> bytes:
    """Load a PEM private key file and return DER (PKCS8) bytes."""
    from cryptography.hazmat.primitives import serialization

    with open(path, "rb") as f:
        pem_bytes = f.read()
    p_key = serialization.load_pem_private_key(pem_bytes, password=None)
    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def build_conn_params(**overrides: Any) -> dict[str, Any]:
    """Assemble ``snowflake.connector.connect()`` params from config/env."""
    key_path = overrides.pop("private_key_path", None) or config.SNOWFLAKE_PRIVATE_KEY_PATH
    if not key_path:
        raise RuntimeError("Set SNOWFLAKE_PRIVATE_KEY_PATH in the environment.")
    if not config.SNOWFLAKE_ACCOUNT or not config.SNOWFLAKE_USER:
        raise RuntimeError(
            "Set SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER (see scripts/env_setup.sh)."
        )
    params: dict[str, Any] = {
        "account": config.SNOWFLAKE_ACCOUNT,
        "user": config.SNOWFLAKE_USER,
        "warehouse": config.SNOWFLAKE_WAREHOUSE,
        "database": config.SNOWFLAKE_DATABASE,
        "schema": config.SNOWFLAKE_SCHEMA,
        "role": config.SNOWFLAKE_ROLE,
        "private_key": _load_private_key(key_path),
        "network_timeout": 300,
        "socket_timeout": 300,
    }
    params.update(overrides)
    return params


@contextmanager
def get_connection(**overrides: Any) -> Generator:
    """Context-managed Snowflake connection."""
    import snowflake.connector

    conn = snowflake.connector.connect(**build_conn_params(**overrides))
    try:
        yield conn
    finally:
        conn.close()


def execute_query(conn: Any, sql: str, params: dict[str, Any] | None = None):
    """Run a SELECT and return a pandas DataFrame.

    Fetches Arrow batches independently and normalizes every timestamp column to
    microseconds before concatenating — LSEG tables carry far-future sentinel
    dates (e.g. ``9999-12-31``) that overflow nanosecond resolution.
    """
    import pandas as pd

    cur = conn.cursor()
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        frames: list[pd.DataFrame] = []
        for batch in cur.fetch_pandas_batches():
            for col in batch.columns:
                if pd.api.types.is_datetime64_any_dtype(batch[col].dtype):
                    try:
                        batch[col] = batch[col].dt.as_unit("us")
                    except (AttributeError, ValueError):
                        pass
            frames.append(batch)
        if not frames:
            return pd.DataFrame(columns=[d[0] for d in (cur.description or [])])
        return pd.concat(frames, ignore_index=True)
    finally:
        cur.close()
