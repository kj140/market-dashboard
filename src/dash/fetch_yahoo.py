"""Daily closes from Yahoo Finance via yfinance."""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Market-wide symbols only; the 7 tickers come from config/tickers.yaml.
MARKET_SYMBOLS = ["^GSPC", "^NDX", "^SOX", "^N225", "JPY=X", "CL=F"]

# Market facts (Ruling R21): before these local times today's bar is still moving, not a close.
# A small margin after the official close (15:30 / 16:00) lets the final price settle.
TOKYO_TZ = ZoneInfo("Asia/Tokyo")
TOKYO_CLOSED_AFTER = time(15, 45)
NEW_YORK_TZ = ZoneInfo("America/New_York")
NEW_YORK_CLOSED_AFTER = time(16, 15)


def _is_tokyo(sym: str) -> bool:
    return sym.endswith(".T") or sym == "^N225"


def _drop_unfinished_today(sym: str, close: pd.Series, now: datetime) -> pd.Series:
    tz, closed_after = (
        (TOKYO_TZ, TOKYO_CLOSED_AFTER) if _is_tokyo(sym) else (NEW_YORK_TZ, NEW_YORK_CLOSED_AFTER)
    )
    local = now.astimezone(tz)
    if local.time() > closed_after:
        return close
    today = pd.Timestamp(local.date())
    return close[close.index != today]


def fetch_closes(
    symbols: list[str], period: str = "2y", now: datetime | None = None
) -> dict[str, pd.Series]:
    """Return {symbol: close series}; failed or empty symbols are omitted.

    A row dated today (exchange local date) is dropped while that exchange is still open.
    """
    now = now if now is not None else datetime.now(timezone.utc)
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
            close = _drop_unfinished_today(sym, close, now)
            if close.empty:
                log.warning("yahoo: no finished closes for %s", sym)
                continue
            out[sym] = close
        except Exception as exc:  # one bad symbol must not stop the rest
            log.warning("yahoo: failed for %s: %s", sym, exc)
    return out
