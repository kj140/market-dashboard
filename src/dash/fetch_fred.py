"""FRED official API."""
from __future__ import annotations

import pandas as pd
import requests

from dash.http import get_with_retry

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = ["DGS10", "GDP", "CPIAUCSL", "EFFR", "PNFI"]


def fetch_fred(series_id: str, api_key: str, start: str = "2023-01-01") -> pd.Series:
    """Fetch one series; raises on failure (caller marks the metric missing)."""
    if not api_key:
        raise RuntimeError("FRED api key is not set")
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    try:
        payload = get_with_retry(FRED_URL, params=params).json()
    except requests.RequestException as exc:
        # str(exc) can embed the request URL (with the key); never propagate it.
        raise RuntimeError(f"FRED request failed for {series_id}: {type(exc).__name__}") from None
    dates, values = [], []
    for obs in payload.get("observations", []):
        if obs.get("value") in (None, "."):
            continue
        dates.append(pd.Timestamp(obs["date"]))
        values.append(float(obs["value"]))
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).sort_index()
