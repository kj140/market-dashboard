"""Helpers that build small synthetic Series for tests."""
from __future__ import annotations

import pandas as pd


def daily(values: list[float], end: str = "2026-11-10") -> pd.Series:
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def monthly(values: list[float], end: str = "2026-09-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx, dtype=float)


def quarterly(values: list[float], end: str = "2026-04-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="QS")
    return pd.Series(values, index=idx, dtype=float)
