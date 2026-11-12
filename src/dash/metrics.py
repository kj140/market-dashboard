"""Raw fetched data -> Metric objects with live/stale/manual/missing status.

No default values: an input that is absent yields status="missing", value=None.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

from .indicators import (
    as_of as truncate_asof,
    change_pct_days,
    drawdown_from_high,
    ratio_pct,
    streak_above,
    yoy_pct,
)
from .models import Metric

# Computation parameters fixed by the spec (6.1), not scoring thresholds.
US10Y_STREAK_LEVEL = 4.5
GDP_YOY_PERIODS = 4
CPI_YOY_PERIODS = 12
USDJPY_DAYS = 30

METRIC_FREQ: dict[str, str] = {
    "fg": "daily",
    "ndx_drop": "daily",
    "n225_drop": "daily",
    "sox_drop": "daily",
    "us10y": "daily",
    "us10y_streak": "daily",
    "wti": "daily",
    "usdjpy_1m": "daily",
    "effr": "daily",
    "cpi_yoy": "monthly",
    "gdp_yoy": "quarterly",
    "gdp_spread": "quarterly",
    "capex_gdp": "quarterly",
}

METRIC_LABELS: dict[str, tuple[str, str]] = {
    "fg": ("Fear & Greed", ""),
    "ndx_drop": ("NASDAQ100 高値からの下落率", "%"),
    "n225_drop": ("日経平均 高値からの下落率", "%"),
    "sox_drop": ("SOX 高値からの下落率", "%"),
    "us10y": ("米10年債利回り", "%"),
    "us10y_streak": ("米10年債 4.5%以上の連続日数", "日"),
    "gdp_yoy": ("名目GDP 前年同期比", "%"),
    "gdp_spread": ("名目GDP成長率 − 米10年債利回り", "%"),
    "cpi_yoy": ("CPI 前年同月比", "%"),
    "wti": ("WTI 原油", "ドル"),
    "usdjpy_1m": ("ドル円 1か月変化率", "%"),
    "capex_gdp": ("民間設備投資 / GDP", "%"),
    "effr": ("実効FF金利", "%"),
    "topix_per": ("TOPIX 予想PER", "倍"),
    "sox_per": ("SOX 予想PER", "倍"),
}


@dataclass
class RawData:
    closes: dict[str, pd.Series] = field(default_factory=dict)
    fred: dict[str, pd.Series] = field(default_factory=dict)
    fg: pd.Series | None = None
    errors: dict[str, str] = field(default_factory=dict)


def _missing(key: str) -> Metric:
    label, unit = METRIC_LABELS[key]
    return Metric(key=key, label=label, value=None, status="missing", as_of=None, unit=unit)


def _live(key: str, value: float | None, as_of: str | None, extra: dict | None = None) -> Metric:
    if value is None or as_of is None:
        return _missing(key)
    label, unit = METRIC_LABELS[key]
    return Metric(
        key=key, label=label, value=float(value), status="live",
        as_of=as_of, unit=unit, extra=extra or {},
    )


def _prep(s: pd.Series | None, asof: date | None) -> pd.Series | None:
    if s is None:
        return None
    s = s.dropna().sort_index()
    if asof is not None:
        s = truncate_asof(s, asof)
    return None if s.empty else s


def _last(s: pd.Series) -> str:
    return s.index[-1].date().isoformat()


def compute_metrics(
    raw: RawData, asof: date | None, manual: dict[str, Metric] | None
) -> dict[str, Metric]:
    closes = {k: _prep(v, asof) for k, v in raw.closes.items()}
    fred = {k: _prep(v, asof) for k, v in raw.fred.items()}
    fg = _prep(raw.fg, asof)

    out: dict[str, Metric] = {}

    out["fg"] = _live("fg", float(fg.iloc[-1]), _last(fg)) if fg is not None else _missing("fg")

    for key, sym in (("ndx_drop", "^NDX"), ("n225_drop", "^N225"), ("sox_drop", "^SOX")):
        s = closes.get(sym)
        dd = drawdown_from_high(s) if s is not None else None
        if dd is None:
            out[key] = _missing(key)
            continue
        extra = {"days": dd[1], "peak_date": dd[2]} if key == "sox_drop" else {}
        out[key] = _live(key, dd[0], _last(s), extra)

    dgs = fred.get("DGS10")
    if dgs is not None:
        out["us10y"] = _live("us10y", float(dgs.iloc[-1]), _last(dgs))
        out["us10y_streak"] = _live("us10y_streak", streak_above(dgs, US10Y_STREAK_LEVEL), _last(dgs))
    else:
        out["us10y"] = _missing("us10y")
        out["us10y_streak"] = _missing("us10y_streak")

    gdp = fred.get("GDP")
    gdp_yoy = yoy_pct(gdp, GDP_YOY_PERIODS) if gdp is not None else None
    out["gdp_yoy"] = _live("gdp_yoy", gdp_yoy, _last(gdp) if gdp is not None else None)

    if gdp_yoy is not None and dgs is not None:
        out["gdp_spread"] = _live(
            "gdp_spread", round(gdp_yoy - float(dgs.iloc[-1]), 2), min(_last(gdp), _last(dgs))
        )
    else:
        out["gdp_spread"] = _missing("gdp_spread")

    cpi = fred.get("CPIAUCSL")
    cpi_v = yoy_pct(cpi, CPI_YOY_PERIODS) if cpi is not None else None
    out["cpi_yoy"] = _live("cpi_yoy", cpi_v, _last(cpi) if cpi is not None else None)

    wti = closes.get("CL=F")
    out["wti"] = _live("wti", float(wti.iloc[-1]), _last(wti)) if wti is not None else _missing("wti")

    jpy = closes.get("JPY=X")
    jpy_v = change_pct_days(jpy, USDJPY_DAYS) if jpy is not None else None
    out["usdjpy_1m"] = _live("usdjpy_1m", jpy_v, _last(jpy) if jpy is not None else None)

    pnfi = fred.get("PNFI")
    capex = ratio_pct(pnfi, gdp) if pnfi is not None and gdp is not None else None
    out["capex_gdp"] = _live(
        "capex_gdp", capex, min(_last(pnfi), _last(gdp)) if capex is not None else None
    )

    effr = fred.get("EFFR")
    out["effr"] = _live("effr", float(effr.iloc[-1]), _last(effr)) if effr is not None else _missing("effr")

    if manual is not None:
        for key in ("topix_per", "sox_per"):
            if key in manual:
                out[key] = manual[key]

    return out


def carry_forward(
    current: dict[str, Metric],
    previous: dict[str, Metric] | None,
    limits: dict,
    freq: dict[str, str],
) -> dict[str, Metric]:
    """Replace missing metrics with the previous value (status stale) while within limits."""
    result = dict(current)
    if not previous:
        return result
    for key, cur in current.items():
        if cur.status != "missing" or key not in freq:
            continue
        prev = previous.get(key)
        if prev is None or prev.value is None or prev.status not in ("live", "stale"):
            continue
        evals = prev.stale_evals + 1
        if evals <= limits[freq[key]]:
            result[key] = replace(
                prev, status="stale", stale_evals=evals, extra=dict(prev.extra)
            )
    return result
