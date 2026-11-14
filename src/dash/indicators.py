"""Pure indicator calculations. No I/O, no network."""
from __future__ import annotations

from datetime import date

import pandas as pd


def _clean(s: pd.Series) -> pd.Series:
    return s.dropna().sort_index()


def drawdown_from_high(
    closes: pd.Series, window_days: int = 365
) -> tuple[float, int, str] | None:
    s = _clean(closes)
    if s.empty:
        return None
    cutoff = s.index[-1] - pd.Timedelta(days=window_days)
    w = s[s.index >= cutoff]
    peak_pos = int(w.values.argmax())
    peak_val = float(w.iloc[peak_pos])
    if peak_val <= 0:
        return None
    last = float(w.iloc[-1])
    dd = round((peak_val - last) / peak_val * 100, 1)
    days = len(w) - 1 - peak_pos
    return dd, days, w.index[peak_pos].date().isoformat()


def streak_above(series: pd.Series, threshold: float) -> int:
    s = _clean(series)
    n = 0
    for v in reversed(s.values):
        if v >= threshold:
            n += 1
        else:
            break
    return n


def yoy_pct(series: pd.Series, periods: int) -> float | None:
    s = _clean(series)
    if len(s) <= periods:
        return None
    base = float(s.iloc[-1 - periods])
    if base == 0:
        return None
    return round((float(s.iloc[-1]) / base - 1) * 100, 2)


def change_pct_days(series: pd.Series, days: int) -> float | None:
    s = _clean(series)
    if s.empty:
        return None
    target = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= target]
    if past.empty:
        return None
    base = float(past.iloc[-1])
    if base == 0:
        return None
    return round((float(s.iloc[-1]) / base - 1) * 100, 2)


def ratio_pct(numer: pd.Series, denom: pd.Series) -> float | None:
    n, d = _clean(numer), _clean(denom)
    common = n.index.intersection(d.index)
    if len(common) == 0:
        return None
    latest = common.max()
    dv = float(d.loc[latest])
    if dv == 0:
        return None
    return round(float(n.loc[latest]) / dv * 100, 1)


def ma_gap_pct(series: pd.Series, window: int) -> float | None:
    """Last value's % distance from its trailing `window`-row simple moving average."""
    s = _clean(series)
    if len(s) < window:
        return None
    ma = float(s.iloc[-window:].mean())
    if ma == 0:
        return None
    return round((float(s.iloc[-1]) / ma - 1) * 100, 1)


def as_of(series: pd.Series, d: date) -> pd.Series:
    return series[series.index <= pd.Timestamp(d)]
