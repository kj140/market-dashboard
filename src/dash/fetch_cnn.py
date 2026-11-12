"""CNN Fear & Greed index (unofficial endpoint)."""
from __future__ import annotations

import pandas as pd

from dash.http import get_with_retry

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://edition.cnn.com/",
}


def fetch_fear_greed() -> pd.Series:
    """History if available, else a single-point series; raises on failure."""
    payload = get_with_retry(CNN_URL, headers=_HEADERS).json()
    points = (payload.get("fear_and_greed_historical") or {}).get("data") or []
    if points:
        idx = pd.DatetimeIndex(pd.to_datetime([p["x"] for p in points], unit="ms")).normalize()
        s = pd.Series([float(p["y"]) for p in points], index=idx)
        return s[~s.index.duplicated(keep="last")].sort_index()
    fg = payload["fear_and_greed"]
    if fg.get("timestamp"):
        ts = pd.Timestamp(fg["timestamp"])
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
    else:
        ts = pd.Timestamp.now()
    return pd.Series([float(fg["score"])], index=pd.DatetimeIndex([ts.normalize()]))
