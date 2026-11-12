"""Wires fetch -> metrics -> scoring -> verdicts -> history / latest.json -> notifications.

All calendar dates are Asia/Tokyo (Ruling R4). Network access happens only inside the
callables held by `Fetchers`; tests inject fakes.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import TickerConfig, load_manual, load_rules, load_tickers
from .fetch_cnn import fetch_fear_greed
from .fetch_fred import FRED_SERIES, fetch_fred
from .fetch_yahoo import MARKET_SYMBOLS, fetch_closes
from .history import is_new_evaluation, load_history, save_history
from .indicators import as_of as truncate_asof, drawdown_from_high
from .metrics import METRIC_FREQ, RawData, carry_forward, compute_metrics
from .models import AreaResult, Metric, TickerResult
from .notify import build_notifications
from .reasons import area_reason, ticker_reason
from .scoring import evaluate_area, points_to_ratio
from .verdict import ticker_verdict

log = logging.getLogger(__name__)

# Japan has no DST, so a fixed offset equals Asia/Tokyo and needs no tzdata on Windows.
JST = timezone(timedelta(hours=9), "JST")
AREAS = ("us", "jp", "semi")
MARKETS = {"us": "^GSPC", "jp": "^N225"}
HISTORY_AREA_KEYS = ("ratio", "raw_ratio", "ratio_excl_manual", "points", "on_hold", "pending_down")


@dataclass
class Fetchers:
    closes: Callable[[list[str]], dict[str, pd.Series]]
    fred: Callable[[str], pd.Series]
    fear_greed: Callable[[], pd.Series]


def default_fetchers(env: Mapping[str, str]) -> Fetchers:
    key = env.get("FRED_API_KEY", "")
    # fetch_fred raises when the key is empty, so a missing key marks FRED metrics missing.
    return Fetchers(
        closes=fetch_closes,
        fred=lambda series_id: fetch_fred(series_id, key),
        fear_greed=fetch_fear_greed,
    )


def collect_raw(fetchers: Fetchers, symbols: list[str]) -> RawData:
    raw = RawData()
    try:
        raw.closes = fetchers.closes(symbols)
    except Exception as exc:
        raw.errors["yahoo"] = f"{type(exc).__name__}: {exc}"
    for sym in symbols:
        if sym not in raw.closes and "yahoo" not in raw.errors:
            raw.errors[f"yahoo:{sym}"] = "no data"
    for series_id in FRED_SERIES:
        try:
            raw.fred[series_id] = fetchers.fred(series_id)
        except Exception as exc:
            raw.errors[f"fred:{series_id}"] = f"{type(exc).__name__}: {exc}"
    try:
        raw.fg = fetchers.fear_greed()
    except Exception as exc:
        raw.errors["cnn"] = f"{type(exc).__name__}: {exc}"
    for source, reason in raw.errors.items():
        log.warning("fetch failed: %s: %s", source, reason)
    return raw


# ---------- helpers ----------

def _paths(root: Path) -> dict[str, Path]:
    data = root / "docs" / "data"
    return {
        "rules": root / "config" / "rules.yaml",
        "tickers": root / "config" / "tickers.yaml",
        "manual": root / "config" / "manual.yaml",
        "latest": data / "latest.json",
        "history": data / "history.json",
    }


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_latest(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("previous latest.json is unreadable, treating as first run: %s", exc)
        return None
    if not isinstance(data, dict) or not {"metrics", "areas", "tickers"} <= data.keys():
        log.error("previous latest.json has an unexpected shape, treating as first run")
        return None
    return data


def _metric_to_dict(m: Metric) -> dict:
    d = asdict(m)
    d.pop("key")
    return d


def _metrics_from_latest(latest: dict | None) -> dict[str, Metric] | None:
    if latest is None:
        return None
    out: dict[str, Metric] = {}
    for key, d in latest.get("metrics", {}).items():
        try:
            out[key] = Metric(key=key, **d)
        except TypeError:
            log.warning("previous metric %s has an unexpected shape; ignored", key)
    return out


def _hold_without_aging(
    current: dict[str, Metric], previous: dict[str, Metric]
) -> dict[str, Metric]:
    """Non-evaluation run: a metric that failed now keeps the previous one without aging,
    because stale_evals counts evaluation days only (spec 7.5). A previous stale metric is
    reused as-is; a previous live one becomes stale with stale_evals 0 (it was not fetched
    by this run, so it must not be shown as live)."""
    out = dict(current)
    for key, cur in current.items():
        prev = previous.get(key)
        if cur.status != "missing" or key not in METRIC_FREQ or prev is None or prev.value is None:
            continue
        if prev.status == "stale":
            out[key] = replace(prev, extra=dict(prev.extra))
        elif prev.status == "live":
            out[key] = replace(prev, status="stale", stale_evals=0, extra=dict(prev.extra))
    return out


def _last_date(s: pd.Series | None) -> str | None:
    if s is None:
        return None
    s = s.dropna()
    return None if s.empty else s.index.max().date().isoformat()


def _ticker_result(
    t: TickerConfig, series: pd.Series | None, area_ratio: int, rules: dict
) -> tuple[TickerResult, list[str]]:
    dd = drawdown_from_high(series) if series is not None and not series.dropna().empty else None
    drop = dd[0] if dd else None
    price = float(series.dropna().sort_index().iloc[-1]) if dd else None
    verdict, notes = ticker_verdict(t, area_ratio, drop, rules)
    return TickerResult(t.symbol, t.name, t.area, price, drop, verdict), notes


def _history_areas(areas: dict[str, AreaResult]) -> dict[str, dict]:
    return {a: {k: getattr(r, k) for k in HISTORY_AREA_KEYS} for a, r in areas.items()}


def _area_to_dict(r: AreaResult) -> dict:
    d = asdict(r)
    d.pop("area")
    return d


# ---------- daily ----------

def run_daily(
    root: Path,
    fetchers: Fetchers,
    now: datetime,
    send: Callable[[str, str], bool | None] | None,
) -> dict:
    """One daily run. Writes history.json / latest.json, then sends notifications.

    Returns {"latest": <latest dict>, "notifications": [subjects], "send_failures": n}.
    A send that returns False counts as a failure (None or True counts as sent).
    """
    root = Path(root)
    paths = _paths(root)
    now_jst = now.astimezone(JST)
    today = now_jst.date()

    rules = load_rules(paths["rules"])
    tickers = load_tickers(paths["tickers"])
    manual = load_manual(paths["manual"], today, rules["manual_overdue_days"])

    symbols = list(dict.fromkeys(MARKET_SYMBOLS + [t.symbol for t in tickers]))
    raw = collect_raw(fetchers, symbols)
    prev_latest = _read_latest(paths["latest"])
    history = load_history(paths["history"])
    last_entry = history[-1] if history else None
    generated_at = now_jst.isoformat(timespec="seconds")

    market_ok = True
    market_dates = {}
    for market, sym in MARKETS.items():
        d = _last_date(raw.closes.get(sym))
        if d is None:
            market_ok = False
            if last_entry is not None:
                # A failed fetch must not look like new market data.
                d = (last_entry.get("market_dates") or {}).get(market)
        market_dates[market] = d
    if not market_ok:
        log.error("market index fetch failed; keeping the last evaluation (R18)")

    # evaluated: new market data, written to history. recompute: nothing to carry forward
    # (latest.json absent/unreadable), so rebuild the state of the entry that already holds
    # this market data from the entry before it, without advancing it.
    recompute = False
    chain_from = last_entry
    if market_ok and is_new_evaluation(market_dates, last_entry):
        evaluated = True
    elif prev_latest is None:
        recompute = True
        if last_entry is not None and not is_new_evaluation(market_dates, last_entry):
            chain_from = history[-2] if len(history) >= 2 else None
        # Only a backfill entry may be replaced by the daily evaluation of the same data (F1).
        evaluated = market_ok and last_entry is not None and last_entry.get("backfill") is True
        if evaluated:
            history = history[:-1]
    else:
        evaluated = False

    metrics = compute_metrics(raw, asof=None, manual=manual)
    prev_metrics = _metrics_from_latest(prev_latest)
    if evaluated or not market_ok:
        # A market-fetch-failed run ages metrics like an evaluation day, so an outage reaches
        # missing (and is mailed) instead of freezing the page (R18).
        metrics = carry_forward(metrics, prev_metrics, rules["stale_limits"], METRIC_FREQ)
    elif prev_metrics:
        metrics = _hold_without_aging(metrics, prev_metrics)

    prev_fetch = (prev_latest or {}).get("market_fetch") or {}
    if market_ok:
        market_fetch = {"ok": True, "failed_since": None}
    elif prev_fetch.get("ok") is False and prev_fetch.get("failed_since"):
        market_fetch = {"ok": False, "failed_since": prev_fetch["failed_since"]}
    else:
        market_fetch = {"ok": False, "failed_since": generated_at}

    latest = {
        "generated_at": generated_at,
        "evaluated": evaluated,
        "market_dates": market_dates,
        "market_fetch": market_fetch,
        "metrics": {k: _metric_to_dict(m) for k, m in metrics.items()},
        "areas": {},
        "tickers": [],
        "page_url": os.environ.get("PAGE_URL", ""),
        # Values the page needs but cannot read from config/rules.yaml itself.
        "display": {
            "stale_page_hours": rules["stale_page_hours"],
            "normal_ratio": points_to_ratio(0, rules["ratio_steps"]),
        },
    }

    if evaluated or recompute:
        prev_areas = (chain_from or {}).get("areas") or {}
        prev_verdicts = (chain_from or {}).get("verdicts") or {}
        areas: dict[str, AreaResult] = {}
        for area in AREAS:
            r = evaluate_area(area, metrics, rules, prev=prev_areas.get(area))
            r.reason = area_reason(r, metrics)
            areas[area] = r
        results: list[TickerResult] = []
        for t in tickers:
            tr, notes = _ticker_result(t, raw.closes.get(t.symbol), areas[t.area].ratio, rules)
            tr.reason = ticker_reason(t, tr.drop_pct, areas[t.area], metrics, notes)
            tr.prev_verdict = prev_verdicts.get(t.symbol)
            results.append(tr)
        latest["areas"] = {a: _area_to_dict(r) for a, r in areas.items()}
        latest["tickers"] = [asdict(tr) for tr in results]
        if evaluated:
            history.append({
                "date": today.isoformat(),
                "backfill": False,
                "market_dates": market_dates,
                "areas": _history_areas(areas),
                "verdicts": {tr.symbol: tr.verdict for tr in results},
            })
            save_history(paths["history"], history)
    else:
        latest["areas"] = prev_latest["areas"]
        latest["tickers"] = prev_latest["tickers"]

    _write_json(paths["latest"], latest)

    notifications = build_notifications(prev_latest, latest, latest["page_url"])
    failures = 0
    if send is not None:
        for subject, body in notifications:
            if send(subject, body) is False:
                failures += 1
    return {
        "latest": latest,
        "notifications": [s for s, _ in notifications],
        "send_failures": failures,
    }


# ---------- backfill ----------

def _trading_dates(raw: RawData, start: date, end: date) -> list[date]:
    dates: set[date] = set()
    for sym in MARKETS.values():
        s = raw.closes.get(sym)
        if s is None:
            continue
        for ts in s.dropna().index:
            d = ts.date()
            if start < d <= end:
                dates.add(d)
    return sorted(dates)


def run_backfill(
    root: Path, fetchers: Fetchers, today: date, days: int = 365
) -> int | None:
    """Recompute history for past trading days (no hold rule, no manual PER, no reasons,
    no notifications). A one-time setup step: once history holds a daily (`backfill: false`)
    entry it refuses and returns None without writing (R20), because the daily chain would
    no longer follow from the recomputed entries. Otherwise returns the number created."""
    root = Path(root)
    paths = _paths(root)
    history = load_history(paths["history"])
    if any(e.get("backfill") is False for e in history):
        log.error("backfill refused: history already has daily entries (backfill is a "
                  "one-time setup step; delete docs/data/history.json to start over)")
        return None
    rules = load_rules(paths["rules"])
    tickers = load_tickers(paths["tickers"])
    symbols = list(dict.fromkeys(MARKET_SYMBOLS + [t.symbol for t in tickers]))
    raw = collect_raw(fetchers, symbols)

    existing = {e["date"]: e for e in history}
    created = 0
    prev_entry: dict | None = None
    for d in _trading_dates(raw, today - timedelta(days=days), today):
        iso = d.isoformat()
        metrics = compute_metrics(raw, asof=d, manual=None)
        prev_areas = (prev_entry or {}).get("areas") or {}
        areas = {
            a: evaluate_area(a, metrics, rules, prev=prev_areas.get(a), apply_hold=False)
            for a in AREAS
        }
        verdicts = {}
        for t in tickers:
            s = raw.closes.get(t.symbol)
            s = truncate_asof(s, d) if s is not None else None
            tr, _ = _ticker_result(t, s, areas[t.area].ratio, rules)
            verdicts[t.symbol] = tr.verdict
        market_dates = {
            m: _last_date(truncate_asof(raw.closes[sym], d)) if sym in raw.closes else None
            for m, sym in MARKETS.items()
        }
        entry = {
            "date": iso,
            "backfill": True,
            "market_dates": market_dates,
            "areas": _history_areas(areas),
            "verdicts": verdicts,
        }
        existing[iso] = entry
        prev_entry = entry
        created += 1

    save_history(paths["history"], list(existing.values()))
    return created
