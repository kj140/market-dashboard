from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from .models import Metric

REQUIRED_RULE_KEYS = (
    "areas",
    "bands",
    "sox_combo",
    "ratio_steps",
    "verdict_table",
    "adjust",
    "stale_limits",
    "hold_missing_fraction",
)

MANUAL_KEYS = {
    "topix_per": "TOPIX 予想PER",
    "sox_per": "SOX 予想PER",
}


@dataclass
class TickerConfig:
    symbol: str
    name: str
    area: str
    note: str
    leveraged: bool = False
    cautious_when_area_ratio_ge: int | None = None


def _read_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_tickers(path: Path) -> list[TickerConfig]:
    data = _read_yaml(path)
    return [
        TickerConfig(
            symbol=str(t["symbol"]),
            name=t["name"],
            area=t["area"],
            note=t.get("note", ""),
            leveraged=bool(t.get("leveraged", False)),
            cautious_when_area_ratio_ge=t.get("cautious_when_area_ratio_ge"),
        )
        for t in data["tickers"]
    ]


def load_rules(path: Path) -> dict:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"rules file is not a mapping: {path}")
    missing = [k for k in REQUIRED_RULE_KEYS if k not in data]
    if missing:
        raise ValueError(f"rules file missing keys: {missing}")
    return data


def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            return None
    return None


def _missing(key: str) -> Metric:
    return Metric(key=key, label=MANUAL_KEYS[key], value=None,
                  status="missing", as_of=None, unit="倍")


def load_manual(path: Path, today: date, overdue_days: int) -> dict[str, Metric]:
    try:
        data = _read_yaml(path)
    except (OSError, yaml.YAMLError):
        data = None
    if not isinstance(data, dict):
        data = {}
    out: dict[str, Metric] = {}
    for key in MANUAL_KEYS:
        entry = data.get(key)
        if not isinstance(entry, dict):
            out[key] = _missing(key)
            continue
        value = entry.get("value")
        updated = _to_date(entry.get("updated"))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or updated is None:
            out[key] = _missing(key)
            continue
        days = (today - updated).days
        out[key] = Metric(
            key=key, label=MANUAL_KEYS[key], value=float(value),
            status="manual", as_of=updated.isoformat(), unit="倍",
            extra={"days_since_update": days, "overdue": days > overdue_days},
        )
    return out
