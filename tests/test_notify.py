import copy
import smtplib

from dash import notify
from dash.notify import build_notifications, send_gmail


def make_latest(**over):
    base = {
        "evaluated": True,
        "metrics": {
            "fg": {"label": "Fear & Greed", "status": "live"},
            "cpi_yoy": {"label": "CPI", "status": "live"},
        },
        "areas": {
            "us": {"ratio": 35, "on_hold": False, "reason": "米国の理由"},
            "jp": {"ratio": 20, "on_hold": False, "reason": "日本の理由"},
            "semi": {"ratio": 30, "on_hold": False, "reason": "半導体の理由"},
        },
        "tickers": [
            {"symbol": "SOXL", "name": "SOXL", "area": "semi", "verdict": "保有", "reason": "SOXLの理由"},
            {"symbol": "6146.T", "name": "ディスコ", "area": "jp", "verdict": "保有", "reason": "ディスコの理由"},
        ],
    }
    base.update(over)
    return base


URL = "https://example.test/dash/"


def test_no_prev_no_notifications():
    assert build_notifications(None, make_latest(), URL) == []


def test_unchanged_no_notifications():
    assert build_notifications(make_latest(), make_latest(), URL) == []


def test_ratio_and_verdict_change_subject():
    prev = make_latest()
    curr = make_latest()
    curr["areas"]["semi"]["ratio"] = 40
    curr["tickers"][0]["verdict"] = "利確 1/3"
    out = build_notifications(prev, curr, URL)
    assert len(out) == 1
    subject, body = out[0]
    assert subject == "【判定変更】半導体 30%→40% / SOXL 保有→利確 1/3"
    assert "半導体の理由" in body and "SOXLの理由" in body
    assert body.rstrip().endswith(URL)


def test_subject_truncated_after_two():
    prev = make_latest()
    curr = make_latest()
    curr["areas"]["us"]["ratio"] = 50
    curr["areas"]["semi"]["ratio"] = 40
    curr["tickers"][0]["verdict"] = "利確 1/3"
    subject, body = build_notifications(prev, curr, URL)[0]
    assert subject == "【判定変更】米国 35%→50% / 半導体 30%→40% ほか1件"
    assert "\n" not in subject
    assert "SOXLの理由" in body


def test_empty_page_url_omits_url_line():
    prev = make_latest()
    curr = make_latest()
    curr["areas"]["us"]["ratio"] = 50
    _, body = build_notifications(prev, curr, "")[0]
    assert "http" not in body
    assert not body.endswith("\n\n")


def test_not_evaluated_skips_verdict_changes():
    prev = make_latest()
    curr = make_latest(evaluated=False)
    curr["areas"]["semi"]["ratio"] = 40
    curr["tickers"][0]["verdict"] = "全利確"
    assert build_notifications(prev, curr, URL) == []


def test_fetch_failure_once():
    prev = make_latest()
    curr = make_latest()
    curr["metrics"]["fg"]["status"] = "missing"
    curr["metrics"]["cpi_yoy"]["status"] = "missing"
    out = build_notifications(prev, curr, URL)
    assert len(out) == 1
    assert out[0][0] == "【取得失敗】Fear & Greed, CPI"
    assert build_notifications(curr, copy.deepcopy(curr), URL) == []


def test_failure_notified_even_when_not_evaluated():
    prev = make_latest()
    curr = make_latest(evaluated=False)
    curr["metrics"]["fg"]["status"] = "missing"
    out = build_notifications(prev, curr, URL)
    assert [s for s, _ in out] == ["【取得失敗】Fear & Greed"]


def test_stale_is_not_failure():
    prev = make_latest()
    curr = make_latest()
    curr["metrics"]["fg"]["status"] = "stale"
    assert build_notifications(prev, curr, URL) == []


def test_recovery_notified():
    prev = make_latest()
    prev["metrics"]["fg"]["status"] = "missing"
    out = build_notifications(prev, make_latest(), URL)
    assert [s for s, _ in out] == ["【回復】Fear & Greed"]


def test_on_hold_start_and_release_notified():
    prev = make_latest()
    curr = make_latest()
    curr["areas"]["semi"]["on_hold"] = True
    started = build_notifications(prev, curr, URL)
    assert len(started) == 1
    assert started[0][0].startswith("【取得失敗】") and "半導体" in started[0][0]
    released = build_notifications(curr, make_latest(), URL)
    assert len(released) == 1
    assert released[0][0].startswith("【回復】") and "半導体" in released[0][0]


def test_on_hold_area_not_compared():
    prev = make_latest()
    curr = make_latest()
    curr["areas"]["semi"]["on_hold"] = True
    curr["areas"]["semi"]["ratio"] = 50
    curr["tickers"][0]["verdict"] = "全利確"  # SOXL is in semi
    curr["tickers"][1]["verdict"] = "買い増し"  # ディスコ is in jp
    out = build_notifications(prev, curr, URL)
    subjects = [s for s, _ in out]
    change = [s for s in subjects if s.startswith("【判定変更】")]
    assert change == ["【判定変更】ディスコ 保有→買い増し"]
    assert not any("→50%" in s or "SOXL" in s for s in change)


def test_send_gmail_missing_env_does_not_raise(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not connect")

    monkeypatch.setattr(smtplib, "SMTP_SSL", boom)
    send_gmail("s", "b", {})
    send_gmail("s", "b", {"GMAIL_ADDRESS": "a@example.test", "GMAIL_APP_PASSWORD": "x"})


def test_send_gmail_sends_once(monkeypatch):
    calls = {"init": [], "login": [], "sent": []}

    class FakeSMTP:
        def __init__(self, host, port, *a, **k):
            calls["init"].append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, pw):
            calls["login"].append((user, pw))

        def send_message(self, msg):
            calls["sent"].append(msg)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    env = {"GMAIL_ADDRESS": "from@example.test", "GMAIL_APP_PASSWORD": "secret-pw", "NOTIFY_TO": "to@example.test"}
    send_gmail("【判定変更】テスト", "本文です", env)
    assert calls["init"] == [("smtp.gmail.com", 465)]
    assert calls["login"] == [("from@example.test", "secret-pw")]
    assert len(calls["sent"]) == 1
    msg = calls["sent"][0]
    assert msg["Subject"] == "【判定変更】テスト"
    assert msg["From"] == "from@example.test" and msg["To"] == "to@example.test"
    assert "本文です" in msg.get_content()


def test_send_gmail_failure_does_not_log_secrets(monkeypatch, caplog):
    class BadSMTP:
        def __init__(self, *a, **k):
            raise OSError("down")

    monkeypatch.setattr(smtplib, "SMTP_SSL", BadSMTP)
    env = {"GMAIL_ADDRESS": "from@example.test", "GMAIL_APP_PASSWORD": "secret-pw", "NOTIFY_TO": "to@example.test"}
    send_gmail("s", "b", env)  # must not raise
    assert "secret-pw" not in caplog.text and "to@example.test" not in caplog.text
