from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_EDGAR_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "config" / "edgar.yaml"
)


@dataclass(frozen=True)
class EdgarConfig:
    user_agent: str
    rate_limit_rps: float
    earnings_8k_window_days: int
    company_folders: dict[str, str]
    company_names: dict[str, str]


def load_edgar_config(path: Path = DEFAULT_EDGAR_CONFIG_PATH) -> EdgarConfig:
    if not path.is_file():
        raise FileNotFoundError(f"EDGAR config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid EDGAR config: {path}")
    folders = raw.get("company_folders") or {}
    names = raw.get("company_names") or folders
    return EdgarConfig(
        user_agent=str(raw.get("user_agent", "")).strip(),
        rate_limit_rps=float(raw.get("rate_limit_rps", 8)),
        earnings_8k_window_days=int(raw.get("earnings_8k_window_days", 45)),
        company_folders={k.upper(): str(v) for k, v in folders.items()},
        company_names={k.upper(): str(v) for k, v in names.items()},
    )
