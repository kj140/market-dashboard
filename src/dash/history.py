"""履歴ファイル(docs/data/history.json)の読み書きと評価日の判定。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


def load_history(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries is not a list")
        return entries
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.error("history file %s is unreadable, starting empty: %s", path, exc)
        return []


def save_history(path: Path, entries: list[dict]) -> None:
    """日付昇順で保存する。同じ日付は後から来たものが置き換える。"""
    path = Path(path)
    by_date: dict[str, dict] = {}
    for entry in entries:
        by_date[entry["date"]] = entry
    ordered = [by_date[d] for d in sorted(by_date)]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"entries": ordered}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def is_new_evaluation(market_dates: dict[str, str], last_entry: dict | None) -> bool:
    if last_entry is None:
        return True
    last = last_entry.get("market_dates") or {}
    return any(market_dates.get(k) != last.get(k) for k in ("us", "jp"))


def entry_near(entries: list[dict], target: date) -> dict | None:
    """target 以前で最も近い日付のエントリ。"""
    iso = target.isoformat()
    candidates = [e for e in entries if e["date"] <= iso]
    return max(candidates, key=lambda e: e["date"]) if candidates else None
