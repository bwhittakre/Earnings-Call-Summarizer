"""Gitignored Rank IC Lab recipe + experiment-log store.

Lives beside the operational DB under ``services/earnings_monitor/state/``
(already gitignored). Lab never writes ``config/signal_packs/``.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .data import default_operational_db_path
from .sectors import ALL_COMPANIES, CUSTOM_LIST

STORE_VERSION = 1
VALID_TAGS = ("good", "bad")


class LabStoreError(Exception):
    """Store file exists but cannot be read; refuse to overwrite it."""


def default_lab_store_path() -> Path:
    configured = os.environ.get("EARNINGS_MONITOR_LAB_STORE")
    if configured:
        return Path(configured).expanduser()
    return Path(default_operational_db_path()).expanduser().parent / "rank_ic_lab.json"


def universe_key(sector_choice: str | None, tickers: Sequence[str] | None = None) -> str:
    """Stable recipe namespace: ``all``, a sector stem, or ``custom:<hash>``."""
    if not sector_choice or sector_choice == ALL_COMPANIES:
        return "all"
    if sector_choice == CUSTOM_LIST:
        joined = ",".join(sorted(str(t).strip().upper() for t in (tickers or ()) if str(t).strip()))
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
        return f"custom:{digest}"
    return str(sector_choice)


def empty_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "recipes": [], "trials": []}


def _unreadable_message(store_path: Path) -> str:
    return (
        f"Lab store exists but is unreadable ({store_path}). "
        "Fix or move the file before saving — refusing to overwrite it."
    )


def _read_store_payload(store_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabStoreError(_unreadable_message(store_path)) from exc
    if not isinstance(payload, dict):
        raise LabStoreError(_unreadable_message(store_path))
    return payload


def load_lab_store(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    store_path = Path(path or default_lab_store_path())
    if not store_path.is_file():
        return empty_store()
    payload = _read_store_payload(store_path)
    recipes = payload.get("recipes")
    trials = payload.get("trials")
    return {
        "version": int(payload.get("version") or STORE_VERSION),
        "recipes": list(recipes) if isinstance(recipes, list) else [],
        "trials": list(trials) if isinstance(trials, list) else [],
    }


def save_lab_store(
    payload: Mapping[str, Any],
    path: str | os.PathLike[str] | None = None,
) -> Path:
    store_path = Path(path or default_lab_store_path())
    if store_path.is_file():
        _read_store_payload(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "version": int(payload.get("version") or STORE_VERSION),
        "recipes": list(payload.get("recipes") or []),
        "trials": list(payload.get("trials") or []),
    }
    tmp = store_path.with_suffix(store_path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, store_path)
    return store_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def recipes_for(store: Mapping[str, Any], universe_key_value: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in store.get("recipes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("universe_key") or "") == universe_key_value:
            out.append(dict(row))
    out.sort(key=lambda r: str(r.get("saved_at") or ""), reverse=True)
    return out


def get_recipe(store: Mapping[str, Any], recipe_id: str) -> dict[str, Any] | None:
    want = str(recipe_id or "")
    if not want:
        return None
    for row in store.get("recipes") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == want:
            return dict(row)
    return None


def upsert_recipe(
    store: dict[str, Any],
    *,
    name: str,
    universe_key_value: str,
    label: str,
    horizon: str,
    dimension: str,
    weights: Mapping[str, float],
    include_revision: bool,
    recipe_id: str | None = None,
) -> dict[str, Any]:
    cleaned_name = str(name or "").strip() or "Untitled recipe"
    cleaned_weights = {str(k): float(v) for k, v in dict(weights).items()}
    recipes = [r for r in (store.get("recipes") or []) if isinstance(r, dict)]
    existing: dict[str, Any] | None = None
    if recipe_id:
        existing = next((r for r in recipes if str(r.get("id")) == recipe_id), None)
    if existing is None:
        existing = next(
            (
                r
                for r in recipes
                if str(r.get("name") or "") == cleaned_name
                and str(r.get("universe_key") or "") == universe_key_value
            ),
            None,
        )
    if existing is None:
        existing = {
            "id": recipe_id or _new_id(),
        }
        recipes.append(existing)
    existing.update(
        {
            "name": cleaned_name,
            "universe_key": universe_key_value,
            "label": str(label),
            "horizon": str(horizon),
            "dimension": str(dimension),
            "weights": cleaned_weights,
            "include_revision": bool(include_revision),
            "saved_at": _now_iso(),
        }
    )
    store["recipes"] = recipes
    return dict(existing)


def append_trial(
    store: dict[str, Any],
    *,
    recipe: Mapping[str, Any],
    lab_stats: Mapping[str, Any],
    baseline_stats: Mapping[str, Any],
    tag: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    cleaned_tag = str(tag or "").strip().lower() or None
    if cleaned_tag not in VALID_TAGS:
        cleaned_tag = None
    trial = {
        "id": _new_id(),
        "logged_at": _now_iso(),
        "recipe_id": recipe.get("id"),
        "recipe_name": recipe.get("name"),
        "universe_key": recipe.get("universe_key"),
        "label": recipe.get("label"),
        "horizon": recipe.get("horizon"),
        "dimension": recipe.get("dimension"),
        "weights": dict(recipe.get("weights") or {}),
        "include_revision": bool(recipe.get("include_revision")),
        "lab": dict(lab_stats),
        "baseline": dict(baseline_stats),
        "tag": cleaned_tag,
        "notes": str(notes).strip() if notes else None,
    }
    trials = [t for t in (store.get("trials") or []) if isinstance(t, dict)]
    trials.append(trial)
    store["trials"] = trials
    return dict(trial)


def trials_for(
    store: Mapping[str, Any],
    universe_key_value: str | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = [dict(t) for t in (store.get("trials") or []) if isinstance(t, dict)]
    if universe_key_value is not None:
        rows = [t for t in rows if str(t.get("universe_key") or "") == universe_key_value]
    rows.sort(key=lambda t: str(t.get("logged_at") or ""), reverse=True)
    if limit is not None:
        rows = rows[: int(limit)]
    return rows
