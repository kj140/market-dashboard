import json
import math
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import dash.__main__ as cli
from dash.history import load_history, save_history
from dash.pipeline import Fetchers, run_backfill, run_daily

REPO = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
MANUAL_OK = (
    "topix_per: {value: 15.0, updated: 2026-11-01}\n"
    "sox_per: {value: 18.0, updated: 2026-11-01}\n"
)


def make_root(tmp_path: Path, manual: str = MANUAL_OK) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    for name in ("rules.yaml", "tickers.yaml"):
        shutil.copy(REPO / "config" / name, cfg / name)
    (cfg / "manual.yaml").write_text(manual, encoding="utf-8")
    return tmp_path


def _wave(idx: pd.DatetimeIndex, base: float) -> pd.Series:
    return pd.Series(
        [base * (1 + 0.2 * math.sin(i / 25)) for i in range(len(idx))], index=idx, dtype=float
    )


def make_fetchers(end: str, n: int = 400, fg_fail: bool = False, fg_value: float = 42.0,
                  skip: tuple[str, ...] = ("285A.T",)) -> Fetchers:
    idx = pd.bdate_range(end=end, periods=n)

    def closes(symbols):
        return {s: _wave(idx, 100.0 + i) for i, s in enumerate(symbols) if s not in skip}

    def fred(series_id):
        if series_id in ("DGS10", "EFFR"):
            return pd.Series([4.2] * n, index=idx, dtype=float)
        if series_id == "CPIAUCSL":
            m = pd.date_range(end="2026-09-01", periods=24, freq="MS")
            return pd.Series([300.0 + i for i in range(24)], index=m, dtype=float)
        q = pd.date_range(end="2026-04-01", periods=12, freq="QS")
        base = 100.0 if series_id == "GDP" else 15.0
        return pd.Series([base + i for i in range(12)], index=q, dtype=float)

    def fear_greed():
        if fg_fail:
            raise RuntimeError("blocked by CNN")
        return pd.Series([fg_value] * n, index=idx, dtype=float)

    return Fetchers(closes=closes, fred=fred, fear_greed=fear_greed)


def read_latest(root: Path) -> dict:
    return json.loads((root / "docs" / "data" / "latest.json").read_text(encoding="utf-8"))


def at(day: int) -> datetime:
    return datetime(2026, 11, day, 6, 30, tzinfo=JST)


def test_first_run_writes_latest_no_notifications(tmp_path):
    root = make_root(tmp_path)
    sent = []
    run_daily(root, make_fetchers("2026-11-11"), at(12), lambda s, b: sent.append(s))
    latest = read_latest(root)
    history = load_history(root / "docs" / "data" / "history.json")
    assert sent == []
    assert latest["evaluated"] is True
    assert latest["generated_at"] == "2026-11-12T06:30:00+09:00"
    assert latest["market_dates"] == {"us": "2026-11-11", "jp": "2026-11-11"}
    assert latest["page_url"] == ""
    assert set(latest["areas"]) == {"us", "jp", "semi"}
    assert latest["areas"]["us"]["prev_ratio"] is None
    assert latest["areas"]["us"]["reason"]
    assert latest["metrics"]["fg"]["status"] == "live"
    assert latest["metrics"]["topix_per"]["status"] == "manual"
    tickers = {t["symbol"]: t for t in latest["tickers"]}
    assert len(tickers) == 7
    assert tickers["285A.T"]["verdict"] == "データなし"
    assert tickers["285A.T"]["drop_pct"] is None
    assert tickers["NVDA"]["price"] is not None
    assert tickers["NVDA"]["prev_verdict"] is None
    assert len(history) == 1
    entry = history[0]
    assert entry["date"] == "2026-11-12"
    assert entry["backfill"] is False
    assert entry["market_dates"] == latest["market_dates"]
    assert entry["areas"]["us"]["ratio"] == latest["areas"]["us"]["ratio"]
    assert entry["verdicts"]["NVDA"] == tickers["NVDA"]["verdict"]


def test_page_url_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGE_URL", "https://example.github.io/dash/")
    root = make_root(tmp_path)
    run_daily(root, make_fetchers("2026-11-11"), at(12), None)
    assert read_latest(root)["page_url"] == "https://example.github.io/dash/"


def test_weekend_run_not_evaluated(tmp_path):
    root = make_root(tmp_path)
    sent = []
    run_daily(root, make_fetchers("2026-11-06"), at(7), lambda s, b: sent.append(s))
    first = read_latest(root)
    run_daily(root, make_fetchers("2026-11-06", fg_value=80.0), at(8), lambda s, b: sent.append(s))
    second = read_latest(root)
    history = load_history(root / "docs" / "data" / "history.json")
    assert second["evaluated"] is False
    assert len(history) == 1
    assert second["generated_at"] == "2026-11-08T06:30:00+09:00"
    assert second["generated_at"] != first["generated_at"]
    # areas and tickers carried forward, metrics refreshed
    assert second["areas"] == first["areas"]
    assert second["tickers"] == first["tickers"]
    assert second["metrics"]["fg"]["value"] == 80.0
    assert sent == []


def test_second_evaluation_sets_prev_values(tmp_path):
    root = make_root(tmp_path)
    run_daily(root, make_fetchers("2026-11-10"), at(11), None)
    first = read_latest(root)
    run_daily(root, make_fetchers("2026-11-11"), at(12), None)
    second = read_latest(root)
    assert second["evaluated"] is True
    for area in ("us", "jp", "semi"):
        assert second["areas"][area]["prev_ratio"] == first["areas"][area]["ratio"]
    prev = {t["symbol"]: t["verdict"] for t in first["tickers"]}
    for t in second["tickers"]:
        assert t["prev_verdict"] == prev[t["symbol"]]
    assert len(load_history(root / "docs" / "data" / "history.json")) == 2


def test_cnn_blocked_fg_missing_and_single_failure_mail(tmp_path):
    root = make_root(tmp_path)
    sent: list[tuple[int, str]] = []
    run_no = 0

    def send(subject, body):
        sent.append((run_no, subject))
        return True

    days = pd.bdate_range("2026-11-02", periods=6)
    statuses = []
    for run_no, d in enumerate(days, start=1):
        fetchers = make_fetchers(d.date().isoformat(), fg_fail=run_no > 1)
        now = datetime.combine(d.date() + timedelta(days=1), datetime.min.time(), JST)
        run_daily(root, fetchers, now, send)
        fg = read_latest(root)["metrics"]["fg"]
        statuses.append(fg["status"])
        if fg["status"] == "stale":
            assert fg["value"] == 42.0
            assert fg["as_of"] == days[0].date().isoformat()

    assert statuses == ["live", "stale", "stale", "stale", "missing", "missing"]
    failures = [(n, s) for n, s in sent if s.startswith("【取得失敗】")]
    assert len(failures) == 1
    assert failures[0][0] == 5
    assert "Fear & Greed" in failures[0][1]


def test_send_failure_counted(tmp_path):
    root = make_root(tmp_path)
    run_daily(root, make_fetchers("2026-11-10"), at(11), None)
    path = root / "docs" / "data" / "latest.json"
    data = read_latest(root)
    data["metrics"]["fg"]["status"] = "missing"  # next run reports a recovery
    path.write_text(json.dumps(data), encoding="utf-8")
    result = run_daily(root, make_fetchers("2026-11-11"), at(12), lambda s, b: False)
    assert any(s.startswith("【回復】") for s in result["notifications"])
    assert result["send_failures"] == len(result["notifications"])
    assert read_latest(root)["generated_at"] == "2026-11-12T06:30:00+09:00"


def test_manual_yaml_broken_continues(tmp_path):
    root = make_root(tmp_path, manual="topix_per: {value: [unclosed\n  ::: broken")
    run_daily(root, make_fetchers("2026-11-11"), at(12), None)
    latest = read_latest(root)
    assert latest["metrics"]["topix_per"]["status"] == "missing"
    assert latest["metrics"]["sox_per"]["status"] == "missing"
    assert latest["evaluated"] is True


def test_backfill_creates_entries_without_hold(tmp_path):
    root = make_root(tmp_path)
    n = run_backfill(root, make_fetchers("2026-11-11", n=30, fg_fail=True), date(2026, 11, 12))
    history = load_history(root / "docs" / "data" / "history.json")
    assert n == 30
    assert len(history) == 30
    assert all(e["backfill"] is True for e in history)
    assert all(not a["on_hold"] for e in history for a in e["areas"].values())
    assert history[-1]["date"] == "2026-11-11"
    assert history[-1]["market_dates"] == {"us": "2026-11-11", "jp": "2026-11-11"}
    assert set(history[0]["areas"]["us"]) == {
        "ratio", "raw_ratio", "ratio_excl_manual", "points", "on_hold", "pending_down"
    }
    assert "reason" not in history[0]["areas"]["us"]
    assert len(history[0]["verdicts"]) == 7
    assert not (root / "docs" / "data" / "latest.json").exists()


def test_backfill_respects_days_window(tmp_path):
    root = make_root(tmp_path)
    n = run_backfill(root, make_fetchers("2026-11-11", n=30), date(2026, 11, 12), days=7)
    history = load_history(root / "docs" / "data" / "history.json")
    assert n == len(history)
    assert all(e["date"] > "2026-11-05" for e in history)
    assert 0 < n <= 7


def test_backfill_keeps_daily_entries(tmp_path):
    root = make_root(tmp_path)
    path = root / "docs" / "data" / "history.json"
    daily_entry = {
        "date": "2026-11-05", "backfill": False,
        "market_dates": {"us": "2026-11-05", "jp": "2026-11-05"},
        "areas": {a: {"ratio": 90, "raw_ratio": 90, "ratio_excl_manual": 90, "points": 9,
                      "on_hold": False, "pending_down": None} for a in ("us", "jp", "semi")},
        "verdicts": {"NVDA": "marker"},
    }
    save_history(path, [daily_entry])
    n = run_backfill(root, make_fetchers("2026-11-11", n=30), date(2026, 11, 12))
    history = load_history(path)
    assert n == 29
    assert len(history) == 30
    kept = [e for e in history if e["date"] == "2026-11-05"]
    assert kept == [daily_entry]


def test_daily_after_backfill_same_market_data_evaluates(tmp_path):
    root = make_root(tmp_path)
    run_backfill(root, make_fetchers("2026-11-11", n=30), date(2026, 11, 12))
    run_daily(root, make_fetchers("2026-11-11", n=30), at(12), None)
    latest = read_latest(root)
    history = load_history(root / "docs" / "data" / "history.json")
    assert latest["evaluated"] is True
    assert latest["areas"]["us"]["reason"]
    # the backfill entry for the same market data is replaced by the daily one
    assert len(history) == 30
    assert history[-1]["backfill"] is False
    assert [e["market_dates"] for e in history].count(latest["market_dates"]) == 1


def _cli_setup(tmp_path, monkeypatch, sends):
    root = make_root(tmp_path)
    run_daily(root, make_fetchers("2026-11-11"), at(12), None)
    data = read_latest(root)
    data["metrics"]["fg"]["status"] = "missing"  # next run will report a recovery
    (root / "docs" / "data" / "latest.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, "default_fetchers", lambda env: make_fetchers("2026-11-11"))

    def fake_send(subject, body, env):
        sends.append(subject)
        return False

    monkeypatch.setattr(cli, "send_gmail", fake_send)
    return root


def test_main_daily_exits_1_when_configured_send_fails(tmp_path, monkeypatch):
    sends = []
    root = _cli_setup(tmp_path, monkeypatch, sends)
    for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "NOTIFY_TO"):
        monkeypatch.setenv(k, "x")
    assert cli.main(["daily"]) == 1
    assert sends and sends[0].startswith("【回復】")
    assert read_latest(root)["metrics"]["fg"]["status"] == "live"


def test_main_daily_exits_0_when_gmail_not_configured(tmp_path, monkeypatch):
    sends = []
    root = _cli_setup(tmp_path, monkeypatch, sends)
    for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "NOTIFY_TO"):
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["daily"]) == 0
    assert sends == []
    assert read_latest(root)["metrics"]["fg"]["status"] == "live"


def test_main_backfill_days_option(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, "default_fetchers", lambda env: make_fetchers("2026-11-11", n=30))
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 12))
    assert cli.main(["backfill", "--days", "7"]) == 0
    assert 0 < len(load_history(root / "docs" / "data" / "history.json")) <= 7


def test_non_evaluation_run_does_not_age_stale_metrics(tmp_path):
    root = make_root(tmp_path)
    run_daily(root, make_fetchers("2026-11-05"), at(6), None)
    run_daily(root, make_fetchers("2026-11-06", fg_fail=True), at(7), None)
    assert read_latest(root)["metrics"]["fg"]["stale_evals"] == 1
    run_daily(root, make_fetchers("2026-11-06", fg_fail=True), at(8), None)
    latest = read_latest(root)
    assert latest["evaluated"] is False
    assert latest["metrics"]["fg"]["status"] == "stale"
    assert latest["metrics"]["fg"]["stale_evals"] == 1
