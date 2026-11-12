"""Template-based Japanese reason text (spec 7.6). No LLM."""
from __future__ import annotations

from .config import TickerConfig
from .metrics import METRIC_LABELS
from .models import AreaResult, Contribution, Metric

HOLD_PREFIX = "判定保留（データ不足）："
NO_SIGNAL = "目立ったシグナルなし"
SEP = "／"


def _md(as_of: str | None) -> str:
    # "2026-11-08" -> "11/08"
    if not as_of or len(as_of) < 10:
        return as_of or ""
    return f"{as_of[5:7]}/{as_of[8:10]}"


def _num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}"


def _body(m: Metric) -> str:
    v = m.value
    if m.key in ("ndx_drop", "n225_drop", "sox_drop"):
        name = {"ndx_drop": "NASDAQ100", "n225_drop": "日経平均", "sox_drop": "SOX"}[m.key]
        s = f"{name} 高値比-{_num(v)}%"
        days = m.extra.get("days")
        if days is not None:
            s += f"（日柄{days}日）"
        return s
    if m.key == "fg":
        return f"Fear & Greed {_num(v, 0)}"
    if m.key == "us10y_streak":
        return f"米10年債4.5%以上 {_num(v, 0)}日連続"
    if m.key == "topix_per":
        return f"TOPIX 予想PER {_num(v)}倍"
    if m.key == "sox_per":
        return f"SOX 予想PER {_num(v)}倍"
    if m.key == "usdjpy_1m":
        return f"ドル円 1か月{v:+.1f}%"
    if m.key == "capex_gdp":
        return f"民間設備投資/GDP {_num(v)}%"
    if m.key == "gdp_spread":
        return f"名目GDP−10年債 {v:+.2f}%"
    if m.key == "cpi_yoy":
        return f"CPI 前年比 {_num(v)}%"
    if m.key == "wti":
        return f"WTI {_num(v)}ドル"
    label, unit = METRIC_LABELS.get(m.key, (m.label, m.unit))
    return f"{label} {_num(v)}{unit or m.unit}"


def metric_phrase(m: Metric) -> str:
    if m.value is None:
        label = METRIC_LABELS.get(m.key, (m.label, ""))[0]
        return f"{label} データなし"
    s = _body(m)
    if m.status == "stale":
        s += f"（前回値 {_md(m.as_of)}）"
    elif m.status == "manual":
        tail = "・要更新" if m.extra.get("overdue") else ""
        s += f"（手入力 {_md(m.as_of)}{tail}）"
    return s


def _top_phrases(
    contributions: list[Contribution], metrics: dict[str, Metric], n: int
) -> list[str]:
    scored = [c for c in contributions if c.points]  # drops 0 and None
    scored.sort(key=lambda c: abs(c.points), reverse=True)  # stable: ties keep order
    out: list[str] = []
    for c in scored:
        key = "sox_drop" if c.key == "sox_combo" else c.key
        m = metrics.get(key)
        if m is None:
            continue
        out.append(metric_phrase(m))
        if len(out) == n:
            break
    return out


def area_reason(result: AreaResult, metrics: dict[str, Metric]) -> str:
    phrases = _top_phrases(result.contributions, metrics, 3)
    text = SEP.join(phrases) if phrases else NO_SIGNAL
    return (HOLD_PREFIX + text) if result.on_hold else text


def ticker_reason(
    t: TickerConfig,
    tr_drop: float | None,
    area: AreaResult,
    metrics: dict[str, Metric],
    adjustments: list[str],
) -> str:
    head = "高値からの下落率はデータなし。" if tr_drop is None else f"高値から-{_num(tr_drop)}%。"
    phrases = _top_phrases(area.contributions, metrics, 2)
    signal = (SEP.join(phrases) + "。") if phrases else ""
    note = (t.note.rstrip("。") + "。") if t.note else ""
    adj = "".join(a.rstrip("。") + "。" for a in adjustments)
    return f"{head}{signal}{note}{adj}"
