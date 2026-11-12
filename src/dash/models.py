from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["live", "stale", "manual", "missing"]


@dataclass
class Metric:
    key: str
    label: str
    value: float | None
    status: Status
    as_of: str | None
    unit: str = ""
    stale_evals: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class Contribution:
    key: str
    points: int | None


@dataclass
class AreaResult:
    area: str
    points: int
    ratio: int
    raw_ratio: int
    ratio_excl_manual: int
    on_hold: bool
    pending_down: int | None
    contributions: list[Contribution]
    missing: list[str]
    reason: str = ""
    prev_ratio: int | None = None


@dataclass
class TickerResult:
    symbol: str
    name: str
    area: str
    price: float | None
    drop_pct: float | None
    verdict: str
    reason: str = ""
    prev_verdict: str | None = None
