"""Daily closes from Yahoo Finance via yfinance."""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Market-wide symbols only; the 7 tickers come from config/tickers.yaml.
MARKET_SYMBOLS = ["^GSPC", "^NDX", "^SOX", "^N225", "JPY=X", "CL=F"]


def fetch_closes(symbols: list[str], period: str = "2y") -> dict[str, pd.Series]:
    """Return {symbol: close series}; failed or empty symbols are omitted."""
    out: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period=period, interval="1d")
            close = hist["Close"].dropna().astype(float)
            if close.empty:
                log.warning("yahoo: no data for %s", sym)
                continue
            idx = pd.DatetimeIndex(close.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            close.index = idx.normalize()
            close = close[~close.index.duplicated(keep="last")].sort_index()
            out[sym] = close
        except Exception as exc:  # one bad symbol must not stop the rest
            log.warning("yahoo: failed for %s: %s", sym, exc)
    return out
