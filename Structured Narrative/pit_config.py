#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point-in-time mode defaults for the Structured Narrative pipeline."""
from __future__ import annotations

import os


def is_pit_mode() -> bool:
    """True unless NARRATIVE_PIT=0 explicitly disables PIT guardrails."""
    return os.getenv("NARRATIVE_PIT", "1").strip().lower() not in ("0", "false", "no", "off")


def pit_env() -> dict[str, str]:
    """Environment overrides for subprocess PIT runs."""
    env = {"NARRATIVE_PIT": "1"}
    if is_pit_mode():
        env["DIMENSION_RESCUE"] = "0"
    return env


def apply_pit_env(base: dict[str, str] | None = None) -> dict[str, str]:
    merged = dict(base or os.environ)
    if is_pit_mode():
        merged.update(pit_env())
    return merged
