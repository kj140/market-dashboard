"""通知: 前回と今回の latest.json の差分から (件名, 本文) を作り、Gmail で送る。"""
from __future__ import annotations

import logging
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage

log = logging.getLogger(__name__)

AREA_NAMES = {"us": "米国", "jp": "日本", "semi": "半導体"}
MAX_SUBJECT_ITEMS = 2


def _area_name(area: str) -> str:
    return AREA_NAMES.get(area, area)


def _subject(prefix: str, items: list[str], sep: str) -> str:
    shown = sep.join(items[:MAX_SUBJECT_ITEMS])
    rest = len(items) - MAX_SUBJECT_ITEMS
    if rest > 0:
        shown += f" ほか{rest}件"
    return f"{prefix}{shown}"


def _body(lines: list[str], page_url: str) -> str:
    text = "\n".join(lines)
    if page_url:
        text += f"\n\n{page_url}"
    return text + "\n"


def _verdict_changes(prev: dict, curr: dict) -> tuple[list[str], list[str]]:
    """(件名用の項目, 本文用の行) を返す。保留中の分野とその銘柄は比較しない。"""
    items: list[str] = []
    lines: list[str] = []
    prev_areas = prev.get("areas", {})
    curr_areas = curr.get("areas", {})
    for area, c in curr_areas.items():
        p = prev_areas.get(area)
        if c.get("on_hold") or p is None or p.get("ratio") == c.get("ratio"):
            continue
        items.append(f"{_area_name(area)} {p['ratio']}%→{c['ratio']}%")
        lines.append(f"{_area_name(area)}: {p['ratio']}%→{c['ratio']}%")
        if c.get("reason"):
            lines.append(f"  {c['reason']}")
    prev_tickers = {t["symbol"]: t for t in prev.get("tickers", [])}
    for t in curr.get("tickers", []):
        p = prev_tickers.get(t["symbol"])
        if curr_areas.get(t.get("area"), {}).get("on_hold"):
            continue
        if p is None or p.get("verdict") == t.get("verdict"):
            continue
        items.append(f"{t['name']} {p['verdict']}→{t['verdict']}")
        lines.append(f"{t['name']}: {p['verdict']}→{t['verdict']}")
        if t.get("reason"):
            lines.append(f"  {t['reason']}")
    return items, lines


def _state_changes(prev: dict, curr: dict) -> tuple[list[str], list[str]]:
    """(新たに missing / 保留になったもの, 回復 / 保留解除したもの) の表示名。"""
    failed: list[str] = []
    recovered: list[str] = []
    prev_metrics = prev.get("metrics", {})
    for key, m in curr.get("metrics", {}).items():
        p = prev_metrics.get(key)
        if p is None:
            continue
        was_missing = p.get("status") == "missing"
        is_missing = m.get("status") == "missing"
        label = m.get("label", key)
        if is_missing and not was_missing:
            failed.append(label)
        elif was_missing and not is_missing:
            recovered.append(label)
    prev_areas = prev.get("areas", {})
    for area, a in curr.get("areas", {}).items():
        p = prev_areas.get(area)
        if p is None or bool(p.get("on_hold")) == bool(a.get("on_hold")):
            continue
        if a.get("on_hold"):
            failed.append(f"{_area_name(area)}(判定保留)")
        else:
            recovered.append(f"{_area_name(area)}(保留解除)")
    return failed, recovered


def build_notifications(prev: dict | None, curr: dict, page_url: str) -> list[tuple[str, str]]:
    """前回と今回の latest.json から (件名, 本文) のリストを作る。前回が無ければ空。"""
    if prev is None:
        return []
    out: list[tuple[str, str]] = []

    if curr.get("evaluated"):
        items, lines = _verdict_changes(prev, curr)
        if items:
            out.append((_subject("【判定変更】", items, " / "), _body(lines, page_url)))

    failed, recovered = _state_changes(prev, curr)
    if failed:
        lines = ["取得できなくなった項目:"] + [f"- {x}" for x in failed]
        out.append((_subject("【取得失敗】", failed, ", "), _body(lines, page_url)))
    if recovered:
        lines = ["回復した項目:"] + [f"- {x}" for x in recovered]
        out.append((_subject("【回復】", recovered, ", "), _body(lines, page_url)))
    return out


def send_gmail(subject: str, body: str, env: Mapping[str, str]) -> bool:
    """Gmail(SMTP over SSL)で送る。送れたら True。設定不足・送信失敗は例外にせず False を返す。"""
    address = env.get("GMAIL_ADDRESS")
    password = env.get("GMAIL_APP_PASSWORD")
    to = env.get("NOTIFY_TO")
    if not (address and password and to):
        log.warning("Gmail の設定(GMAIL_ADDRESS / GMAIL_APP_PASSWORD / NOTIFY_TO)が不足しているため通知を送りません")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to
    msg.set_content(body, charset="utf-8")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(address, password)
            smtp.send_message(msg)
    except Exception as exc:  # 認証情報を含み得るので型名だけ記録する
        log.error("Gmail の送信に失敗しました: %s", type(exc).__name__)
        return False
    return True
