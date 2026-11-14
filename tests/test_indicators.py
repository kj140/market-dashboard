from datetime import date

import pandas as pd

from dash.indicators import (
    as_of,
    change_pct_days,
    drawdown_from_high,
    ma_gap_pct,
    ratio_pct,
    streak_above,
    yoy_pct,
)


def _bdays(values, end="2026-01-09"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_drawdown_basic():
    s = _bdays([100, 120, 90])
    dd, days, peak = drawdown_from_high(s)
    assert (dd, days) == (25.0, 1)
    assert peak == s.index[1].date().isoformat()


def test_drawdown_short_history():
    s = _bdays([10, 12, 11, 9, 10])
    res = drawdown_from_high(s)
    assert res is not None
    assert res[0] == 16.7
    assert res[1] == 3


def test_drawdown_empty_returns_none():
    assert drawdown_from_high(pd.Series([], dtype=float, index=pd.DatetimeIndex([]))) is None


def test_drawdown_ignores_peak_older_than_window():
    idx = pd.DatetimeIndex(["2024-11-01", "2025-12-01", "2026-01-05"])
    s = pd.Series([200.0, 100.0, 90.0], index=idx)
    dd, days, peak = drawdown_from_high(s)
    assert dd == 10.0
    assert days == 1
    assert peak == "2025-12-01"


def test_streak_above_counts_consecutive():
    assert streak_above(_bdays([4.6, 4.4, 4.5, 4.6, 4.7]), 4.5) == 3
    assert streak_above(_bdays([4.6, 4.4]), 4.5) == 0


def test_yoy_pct_monthly():
    idx = pd.date_range("2025-01-01", periods=13, freq="MS")
    vals = [100.0] * 12 + [103.7]
    assert yoy_pct(pd.Series(vals, index=idx), 12) == 3.7


def test_yoy_pct_insufficient_none():
    idx = pd.date_range("2025-01-01", periods=12, freq="MS")
    assert yoy_pct(pd.Series([100.0] * 12, index=idx), 12) is None


def test_change_pct_days_yen():
    idx = pd.DatetimeIndex(["2025-12-01", "2025-12-31", "2026-01-30"])
    s = pd.Series([140.0, 150.0, 142.5], index=idx)
    assert change_pct_days(s, 30) == -5.0


def test_ratio_pct_aligns_dates():
    pnfi = pd.Series([14.2, 15.0], index=pd.DatetimeIndex(["2025-07-01", "2025-10-01"]))
    gdp = pd.Series([100.0], index=pd.DatetimeIndex(["2025-07-01"]))
    assert ratio_pct(pnfi, gdp) == 14.2


def test_ma_gap_pct():
    # 4 rows at 100 then 150: MA(5) = 110, last 150 -> +36.4%
    assert ma_gap_pct(_bdays([100, 100, 100, 100, 150]), 5) == 36.4
    # only the trailing window counts
    assert ma_gap_pct(_bdays([1000, 100, 100, 100, 100, 100]), 5) == 0.0
    assert ma_gap_pct(_bdays([100, 90]), 2) == -5.3


def test_ma_gap_pct_short_history_none():
    assert ma_gap_pct(_bdays([100, 100, 100]), 5) is None
    assert ma_gap_pct(_bdays([]), 5) is None


def test_as_of_truncates():
    s = _bdays([1, 2, 3, 4, 5], end="2026-01-09")
    out = as_of(s, date(2026, 1, 7))
    assert out.index[-1].date() == date(2026, 1, 7)
    assert len(out) == 3
