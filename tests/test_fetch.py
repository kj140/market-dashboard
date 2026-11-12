import datetime

import pandas as pd
import pytest
import requests

from dash import fetch_cnn, fetch_fred, fetch_yahoo, http


class FakeResp:
    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


def test_get_with_retry_retries_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return FakeResp({"ok": 1})

    monkeypatch.setattr(http.requests, "get", fake_get)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    resp = http.get_with_retry("http://x")
    assert resp.json() == {"ok": 1}
    assert len(calls) == 2


def test_get_with_retry_raises_after_all_fail(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        raise requests.Timeout("slow")

    monkeypatch.setattr(http.requests, "get", fake_get)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(requests.Timeout):
        http.get_with_retry("http://x", retries=2)
    assert len(calls) == 3


def test_fetch_fred_drops_dot_values(monkeypatch):
    payload = {"observations": [
        {"date": "2026-10-01", "value": "4.5"},
        {"date": "2026-10-02", "value": "."},
    ]}
    monkeypatch.setattr(fetch_fred, "get_with_retry", lambda *a, **k: FakeResp(payload))
    s = fetch_fred.fetch_fred("DGS10", "k")
    assert len(s) == 1
    assert s.iloc[0] == 4.5


def test_fetch_fred_error_does_not_leak_key(monkeypatch):
    def boom(*a, **k):
        raise requests.HTTPError("403 for url: https://x?api_key=SECRETKEY")

    monkeypatch.setattr(fetch_fred, "get_with_retry", boom)
    with pytest.raises(RuntimeError) as ei:
        fetch_fred.fetch_fred("DGS10", "SECRETKEY")
    assert "SECRETKEY" not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_fetch_fred_without_key_raises():
    with pytest.raises(RuntimeError):
        fetch_fred.fetch_fred("DGS10", "")


def test_fetch_fear_greed_uses_history(monkeypatch):
    payload = {
        "fear_and_greed": {"score": 50},
        "fear_and_greed_historical": {"data": [
            {"x": 1760000000000, "y": 40.0},
            {"x": 1760086400000, "y": 45.5},
        ]},
    }
    seen = {}

    def fake(url, **kw):
        seen.update(kw)
        return FakeResp(payload)

    monkeypatch.setattr(fetch_cnn, "get_with_retry", fake)
    s = fetch_cnn.fetch_fear_greed()
    assert len(s) == 2
    assert s.index.tz is None
    assert "User-Agent" in seen["headers"]
    assert seen["headers"]["Referer"] == "https://edition.cnn.com/"


def test_fetch_fear_greed_falls_back_to_score(monkeypatch):
    payload = {"fear_and_greed": {"score": 61.2, "timestamp": "2026-11-11T23:59:00+00:00"}}
    monkeypatch.setattr(fetch_cnn, "get_with_retry", lambda *a, **k: FakeResp(payload))
    s = fetch_cnn.fetch_fear_greed()
    assert len(s) == 1 and s.iloc[0] == 61.2


def test_fetch_closes_skips_failed_symbol(monkeypatch):
    idx = pd.DatetimeIndex(["2026-11-10 00:00", "2026-11-11 00:00"], tz="America/New_York")

    class FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period, interval):
            if self.sym == "285A.T":
                raise RuntimeError("boom")
            if self.sym == "EMPTY":
                return pd.DataFrame({"Close": []})
            return pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)

    monkeypatch.setattr(fetch_yahoo.yf, "Ticker", FakeTicker)
    out = fetch_yahoo.fetch_closes(["^SOX", "285A.T", "EMPTY"])
    assert list(out) == ["^SOX"]
    assert out["^SOX"].index.tz is None
    assert len(out["^SOX"]) == 2


def test_fetch_fred_missing_observations_raises(monkeypatch):
    monkeypatch.setattr(fetch_fred, "get_with_retry", lambda *a, **k: FakeResp({"error_message": "bad"}))
    with pytest.raises(RuntimeError):
        fetch_fred.fetch_fred("DGS10", "k")


def test_fetch_fred_all_dots_raises(monkeypatch):
    payload = {"observations": [{"date": "2026-10-01", "value": "."}]}
    monkeypatch.setattr(fetch_fred, "get_with_retry", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError):
        fetch_fred.fetch_fred("DGS10", "k")


def test_fetch_fear_greed_no_history_no_timestamp_raises(monkeypatch):
    monkeypatch.setattr(fetch_cnn, "get_with_retry", lambda *a, **k: FakeResp({"fear_and_greed": {"score": 50}}))
    with pytest.raises(RuntimeError):
        fetch_cnn.fetch_fear_greed()


def _ticker_with_rows(dates, tz):
    idx = pd.DatetimeIndex(dates, tz=tz)

    class FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period, interval):
            return pd.DataFrame({"Close": [float(i + 1) for i in range(len(idx))]}, index=idx)

    return FakeTicker


@pytest.mark.parametrize("sym, tz, before, after", [
    # Tokyo closes 15:45 JST (= 06:45 UTC); New York closes 16:15 ET (= 21:15 UTC in November).
    ("6146.T", "Asia/Tokyo", "2026-11-12 06:00", "2026-11-12 07:00"),
    ("^N225", "Asia/Tokyo", "2026-11-12 06:00", "2026-11-12 07:00"),
    ("NVDA", "America/New_York", "2026-11-12 20:00", "2026-11-12 21:30"),
])
def test_fetch_closes_drops_today_before_exchange_close(monkeypatch, sym, tz, before, after):
    rows = ["2026-11-10 00:00", "2026-11-11 00:00", "2026-11-12 00:00"]
    monkeypatch.setattr(fetch_yahoo.yf, "Ticker", _ticker_with_rows(rows, tz))
    utc = datetime.timezone.utc

    early = fetch_yahoo.fetch_closes([sym], now=datetime.datetime.fromisoformat(before).replace(tzinfo=utc))
    assert [d.date().isoformat() for d in early[sym].index] == ["2026-11-10", "2026-11-11"]
    assert list(early[sym]) == [1.0, 2.0]

    late = fetch_yahoo.fetch_closes([sym], now=datetime.datetime.fromisoformat(after).replace(tzinfo=utc))
    assert [d.date().isoformat() for d in late[sym].index] == ["2026-11-10", "2026-11-11", "2026-11-12"]


def test_fetch_closes_keeps_rows_when_today_has_no_bar(monkeypatch):
    rows = ["2026-11-10 00:00", "2026-11-11 00:00"]
    monkeypatch.setattr(fetch_yahoo.yf, "Ticker", _ticker_with_rows(rows, "America/New_York"))
    now = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=datetime.timezone.utc)  # 10:00 ET
    out = fetch_yahoo.fetch_closes(["NVDA"], now=now)
    assert len(out["NVDA"]) == 2
