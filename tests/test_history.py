import json
from datetime import date

from dash.history import entry_near, is_new_evaluation, load_history, save_history


def test_load_history_missing_file_empty(tmp_path):
    assert load_history(tmp_path / "nope.json") == []


def test_load_history_corrupt_empty(tmp_path, caplog):
    p = tmp_path / "history.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_history(p) == []
    assert "history" in caplog.text.lower()


def test_save_history_replaces_same_date(tmp_path):
    p = tmp_path / "sub" / "history.json"
    save_history(p, [
        {"date": "2026-11-12", "verdicts": {"SOXL": "保有"}},
        {"date": "2026-11-10", "verdicts": {}},
        {"date": "2026-11-12", "verdicts": {"SOXL": "利確 1/3"}},
    ])
    entries = load_history(p)
    assert [e["date"] for e in entries] == ["2026-11-10", "2026-11-12"]
    assert entries[1]["verdicts"]["SOXL"] == "利確 1/3"
    assert "利確 1/3" in p.read_text(encoding="utf-8")
    assert json.loads(p.read_text(encoding="utf-8"))["entries"] == entries
    assert [f.name for f in p.parent.iterdir()] == ["history.json"]


def test_is_new_evaluation_weekend_false():
    dates = {"us": "2026-11-07", "jp": "2026-11-07"}
    assert is_new_evaluation(dates, {"market_dates": dict(dates)}) is False


def test_is_new_evaluation_one_market_holiday_true():
    last = {"market_dates": {"us": "2026-11-06", "jp": "2026-11-09"}}
    assert is_new_evaluation({"us": "2026-11-09", "jp": "2026-11-09"}, last) is True


def test_is_new_evaluation_no_previous_true():
    assert is_new_evaluation({"us": "2026-11-07", "jp": "2026-11-07"}, None) is True


def test_entry_near_week_ago():
    entries = [{"date": "2026-11-03"}, {"date": "2026-11-05"}, {"date": "2026-11-10"}]
    assert entry_near(entries, date(2026, 11, 5))["date"] == "2026-11-05"
    assert entry_near(entries, date(2026, 11, 4))["date"] == "2026-11-03"
    assert entry_near(entries, date(2026, 11, 2)) is None
