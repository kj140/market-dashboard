"""CLI: `python -m dash daily` / `python -m dash backfill [--days 365]` (root = cwd)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from .notify import send_gmail
from .pipeline import JST, default_fetchers, run_backfill, run_daily

log = logging.getLogger("dash")
GMAIL_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "NOTIFY_TO")


def _today() -> date:
    return datetime.now(JST).date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dash")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("daily", help="毎日の取得・判定・通知")
    bf = sub.add_parser("backfill", help="過去の判定をさかのぼって計算する")
    bf.add_argument("--days", type=int, default=365)
    args = parser.parse_args(argv)

    root = Path.cwd()
    fetchers = default_fetchers(os.environ)

    if args.command == "backfill":
        n = run_backfill(root, fetchers, _today(), days=args.days)
        if n is None:
            return 1
        log.info("backfill: created %d entries", n)
        return 0

    configured = all(os.environ.get(k) for k in GMAIL_ENV)
    if configured:
        send = lambda s, b: send_gmail(s, b, os.environ)  # noqa: E731
    else:
        log.warning("Gmail の設定(%s)が不足しているため通知は送りません", " / ".join(GMAIL_ENV))
        send = None
    result = run_daily(root, fetchers, datetime.now(JST), send)
    if result["send_failures"]:
        log.error("通知 %d 件の送信に失敗しました", result["send_failures"])
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
